"""将源仓库的 Issue 批量迁移到目标仓库（用于测评环境搭建）。

用法：
    # 从 Ascend/msinsight 迁移到你的私库 zhumingzhu/msinsight-test
    python -m scripts.migrate_issues \
        --source Ascend/msinsight \
        --target zhumingzhu/msinsight-test \
        --limit 50

    # 迁移已关闭的 Issue（用于构建测评知识库）
    python -m scripts.migrate_issues \
        --source Ascend/msinsight \
        --target zhumingzhu/msinsight-test \
        --state closed

    # 迁移评论（默认不迁移，加 --with-comments）
    python -m scripts.migrate_issues \
        --source Ascend/msinsight \
        --target zhumingzhu/msinsight-test \
        --with-comments

    # 查看迁移状态
    python -m scripts.migrate_issues --status
"""

from issue_kb.config import settings
import json
import sys
import time
from pathlib import Path

import httpx
from loguru import logger

# 确保从项目根目录可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


MIGRATE_LOG_FILE = Path(__file__).resolve().parent.parent / "migrate_log.json"


def _load_log() -> dict:
    if MIGRATE_LOG_FILE.exists():
        return json.loads(MIGRATE_LOG_FILE.read_text(encoding="utf-8"))
    return {"migrated": {}, "failed": [], "last_run": None}


def _save_log(log_data: dict):
    MIGRATE_LOG_FILE.write_text(
        json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def migrate(
    source_repo: str,
    target_repo: str,
    state: str = "all",
    limit: int | None = None,
    with_comments: bool = False,
    resume: bool = True,
):
    """从源仓库拉取 Issue，逐条在目标仓库创建。

    Args:
        source_repo: 源仓库（owner/repo）
        target_repo: 目标仓库（owner/repo）
        state: 拉取的 Issue 状态（open/closed/all）
        limit: 最多迁移条数（None=全部）
        with_comments: 是否迁移评论
        resume: 断点续跑（跳过已迁移的 Issue）
    """
    from issue_kb.gitcode_client import GitCodeClient

    token = settings.gitcode_token
    if not token:
        logger.error("未配置 GITCODE_TOKEN，请在 .env 中设置")
        sys.exit(1)

    log = _load_log()
    migrated_map: dict[str, int] = log.get("migrated", {})
    # key: "{source_repo}:{source_number}" → value: target_number

    logger.info(f"源仓库: {source_repo}")
    logger.info(f"目标仓库: {target_repo}")
    logger.info(f"状态过滤: {state}")

    # 1. 从源仓库拉取 Issue
    logger.info("正在从源仓库拉取 Issue 列表...")
    settings.gitcode_repo = source_repo
    settings.kb_dir = "./issue-knowledge-base"  # 临时，不影响实际知识库
    source_client = GitCodeClient(token)

    with source_client:
        issues = source_client.fetch_all_issues(state=state)
    logger.info(f"源仓库共 {len(issues)} 条 Issue")

    if limit and len(issues) > limit:
        issues = issues[:limit]
        logger.info(f"限制迁移前 {limit} 条")

    # 2. 逐条在目标仓库创建
    settings.gitcode_repo = target_repo
    target_client = GitCodeClient(token)

    created = 0
    skipped = 0
    failed = 0
    comments_migrated = 0

    with target_client:
        for i, issue in enumerate(issues, 1):
            source_num = issue.get("number")
            log_key = f"{source_repo}:{source_num}"

            # 断点续跑：跳过已迁移的
            if resume and log_key in migrated_map:
                skipped += 1
                logger.info(f"[{i}/{len(issues)}] 跳过已迁移: #{source_num}")
                continue

            title = issue.get("title", "")
            body = issue.get("body", "") or ""
            labels = [lb.get("name", "") for lb in issue.get("labels", [])]
            issue_state = issue.get("state", "open")

            # 在正文头部注入来源信息
            source_url = f"https://gitcode.com/{source_repo}/issues/{source_num}"
            meta_block = (
                f"> **迁移自**: [{source_repo}#{source_num}]({source_url})  \n"
                f"> **原始状态**: {issue_state}  \n"
                f"> **原始作者**: {issue.get('user', {}).get('login', '未知')}  \n"
                f"> **创建时间**: {issue.get('created_at', '未知')}\n\n"
                f"---\n\n"
            )
            full_body = meta_block + body

            try:
                result = target_client.create_issue(
                    title=f"[#{source_num}] {title}",
                    body=full_body,
                    labels=labels,
                    state=issue_state,
                )
                target_num = result.get("number")
                migrated_map[log_key] = target_num
                created += 1
                logger.info(
                    f"[{i}/{len(issues)}] #{source_num} → #{target_num}: {title[:40]}"
                )

                # 迁移评论
                if with_comments and source_num:
                    try:
                        source_client_for_comments = GitCodeClient(token)
                        settings.gitcode_repo = source_repo
                        source_client_for_comments.repo = source_repo
                        comments = source_client_for_comments.fetch_comments(
                            source_num)
                        source_client_for_comments.close()
                        settings.gitcode_repo = target_repo

                        for c in comments:
                            cbody = c.get("body", "") or ""
                            if not cbody.strip():
                                continue
                            comment_meta = (
                                f"> *来自 @{c.get('user', {}).get('login', '?')} "
                                f"于 {c.get('created_at', '?')}*\n\n"
                            )
                            target_client.post_comment(
                                target_num, comment_meta + cbody
                            )
                            comments_migrated += 1
                            time.sleep(0.5)
                    except Exception as e:
                        logger.warning(f"  评论迁移失败 (#{source_num}): {e}")

                # 每条成功后即保存日志（支持中断续跑）
                log["migrated"] = migrated_map
                log["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _save_log(log)

                time.sleep(settings.crawl_delay)

            except httpx.HTTPStatusError as e:
                failed += 1
                logger.error(
                    f"[{i}/{len(issues)}] #{source_num} 创建失败: "
                    f"HTTP {e.response.status_code} - {e.response.text[:200]}"
                )
                log.setdefault("failed", []).append(
                    {"source_number": source_num, "error": str(e)[:200]}
                )
                _save_log(log)

            except Exception as e:
                failed += 1
                logger.error(f"[{i}/{len(issues)}] #{source_num} 异常: {e}")

    logger.info(
        f"\n迁移完成: 新建 {created} / 跳过 {skipped} / 失败 {failed}"
        f"{f' / 评论 {comments_migrated}' if with_comments else ''}"
    )
    logger.info(f"迁移日志: {MIGRATE_LOG_FILE}")


def show_status():
    """显示迁移状态。"""
    log = _load_log()
    migrated = log.get("migrated", {})
    failed = log.get("failed", [])
    print(f"已迁移: {len(migrated)} 条")
    print(f"失败: {len(failed)} 条")
    print(f"上次运行: {log.get('last_run', '从未')}")
    if failed:
        print("\n失败列表:")
        for f in failed[-10:]:
            print(f"  #{f['source_number']}: {f['error'][:80]}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Issue 迁移工具（源仓库 → 目标仓库）")
    parser.add_argument(
        "--source", default="Ascend/msinsight", help="源仓库 owner/repo")
    parser.add_argument("--target", required=True, help="目标仓库 owner/repo")
    parser.add_argument("--state", default="all",
                        help="Issue 状态: open/closed/all")
    parser.add_argument("--limit", type=int, default=None, help="最多迁移条数")
    parser.add_argument("--with-comments", action="store_true", help="同时迁移评论")
    parser.add_argument("--no-resume", action="store_true", help="不复用已有迁移记录")
    parser.add_argument("--status", action="store_true", help="查看迁移状态")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    migrate(
        source_repo=args.source,
        target_repo=args.target,
        state=args.state,
        limit=args.limit,
        with_comments=args.with_comments,
        resume=not args.no_resume,
    )


if __name__ == "__main__":
    main()
