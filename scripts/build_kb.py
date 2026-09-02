"""构建知识库 - 从 GitCode 拉取 Issue 并存入本地知识库，构建 embedding 索引。

用法：
    python -m scripts.build_kb              # 全量构建
    python -m scripts.build_kb --fresh       # 清空后重建
    python -m scripts.build_kb --incremental # 增量更新（只拉取新 issue）
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from issue_kb.config import settings
from issue_kb.gitcode_client import GitCodeClient
from issue_kb.knowledge import KnowledgeBase, IssueData
from issue_kb.similarity import SimilarityEngine


def build(fresh: bool = False, incremental: bool = False):
    kb = KnowledgeBase()
    engine = SimilarityEngine(kb.kb_dir)

    if fresh:
        logger.info("===== 全量重建模式 =====")
        kb.rebuild()

    # 确定拉取策略
    since = None
    if incremental:
        since = kb.get_cursor()
        if since:
            logger.info(f"增量模式：只拉取 {since} 之后更新的 Issue")
        else:
            logger.info("增量模式：无游标记录，将拉取全量")

    # 1. 从 GitCode 拉取 Issue
    logger.info("开始拉取 Issue...")
    with GitCodeClient() as client:
        state = "all" if settings.include_closed else "open"
        raw_issues = client.fetch_all_issues(state=state, since=since)

    if not raw_issues:
        logger.info("没有新的 Issue 需要处理")
        return

    logger.info(f"拉取到 {len(raw_issues)} 条 Issue")

    # 2. 过滤忽略标签
    ignored = settings.ignored_label_set
    if ignored:
        raw_issues = [
            r for r in raw_issues
            if not (set(lb.get("name", "").lower() for lb in r.get("labels", [])) & ignored)
        ]
        logger.info(f"过滤忽略标签后: {len(raw_issues)} 条")

    # 3. 标准化并保存（记录更新的 issue 编号，用于刷新其 embedding）
    issues_data = []
    updated_numbers = []
    for raw in raw_issues:
        data = IssueData.from_gitcode(raw)
        if IssueData.validate(data):
            if kb.get_issue(data["number"]) is not None:
                updated_numbers.append(data["number"])
            issues_data.append(data)

    added, updated = kb.save_issues_batch(issues_data)
    logger.info(f"保存完成: 新增 {added}, 更新 {updated}")

    # 内容更新的 issue 移除旧向量，后续会自动重算，避免用旧向量检索
    for num in updated_numbers:
        engine.remove_embedding(num)

    # 4. 更新游标
    from datetime import datetime, timezone
    kb.set_cursor(datetime.now(timezone.utc).isoformat())

    # 5. 增量构建 embedding 索引：
    #    - 已有向量的 issue 直接跳过（成功部分不重复构建）
    #    - 失败批次记录编号并在最后重试，重跑命令可自动补齐
    all_issues = kb.list_issues()
    result = engine.ensure_index(all_issues)

    logger.info(
        f"===== 知识库构建完成 =====\n"
        f"  Issue 总数: {kb.issue_count()}\n"
        f"  Embedding 索引: {engine.index_size()} 条\n"
        f"  本次: 新增 {result['added']} 条，跳过 {result['skipped']} 条"
    )
    if result["failed"]:
        logger.warning(
            f"  失败 {len(result['failed'])} 条: {result['failed']}\n"
            f"  重新运行 python -m scripts.build_kb 可自动补齐"
        )


def main():
    parser = argparse.ArgumentParser(description="构建 Issue 知识库")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fresh", action="store_true", help="清空后全量重建")
    group.add_argument("--incremental", action="store_true", help="增量更新")
    args = parser.parse_args()
    build(fresh=args.fresh, incremental=args.incremental)


if __name__ == "__main__":
    main()
