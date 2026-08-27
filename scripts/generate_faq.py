"""生成 FAQ 文档 - 从知识库中筛选已解决 Issue，聚类合并后生成 FAQ。

用法：
    python -m scripts.generate_faq                    # 全量生成
    python -m scripts.generate_faq --category 安装     # 按分类生成
    python -m scripts.generate_faq --issue 123        # 为指定 Issue 生成单条 FAQ
    python -m scripts.generate_faq --incremental      # 增量更新
    python -m scripts.generate_faq --no-draft         # 生成正式版（非草稿）
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from issue_kb.knowledge import KnowledgeBase
from issue_kb.faq import FAQGenerator


def main():
    parser = argparse.ArgumentParser(description="生成 FAQ 文档")
    parser.add_argument("--category", type=str, default=None, help="按分类生成")
    parser.add_argument("--issue", type=int, default=None, help="为指定 Issue 生成单条 FAQ")
    parser.add_argument("--incremental", action="store_true", help="增量更新")
    parser.add_argument("--no-draft", action="store_true", help="生成正式版（非草稿）")
    args = parser.parse_args()

    kb = KnowledgeBase()
    gen = FAQGenerator(kb.kb_dir)

    if args.issue:
        # 单条 FAQ
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
        )
        logger.info(f"已生成 {len(files)} 个 FAQ 文件到 {gen.faq_dir}")


if __name__ == "__main__":
    main()
