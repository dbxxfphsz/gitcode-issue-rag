"""生成 FAQ 文档 - 从知识库中筛选已解决 Issue，聚类合并后生成 FAQ。

用法：
    python -m scripts.generate_faq                    # 全量生成
    python -m scripts.generate_faq --category 安装     # 按分类生成
    python -m scripts.generate_faq --issue 123        # 为指定 Issue 生成单条 FAQ
    python -m scripts.generate_faq --incremental      # 增量更新
    python -m scripts.generate_faq --no-draft         # 生成正式版（非草稿）
    python -m scripts.generate_faq --limit 2          # 调试：仅处理前 2 条（降低 LLM 开销）
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from issue_kb.config import apply_repo_override
from issue_kb.knowledge import KnowledgeBase
from issue_kb.faq import FAQGenerator


def main():
    parser = argparse.ArgumentParser(description="生成 FAQ 文档")
    parser.add_argument("--category", type=str, default=None, help="按分类生成")
    parser.add_argument("--issue", type=int, default=None, help="为指定 Issue 生成单条 FAQ")
    parser.add_argument("--incremental", action="store_true", help="增量更新")
    parser.add_argument("--no-draft", action="store_true", help="生成正式版（非草稿）")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="仅处理前 N 条已解决 Issue（调试用，降低 LLM 调用开销）",
    )
    parser.add_argument("--repo", type=str, default=None, help="GitCode 仓库地址（owner/repo），默认使用 .env 配置")
    args = parser.parse_args()
    apply_repo_override(args.repo)

    kb = KnowledgeBase()
    gen = FAQGenerator(kb.kb_dir)

    if args.issue:
        # 单条 FAQ（--limit 仅用于批量模式，此处不适用）
        if args.limit is not None:
            logger.warning("--limit 仅在批量生成时生效，--issue 单条模式已忽略该参数")
        issue = kb.get_issue(args.issue)
        if not issue:
            logger.error(f"#{args.issue} 不在知识库中")
            return
        gen.generate_single(issue, draft=not args.no_draft)
    else:
        # 批量 FAQ
        issues = kb.list_issues()
        files = gen.generate(
            issues,
            category=args.category,
            incremental=args.incremental,
            draft=not args.no_draft,
            limit=args.limit,
        )
        logger.info(f"已生成 {len(files)} 个 FAQ 文件到 {gen.faq_dir}")


if __name__ == "__main__":
    main()
