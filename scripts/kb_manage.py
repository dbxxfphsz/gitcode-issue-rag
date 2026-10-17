"""知识库管理 - 查看状态、删除 Issue、重建索引、归档。

用法：
    python -m scripts.kb_manage status      # 查看知识库状态
    python -m scripts.kb_manage delete 123  # 删除指定 Issue
    python -m scripts.kb_manage reindex     # 重建 embedding 索引
    python -m scripts.kb_manage rebuild     # 清空并重建（危险）
    python -m scripts.kb_manage archive     # 归档旧知识库到 archive/ 并重置为空
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from issue_kb.config import apply_repo_override
from issue_kb.knowledge import KnowledgeBase
from issue_kb.similarity import SimilarityEngine


def cmd_status():
    kb = KnowledgeBase()
    stats = kb.get_stats()
    engine = SimilarityEngine(kb.kb_dir)

    print("===== Issue 知识库状态 =====")
    print(f"  知识库目录: {kb.kb_dir}")
    print(f"  Issue 总数: {stats['total']}")
    print(f"  Embedding 索引: {engine.index_size()} 条")
    print(f"  状态分布: {stats['states']}")
    print(f"  已处理 Issue: {stats['processed_count']} 条")
    print(f"  扫描游标: {stats['scan_cursor'] or '无'}")
    print(f"  上次扫描: {stats['last_scan_at'] or '从未'}")
    print(f"  上次构建: {stats['last_kb_build_at'] or '从未'}")
    print(f"  标签: {', '.join(stats['labels'][:30])}")


def cmd_delete(number: int):
    kb = KnowledgeBase()
    if kb.delete_issue(number):
        logger.info(f"已删除 #{number}")
    else:
        logger.warning(f"#{number} 不存在")


def cmd_reindex():
    kb = KnowledgeBase()
    engine = SimilarityEngine(kb.kb_dir)
    issues = kb.list_issues()
    if not issues:
        logger.warning("知识库为空")
        return
    engine.rebuild_index(issues)
    logger.info(f"索引重建完成: {engine.index_size()} 条")


def cmd_rebuild():
    kb = KnowledgeBase()
    kb.rebuild()
    logger.info("知识库已清空，请重新运行 build_kb")


def cmd_archive():
    """把当前知识库整体移到 archive/kb-legacy-<时间戳>/，再重置为空目录。

    归档保留旧 issues/、embeddings.json、metadata.json、reports/ 等全部扫描计算结果，
    供追溯/回滚；归档后知识库清空，需重新运行 build_kb --fresh 从零重建。
    """
    kb = KnowledgeBase()
    src = kb.kb_dir.resolve()
    if not src.exists() or not any(src.iterdir()):
        logger.warning(f"知识库目录为空，无需归档: {src}")
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = src.parent / "archive" / f"kb-legacy-{ts}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    kb._ensure_dirs()  # 重建空的知识库目录结构
    logger.info(f"已归档旧知识库到: {dst}")
    logger.info("知识库已重置为空，接下来运行 python -m scripts.build_kb --fresh 从 GitCode 全量重建")


def main():
    parser = argparse.ArgumentParser(description="知识库管理")
    parser.add_argument(
        "command",
        choices=["status", "delete", "reindex", "rebuild", "archive"],
        help="操作命令",
    )
    parser.add_argument("number", type=int, nargs="?", help="Issue 编号（delete 时使用）")
    parser.add_argument("--repo", type=str, default=None, help="GitCode 仓库地址（owner/repo），默认使用 .env 配置")
    args = parser.parse_args()
    apply_repo_override(args.repo)

    if args.command == "status":
        cmd_status()
    elif args.command == "delete":
        if not args.number:
            logger.error("delete 需要指定 Issue 编号")
            return
        cmd_delete(args.number)
    elif args.command == "reindex":
        cmd_reindex()
    elif args.command == "rebuild":
        cmd_rebuild()
    elif args.command == "archive":
        cmd_archive()


if __name__ == "__main__":
    main()
