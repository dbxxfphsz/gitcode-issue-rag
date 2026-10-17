"""评论 Issue - 将扫描报告发布为 GitCode Issue 评论。

用法：
    python -m scripts.comment_issue --issue 123
    python -m scripts.comment_issue --issue 123 --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from issue_kb.config import apply_repo_override
from scripts.scan_issue import scan, _parse_issue_ref


def main():
    parser = argparse.ArgumentParser(description="将扫描报告评论到 Issue")
    parser.add_argument("--issue", type=str, required=True, help="Issue 编号或链接")
    parser.add_argument("--top-k", type=int, default=None, help="返回条数")
    parser.add_argument("--force", action="store_true", help="强制发布（忽略已有评论）")
    parser.add_argument("--repo", type=str, default=None, help="GitCode 仓库地址（owner/repo），默认使用 .env 配置")
    args = parser.parse_args()
    apply_repo_override(args.repo)

    issue_number = _parse_issue_ref(args.issue)
    if issue_number is None:
        logger.error(f"无法解析 Issue 引用: {args.issue}")
        return

    # 以 comment 模式执行扫描
    scan(issue_number=issue_number, top_k=args.top_k, mode="comment")


if __name__ == "__main__":
    main()
