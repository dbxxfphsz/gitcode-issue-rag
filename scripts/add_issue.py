"""添加 Issue 到知识库 - 从 GitCode 拉取或手动输入，保存并更新索引。

用法：
    python -m scripts.add_issue --issue 123
    python -m scripts.add_issue --issue 123 --with-comments
    python -m scripts.add_issue --manual --title "xxx" --body "xxx" --labels "bug"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from issue_kb.config import settings
from issue_kb.gitcode_client import GitCodeClient
from issue_kb.knowledge import KnowledgeBase, IssueData
from issue_kb.similarity import SimilarityEngine, _build_issue_text


def add_from_gitcode(issue_number: int, with_comments: bool = True):
    """从 GitCode 拉取 Issue 并加入知识库。"""
    kb = KnowledgeBase()
    engine = SimilarityEngine(kb.kb_dir)

    existing = kb.get_issue(issue_number)
    if existing:
        logger.info(f"#{issue_number} 已存在于知识库中，将更新")

    with GitCodeClient() as client:
        raw = client.fetch_issue(issue_number)
        comments = client.fetch_comments(issue_number) if with_comments else []

    data = IssueData.from_gitcode(raw, comments)
    if not IssueData.validate(data):
        logger.error(f"#{issue_number} 数据无效")
        return

    kb.save_issue(data)
    logger.info(f"已保存 #{issue_number} 到知识库")

    # 更新 embedding
    text = _build_issue_text(data, settings.include_comments)
    engine.update_embedding(issue_number, text)
    logger.info(f"embedding 已更新")

    stats = kb.get_stats()
    logger.info(f"知识库总计: {stats['total']} 条 Issue")


def add_manual(title: str, body: str = "", labels: str = "", state: str = "open"):
    """手动添加 Issue 到知识库。"""
    kb = KnowledgeBase()
    engine = SimilarityEngine(kb.kb_dir)

    # 分配编号（取现有最大编号 + 1）
    all_issues = kb.list_issues()
    max_num = max((i["number"] for i in all_issues), default=0)
    number = max_num + 1

    label_list = [lb.strip() for lb in labels.split(",") if lb.strip()] if labels else []
    data = {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "url": "",
        "labels": label_list,
        "author": "",
        "created_at": "",
        "updated_at": "",
        "closed_at": "",
        "comments_data": [],
        "kb_added_at": None,
        "kb_updated_at": None,
        "solution": "",
    }

    kb.save_issue(data)
    text = _build_issue_text(data, settings.include_comments)
    engine.update_embedding(number, text)
    logger.info(f"已添加手动 Issue #{number}: {title}")


def main():
    parser = argparse.ArgumentParser(description="添加 Issue 到知识库")
    parser.add_argument("--issue", type=int, help="从 GitCode 拉取 Issue 编号")
    parser.add_argument("--with-comments", action="store_true", help="同时拉取评论")
    parser.add_argument("--manual", action="store_true", help="手动输入模式")
    parser.add_argument("--title", type=str, default="", help="标题（手动模式）")
    parser.add_argument("--body", type=str, default="", help="正文（手动模式）")
    parser.add_argument("--labels", type=str, default="", help="标签，逗号分隔")
    parser.add_argument("--state", type=str, default="open", help="状态")
    args = parser.parse_args()

    if args.manual:
        if not args.title:
            logger.error("手动模式需要 --title")
            return
        add_manual(args.title, args.body, args.labels, args.state)
    elif args.issue:
        add_from_gitcode(args.issue, args.with_comments)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
