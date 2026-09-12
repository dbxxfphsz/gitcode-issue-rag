"""扫描 Issue - 在知识库中查找相似问题并生成报告。

用法：
    python -m scripts.scan_issue --issue 123
    python -m scripts.scan_issue --issue 123 --top-k 5 --mode comment
    python -m scripts.scan_issue --title "xxx报错" --body "详细描述"
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from issue_kb.config import settings
from issue_kb.gitcode_client import GitCodeClient
from issue_kb.knowledge import KnowledgeBase, IssueData
from issue_kb.similarity import SimilarityEngine, _build_issue_text
from issue_kb.report import generate_scan_report
from issue_kb.commenter import IssueCommenter


def _parse_issue_ref(ref: str) -> str | None:
    """从 Issue 编号或链接中提取编号（支持数字和字母数字 ID）。"""
    ref = ref.strip()
    # 纯数字
    if ref.isdigit():
        return int(ref)
    # #123 格式
    if ref.startswith("#") and ref[1:].isdigit():
        return int(ref[1:])
    # URL 格式: .../issues/123 或 .../issues/I7S9F8
    m = re.search(r"/issues/([\w-]+)", ref)
    if m:
        val = m.group(1)
        return int(val) if val.isdigit() else val
    # 字母数字混合 ID（如 GitCode 的 I7S9F8）
    if ref.isalnum() and not ref.isdigit():
        return ref
    return None


def scan(
    issue_number: int | str | None = None,
    title: str | None = None,
    body: str = "",
    top_k: int | None = None,
    mode: str | None = None,
):
    """执行相似性扫描。"""
    kb = KnowledgeBase()
    engine = SimilarityEngine(kb.kb_dir)
    scan_mode = mode or settings.scan_mode

    # 获取目标 issue 数据
    if issue_number:
        # 先尝试从知识库读取（数字 ID 优先）
        num_key = int(issue_number) if str(issue_number).isdigit() else issue_number
        target = kb.get_issue(num_key) if str(num_key).isdigit() else None
        if not target:
            # 从 GitCode API 拉取
            logger.info(f"#{issue_number} 不在知识库中，从 GitCode 拉取...")
            with GitCodeClient() as client:
                raw = client.fetch_issue(issue_number)
                comments = client.fetch_comments(issue_number) if settings.include_comments else []
                target = IssueData.from_gitcode(raw, comments)
    elif title:
        target = {"number": 0, "title": title, "body": body, "state": "open", "url": "", "labels": []}
    else:
        logger.error("请指定 --issue 或 --title")
        return

    # 构建查询文本
    query_text = _build_issue_text(target, include_comments=settings.include_comments)

    # 执行搜索
    results = engine.search(
        query_text,
        top_k=top_k,
        exclude_number=issue_number,
    )

    # 补充 issue 详情（编号归一化为 str，兼容 int/str 混合存储）
    kb_issues = {str(i["number"]): i for i in kb.list_issues()}
    for r in results:
        r["issue"] = kb_issues.get(str(r["number"]), {})

    # 生成报告
    report = generate_scan_report(target, results, kb_issues)

    # 保存报告到文件
    report_dir = kb.kb_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"scan_{issue_number or 'query'}.md"
    report_file.write_text(report, encoding="utf-8")

    # 所有日志输出完毕后再打印报告，避免被日志淹没
    above_threshold = [r for r in results if r["score"] >= settings.similarity_threshold]
    logger.info(
        f"===== 扫描摘要 =====\n"
        f"  目标 Issue: #{target.get('number', '?')} {target.get('title', '')[:50]}\n"
        f"  知识库条目: {len(kb_issues)}\n"
        f"  返回结果: {len(results)} 条\n"
        f"  高于阈值({settings.similarity_threshold:.0%}): {len(above_threshold)} 条\n"
        f"  报告已保存: {report_file}"
    )

    # 报告输出在日志之后，用分隔线区分
    print("\n" + "=" * 60)
    print(report)

    # 如果需要评论模式
    if scan_mode == "comment" and issue_number:
        commenter = IssueCommenter()
        success = commenter.post_scan_report(issue_number, report)
        if success:
            logger.info(f"报告已评论到 #{issue_number}")
        else:
            logger.warning(f"评论发布失败或已存在")

    return report


def main():
    parser = argparse.ArgumentParser(description="扫描 Issue 查找相似问题")
    parser.add_argument("--issue", type=str, help="Issue 编号、#编号 或 URL")
    parser.add_argument("--title", type=str, help="Issue 标题（手动输入）")
    parser.add_argument("--body", type=str, default="", help="Issue 正文")
    parser.add_argument("--top-k", type=int, default=None, help="返回条数")
    parser.add_argument("--mode", type=str, choices=["report", "comment"], help="运行模式")
    args = parser.parse_args()

    issue_number = None
    if args.issue:
        issue_number = _parse_issue_ref(args.issue)
        if issue_number is None:
            logger.error(f"无法解析 Issue 引用: {args.issue}")
            return

    scan(
        issue_number=issue_number,
        title=args.title,
        body=args.body,
        top_k=args.top_k,
        mode=args.mode,
    )

if __name__ == "__main__":
    main()
