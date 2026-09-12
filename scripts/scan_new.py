"""定时扫描新 Issue - 增量拉取新 Issue 并逐个执行相似性扫描。

支持断点续跑：通过游标记录上次扫描位置，已处理的 Issue 不会重复处理。

用法：
    python -m scripts.scan_new                  # 扫描上次游标后的新 Issue
    python -m scripts.scan_new --mode comment   # 扫描并评论
    python -m scripts.scan_new --mode report    # 仅生成报告
    python -m scripts.scan_new --status         # 查看运行状态
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone
from loguru import logger

from issue_kb.config import settings
from issue_kb.gitcode_client import GitCodeClient
from issue_kb.knowledge import KnowledgeBase, IssueData
from issue_kb.similarity import SimilarityEngine, _build_issue_text
from issue_kb.report import generate_scan_report
from issue_kb.commenter import IssueCommenter


def scan_new(mode: str = "report"):
    """扫描新增/更新的 Issue。"""
    kb = KnowledgeBase()
    engine = SimilarityEngine(kb.kb_dir)
    processed = kb.get_processed_ids()

    # 获取游标
    cursor = kb.get_cursor()
    since = cursor
    if not since:
        # 首次运行，使用 7 天前作为起点
        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        logger.info(f"无游标记录，使用 7 天前作为起点: {since}")

    logger.info(f"拉取 {since} 之后更新的 Issue...")

    with GitCodeClient() as client:
        raw_issues = client.fetch_all_issues(state="all", since=since)

    if not raw_issues:
        logger.info("没有新的 Issue")
        return

    # 过滤已处理的
    new_issues = [r for r in raw_issues if r.get("number") not in processed]
    logger.info(f"拉取到 {len(raw_issues)} 条，其中 {len(new_issues)} 条未处理")

    if not new_issues:
        logger.info("所有 Issue 均已处理")
        kb.set_cursor(datetime.now(timezone.utc).isoformat())
        return

    commenter = IssueCommenter() if mode == "comment" else None
    success_count = 0
    error_count = 0

    for raw in new_issues:
        number = raw.get("number")
        try:
            logger.info(f"处理 #{number}: {raw.get('title', '')[:50]}...")

            # 标准化数据
            comments = []
            if settings.include_comments:
                with GitCodeClient() as c:
                    comments = c.fetch_comments(number)

            data = IssueData.from_gitcode(raw, comments)

            # 保存到知识库
            kb.save_issue(data)

            # 更新 embedding
            text = _build_issue_text(data, settings.include_comments)
            engine.update_embedding(number, text)

            # 执行相似性搜索
            results = engine.search(text, exclude_number=number)
            kb_issues = {str(i["number"]): i for i in kb.list_issues()}
            for r in results:
                r["issue"] = kb_issues.get(str(r["number"]), {})

            # 生成报告
            report = generate_scan_report(data, results, kb_issues)

            # 保存报告
            report_dir = kb.kb_dir / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_file = report_dir / f"scan_{number}.md"
            report_file.write_text(report, encoding="utf-8")

            # 评论（如果需要）
            if commenter and mode == "comment":
                commenter.post_scan_report(number, report)

            # 标记为已处理
            kb.mark_processed(number)
            success_count += 1

        except Exception as e:
            logger.error(f"处理 #{number} 失败: {e}")
            error_count += 1
            # 单个失败不影响其他
            continue

    # 更新游标
    kb.set_cursor(datetime.now(timezone.utc).isoformat())

    logger.info(
        f"===== 扫描完成 =====\n"
        f"  成功: {success_count}\n"
        f"  失败: {error_count}\n"
        f"  游标已更新"
    )


def show_status():
    """显示扫描任务状态。"""
    kb = KnowledgeBase()
    stats = kb.get_stats()
    print("===== 定时扫描任务状态 =====")
    print(f"  知识库 Issue 总数: {stats['total']}")
    print(f"  已处理 Issue 数: {stats['processed_count']}")
    print(f"  上次扫描时间: {stats['last_scan_at'] or '从未'}")
    print(f"  扫描游标: {stats['scan_cursor'] or '无'}")
    print(f"  状态分布: {stats['states']}")
    print(f"  标签: {', '.join(stats['labels'][:20])}")


def main():
    parser = argparse.ArgumentParser(description="定时扫描新 Issue")
    parser.add_argument("--mode", type=str, choices=["report", "comment"], default=None)
    parser.add_argument("--status", action="store_true", help="查看运行状态")
    args = parser.parse_args()

    if args.status:
        show_status()
    else:
        scan_new(mode=args.mode or settings.scan_mode)


if __name__ == "__main__":
    main()
