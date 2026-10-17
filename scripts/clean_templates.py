"""模板噪声清洗 - LLM 语义判定候选行、审计判定、回填清洗存量 Issue。

用法：
    python -m scripts.clean_templates --preview   # 频率预筛 + LLM 判定 + 打印判定表 + 写缓存（不改 body）
    python -m scripts.clean_templates --apply      # 按缓存回填清洗存量 Issue + 重算 embedding

正常全新流程走 build_kb（已在录入时同步判定+清洗）；本脚本用于：
    - --preview：在改动 body 前审计 LLM 的 remove/keep 判定是否合理；
    - --apply：手改 llm_template_cache.json 后，或对存量库就地清洗时，回填 + 重算 embedding。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from issue_kb.config import apply_repo_override
from issue_kb.knowledge import KnowledgeBase
from issue_kb.similarity import SimilarityEngine


def _print_verdicts(kb: KnowledgeBase, candidates: list[dict]):
    """打印候选行的 LLM 判定表（行/出现数/verdict/reason），供人工审计。"""
    classifier = kb.classifier
    if not candidates:
        logger.warning("未发现候选行（样本不足或 min_support 过高）")
        return
    remove_n = sum(
        1 for c in candidates
        if (classifier.verdict(c["text"]) or {}).get("verdict") == "remove"
    )
    judged = sum(1 for c in candidates if classifier.verdict(c["text"]))
    print(
        f"\n候选行 LLM 判定（共 {len(candidates)} 行：剔除 {remove_n} / "
        f"保留 {judged - remove_n} / 未判定 {len(candidates) - judged}，按出现数降序）："
    )
    print("-" * 88)
    for i, c in enumerate(candidates, 1):
        v = classifier.verdict(c["text"]) or {}
        verdict = v.get("verdict")
        reason = v.get("reason", "")
        text = c["text"]
        if len(text) > 40:
            text = text[:40] + "…"
        if verdict == "remove":
            mark = "[剔除]"
        elif verdict == "keep":
            mark = "[保留]"
        else:
            mark = "[未判定]"
        print(f"{i:3d}. [{c['count']:4d} 条] {mark} {text}")
        if reason:
            print(f"          理由: {reason}")
    print("-" * 88)


def _preview_clean_sample(kb: KnowledgeBase, sample_n: int = 3):
    """抽样打印清洗前后 body 对比（选剔除字符最多者，效果最直观）。"""
    issues = kb.list_issues()
    scored = []
    for issue in issues:
        raw = issue.get("body_raw") or issue.get("body", "") or ""
        cleaned = kb.classifier.clean_body(raw)
        scored.append((len(raw) - len(cleaned), issue, raw, cleaned))
    scored.sort(key=lambda t: t[0], reverse=True)  # 按剔除字符数降序
    shown = 0
    for diff, issue, raw, cleaned in scored:
        if diff <= 0 or shown >= sample_n:
            break
        print(f"\n===== #{issue.get('number')} 清洗前后对比（剔除 {diff} 字符）=====")
        print(f"[原始 {len(raw)} 字符]\n{raw[:400]}")
        print(f"\n[清洗后 {len(cleaned)} 字符]\n{cleaned[:400]}")
        print("=" * 44)
        shown += 1


def preview(kb: KnowledgeBase):
    """频率预筛候选 → LLM 判定 → 打印判定表 + 写缓存，不改任何 body。"""
    classifier = kb.classifier
    issues = kb.list_issues()
    if not issues:
        logger.warning("知识库为空，请先运行 build_kb。")
        return
    logger.info(f"全库 {len(issues)} 条 Issue，频率预筛候选 + LLM 语义判定（preview，不改 body）...")
    candidates = classifier.discover_candidates(issues)
    classifier.classify_lines([c["text"] for c in candidates])
    _print_verdicts(kb, candidates)
    _preview_clean_sample(kb)
    logger.info(
        f"判定已写入 {classifier.cache_file}（人可读可编辑）。"
        f"确认无误后用 --apply 回填清洗，或直接 build_kb 录入。"
    )


def apply(kb: KnowledgeBase):
    """按缓存回填清洗存量 Issue（body_raw/body）+ 重算 embedding（不请求 GitCode）。"""
    classifier = kb.classifier
    classifier.reload()  # 重新读缓存（可能已手改 verdict）
    issues = kb.list_issues()
    if not issues:
        logger.warning("知识库为空，请先运行 build_kb --fresh。")
        return
    if classifier.cache_size() == 0:
        logger.warning(
            "LLM 判定缓存为空，无可清洗内容。请先运行 --preview（或 build_kb）生成判定后再 --apply。"
        )
        return
    engine = SimilarityEngine(kb.kb_dir)

    _preview_clean_sample(kb)  # 回填前抽样展示清洗效果

    # 回填：body_raw 保留原文，body 存清洗后（复用 save_issue 的幂等清洗）
    logger.info("回填存量 Issue（body_raw 保留原文，body 存清洗后文本）...")
    for issue in issues:
        original_body = issue.get("body_raw") or issue.get("body", "") or ""
        issue.pop("body_raw", None)  # 移除标记，令 save_issue 重新清洗
        issue["body"] = original_body
        kb.save_issue(issue)
    logger.info(f"已回填 {len(issues)} 条 Issue")

    # 重算 embedding（基于清洗后的 body）
    logger.info("重算 embedding 索引（基于清洗后的 body）...")
    all_issues = kb.list_issues()
    result = engine.rebuild_index(all_issues)
    logger.info(
        f"===== 模板清洗完成 =====\n"
        f"  回填 Issue: {len(issues)} 条\n"
        f"  Embedding 重算: 新增 {result['added']} 条，失败 {len(result['failed'])} 条"
    )
    if result["failed"]:
        logger.warning(f"  失败编号: {result['failed']}，重跑 --apply 可自动补齐")


def main():
    parser = argparse.ArgumentParser(description="Issue 模板噪声清洗（LLM 语义判定）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--preview", action="store_true",
        help="频率预筛 + LLM 判定 + 打印判定表 + 写缓存，不改 body",
    )
    group.add_argument(
        "--apply", action="store_true",
        help="按缓存回填清洗存量 Issue + 重算 embedding",
    )
    parser.add_argument("--repo", type=str, default=None, help="GitCode 仓库地址（owner/repo），默认使用 .env 配置")
    args = parser.parse_args()
    apply_repo_override(args.repo)

    kb = KnowledgeBase()
    if args.preview:
        preview(kb)
    elif args.apply:
        apply(kb)


if __name__ == "__main__":
    main()
