"""构建知识库 - 从缓存的 Issue 中提取知识条目到向量库。

用法：
    cd gitcode-issue-rag
    python -m scripts.build_kb

    # 指定最大处理数量
    python -m scripts.build_kb --max-issues 50

前置条件：
    先运行 python -m scripts.init_ingest 爬取 issue 到本地缓存
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document
from loguru import logger

from app.knowledge.knowledge import extract_knowledge
from app.shared.models import get_vectorstore
from app.shared.schemas import Issue, load_issues_json

# 用于筛选知识提取的 issue 标签（不区分大小写）
KB_LABELS = {"bug", "usage", "缺陷", "使用", "问题", "question", "error", "故障"}


def _is_kb_relevant(issue: Issue) -> bool:
    """判断 issue 是否适合提取为知识条目。

    筛选策略：标签包含 bug/usage 类关键词，或标题包含相关关键词。
    """
    label_lower = {label.lower() for label in issue.labels}
    if label_lower & KB_LABELS:
        return True

    # 标题关键词兜底
    title_lower = issue.title.lower()
    title_keywords = ["报错", "错误", "失败", "无法", "怎么", "如何", "问题", "异常", "crash", "error", "fail"]
    return any(kw in title_lower for kw in title_keywords)


def build_knowledge_base(max_issues: int | None = None) -> int:
    """从缓存 issue 构建知识库。

    流程：加载缓存 → 筛选 Bug/Usage → LLM 提取知识 → 写入向量库

    Args:
        max_issues: 最多处理多少条 issue（None 表示全部）

    Returns:
        成功写入的知识条目数量
    """
    issues = load_issues_json()
    if not issues:
        logger.error("缓存为空，请先运行 python -m scripts.init_ingest 爬取数据")
        return 0

    logger.info(f"加载了 {len(issues)} 条 issue，开始筛选...")

    # 筛选 Bug/Usage 类 issue
    relevant = [i for i in issues if _is_kb_relevant(i)]
    logger.info(f"筛选出 {len(relevant)} 条 Bug/Usage 类 issue")

    if max_issues:
        relevant = relevant[:max_issues]
        logger.info(f"限制处理前 {max_issues} 条")

    # 逐条提取知识
    vectorstore = get_vectorstore()
    added = 0

    for i, issue in enumerate(relevant):
        logger.info(f"[{i + 1}/{len(relevant)}] 提取: {issue.issue_id} - {issue.title[:50]}...")
        entry = extract_knowledge(issue)
        if entry is None:
            logger.warning(f"  跳过 {issue.issue_id}：无法提取知识")
            continue

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
            },
        )
        vectorstore.add_documents([doc])
        added += 1
        logger.info(f"  已写入: {entry.title}")

    logger.info(
        f"========== 知识库构建完成 ==========\n"
        f"  处理 issue 数: {len(relevant)}\n"
        f"  成功提取知识: {added} 条\n"
        f"  知识库总计: {vectorstore._collection.count()} 条"
    )
    return added


def main():
    parser = argparse.ArgumentParser(description="从 Issue 缓存构建知识库")
    parser.add_argument(
        "--max-issues",
        type=int,
        default=None,
        help="最多处理多少条 issue（默认全部）",
    )
    args = parser.parse_args()
    build_knowledge_base(max_issues=args.max_issues)


if __name__ == "__main__":
    main()
