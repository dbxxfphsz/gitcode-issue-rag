"""扫描 Issue - 在知识库中搜索相似问题并生成报告。

用法：
    cd gitcode-issue-rag
    python -m scripts.scan_issue --title "xxx报错" --body "详细描述"

    # 指定返回条数
    python -m scripts.scan_issue --title "xxx报错" --body "详细描述" --top-k 5
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from app.config import settings
from app.shared.models import get_vectorstore


def scan_issue(title: str, body: str = "", top_k: int | None = None) -> list[dict]:
    """在知识库中搜索相似问题，返回结构化结果。

    Args:
        title: issue 标题
        body: issue 正文（可选）
        top_k: 返回条数（默认用配置值）

    Returns:
        相似知识条目列表，每条包含 score/title/category/problem/solution/url/related_issues
    """
    k = top_k or settings.dedup_top_k
    query_text = f"标题: {title}\n问题描述: {body}" if body else f"标题: {title}"

    vectorstore = get_vectorstore()
    results = vectorstore.similarity_search_with_relevance_scores(query_text, k=k)

    if not results:
        logger.info("知识库为空或无匹配结果")
        return []

    report = []
    for doc, score in results:
        meta = doc.metadata
        entry = {
            "score": round(score, 4),
            "title": meta.get("title", "未知"),
            "category": meta.get("category", "other"),
            "problem": meta.get("problem", doc.page_content[:200]),
            "solution": meta.get("solution", ""),
            "url": meta.get("url", ""),
            "related_issues": meta.get("related_issue_ids", ""),
        }
        report.append(entry)

    return report


def format_report(title: str, results: list[dict]) -> str:
    """将搜索结果格式化为可读报告。"""
    lines = [
        f"# Issue 扫描报告",
        f"",
        f"**扫描标题**: {title}",
        f"**匹配结果数**: {len(results)}",
        f"",
    ]

    if not results:
        lines.append("未找到相似问题，这可能是一个新问题。")
        return "\n".join(lines)

    for i, r in enumerate(results, 1):
        lines += [
            f"---",
            f"",
            f"## {i}. {r['title']}",
            f"",
            f"- **相似度**: {r['score']}",
            f"- **分类**: {r['category']}",
            f"- **问题**: {r['problem']}",
        ]
        if r["solution"]:
            lines.append(f"- **解决方案**: {r['solution']}")
        if r["url"]:
            lines.append(f"- **参考 Issue**: {r['url']}")
        if r["related_issues"]:
            lines.append(f"- **关联 Issue**: {r['related_issues']}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="扫描 Issue 查找相似问题")
    parser.add_argument("--title", type=str, help="Issue 标题")
    parser.add_argument("--body", type=str, default="", help="Issue 正文")
    parser.add_argument("--top-k", type=int, default=None, help="返回条数")
    args = parser.parse_args()

    if not args.title:
        # 交互模式
        title = input("请输入 Issue 标题: ").strip()
        body = input("请输入 Issue 正文（可跳过）: ").strip()
    else:
        title = args.title
        body = args.body

    results = scan_issue(title, body, top_k=args.top_k)
    report = format_report(title, results)
    print(report)


if __name__ == "__main__":
    main()
