"""添加 Issue 到知识库 - 提取知识并存入向量库。

用法：
    cd gitcode-issue-rag
    python -m scripts.add_issue \\
        --issue-id "#123" \\
        --title "xxx报错" \\
        --body "详细描述" \\
        --url "https://gitcode.com/xxx/issues/123" \\
        --labels "bug,usage"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document
from loguru import logger

from app.knowledge.knowledge import extract_knowledge
from app.shared.models import get_vectorstore
from app.shared.schemas import Issue


def add_issue_to_kb(
    issue_id: str,
    title: str,
    body: str = "",
    url: str = "",
    labels: list[str] | None = None,
) -> bool:
    """将一条 Issue 提取为知识并加入知识库。

    Args:
        issue_id: issue 编号，如 "#123"
        title: issue 标题
        body: issue 正文
        url: issue URL
        labels: 标签列表

    Returns:
        是否成功添加
    """
    issue = Issue(
        issue_id=issue_id,
        title=title,
        body=body,
        url=url,
        labels=labels or [],
    )

    logger.info(f"正在提取知识: {issue_id} - {title}")
    entry = extract_knowledge(issue)
    if entry is None:
        logger.warning(f"无法从 {issue_id} 提取知识")
        return False

    vectorstore = get_vectorstore()
    doc = Document(
        page_content=entry.to_document_text(),
        metadata={
            "title": entry.title,
            "category": entry.category,
            "problem": entry.problem,
            "solution": entry.solution,
            "related_issue_ids": ",".join(entry.related_issue_ids),
            "tags": ",".join(entry.tags),
            "type": "knowledge_entry",
            "url": url,
        },
    )
    vectorstore.add_documents([doc])

    total = vectorstore._collection.count()
    logger.info(f"已添加到知识库: {entry.title}（知识库总计 {total} 条）")
    return True


def main():
    parser = argparse.ArgumentParser(description="添加 Issue 到知识库")
    parser.add_argument("--issue-id", type=str, required=True, help="Issue ID，如 #123")
    parser.add_argument("--title", type=str, required=True, help="Issue 标题")
    parser.add_argument("--body", type=str, default="", help="Issue 正文")
    parser.add_argument("--url", type=str, default="", help="Issue URL")
    parser.add_argument("--labels", type=str, default="", help="标签，逗号分隔")

    args = parser.parse_args()
    labels = [label.strip() for label in args.labels.split(",") if label.strip()] if args.labels else []

    success = add_issue_to_kb(
        issue_id=args.issue_id,
        title=args.title,
        body=args.body,
        url=args.url,
        labels=labels,
    )
    if success:
        print(f"✓ 已添加到知识库: {args.title}")
    else:
        print(f"✗ 添加失败: {args.title}")


if __name__ == "__main__":
    main()
