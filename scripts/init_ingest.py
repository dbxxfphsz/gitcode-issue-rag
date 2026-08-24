"""全量入库脚本 - 爬取与向量化分离，支持断点重试。

用法：
    # 默认：有缓存就读缓存向量化，没缓存就先爬再存再向量化
    python -m scripts.init_ingest

    # 从头开始：删除缓存，重新爬取所有数据
    python -m scripts.init_ingest --fresh

    # 只爬不向量化：爬取数据存到 JSON，不跑 embedding
    python -m scripts.init_ingest --crawl-only

    # 只向量化：读已有 JSON 缓存，只跑 embedding（爬取失败后重试用）
    python -m scripts.init_ingest --embed-only
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 让 import 能找到项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from app.crawler.gitcode import GitCodeCrawler
from app.ingestion import ingest_issues
from app.shared.schemas import (
    save_issues_json,
    load_issues_json,
    clear_issues_cache,
    CACHE_FILE,
)


async def crawl_all() -> list:
    """爬取所有 issue（closed + open）并保存到本地 JSON。"""
    crawler = GitCodeCrawler()

    logger.info("拉取所有已关闭的 issue...")
    closed_issues = await crawler.fetch_all_issues(state="closed")
    logger.info(f"获取到 {len(closed_issues)} 条已关闭 issue")

    logger.info("拉取所有开放的 issue...")
    open_issues = await crawler.fetch_all_issues(state="open")
    logger.info(f"获取到 {len(open_issues)} 条开放 issue")

    all_issues = closed_issues + open_issues

    # 保存到本地 JSON
    saved_path = save_issues_json(all_issues)
    logger.info(f"爬取完成：共 {len(all_issues)} 条 issue，已保存到 {saved_path}")

    return all_issues


def embed_from_cache():
    """从本地 JSON 缓存读取 issue 并做向量化入库。"""
    issues = load_issues_json()
    if not issues:
        logger.error(f"缓存文件不存在或为空: {CACHE_FILE}")
        logger.error("请先运行不带 --embed-only 的命令爬取数据")
        return 0

    logger.info(f"从缓存加载了 {len(issues)} 条 issue，开始向量化入库...")
    chunk_count = ingest_issues(issues)
    logger.info(
        f"========== 向量化入库完成 ==========\n"
        f"  issue 总数: {len(issues)}\n"
        f"  文档块总数: {chunk_count}\n"
        f"  接下来可以启动服务: python -m main"
    )
    return chunk_count


async def main():
    parser = argparse.ArgumentParser(description="GitCode Issue 全量入库脚本")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--fresh",
        action="store_true",
        help="删除缓存，重新爬取所有数据",
    )
    group.add_argument(
        "--crawl-only",
        action="store_true",
        help="只爬取数据存到 JSON，不做向量化",
    )
    group.add_argument(
        "--embed-only",
        action="store_true",
        help="只从已有 JSON 缓存做向量化（爬取失败后重试用）",
    )
    args = parser.parse_args()

    # --fresh：删除缓存后重新爬
    if args.fresh:
        if clear_issues_cache():
            logger.info("已删除旧的缓存文件")
        logger.info("========== 从头开始全量入库 ==========")
        issues = await crawl_all()
        embed_from_cache()
        return

    # --crawl-only：只爬不向量化
    if args.crawl_only:
        logger.info("========== 仅爬取模式 ==========")
        await crawl_all()
        return

    # --embed-only：只向量化，不爬取
    if args.embed_only:
        logger.info("========== 仅向量化模式 ==========")
        embed_from_cache()
        return

    # 默认模式：有缓存就用缓存，没缓存就爬
    logger.info("========== 全量入库 ==========")
    cached = load_issues_json()
    if cached:
        logger.info(f"发现本地缓存 ({CACHE_FILE})，共 {len(cached)} 条 issue，跳过爬取")
        logger.info("如需重新爬取，请使用 --fresh 参数")
        embed_from_cache()
    else:
        logger.info("未发现本地缓存，开始爬取...")
        await crawl_all()
        embed_from_cache()


if __name__ == "__main__":
    asyncio.run(main())
