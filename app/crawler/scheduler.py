"""定时任务调度器 - 每日增量爬取 + 每月知识库整合。

使用 APScheduler，跟着 FastAPI 一起启动，不需要额外的进程。
类比前端：类似 setInterval，但支持 cron 表达式，更精确也更可靠。

定时任务：
  - 每日凌晨: 增量爬取 GitCode issue 并入库
  - 每月 1 号: 整合知识库，合并相似知识条目
"""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.config import settings
from app.crawler.gitcode import GitCodeCrawler
from app.ingestion import ingest_issues, get_existing_issue_ids
from app.knowledge.consolidation import consolidate_knowledge_base


async def daily_crawl_job():
    """每日定时任务：爬取当天更新的 issue 并增量入库。"""
    logger.info("===== 定时任务开始：每日增量爬取 =====")

    crawler = GitCodeCrawler()
    try:
        # 1. 爬取今天的 issue
        issues = await crawler.fetch_today_issues()
        logger.info(f"爬取到 {len(issues)} 条 issue")

        # 2. 去重过滤
        existing_ids = get_existing_issue_ids()
        new_issues = [i for i in issues if i.issue_id not in existing_ids]
        logger.info(f"其中新增 {len(new_issues)} 条（已有 {len(issues) - len(new_issues)} 条）")

        # 3. 入库
        if new_issues:
            chunk_count = ingest_issues(new_issues)
            logger.info(f"入库完成：{len(new_issues)} 条 issue → {chunk_count} 个文档块")
        else:
            logger.info("没有新内容需要入库")

    except Exception:
        logger.exception("定时任务执行失败")

    logger.info("===== 定时任务结束 =====")


async def monthly_consolidation_job():
    """月度整合任务：合并知识库中的相似条目。"""
    logger.info("===== 定时任务开始：每月知识库整合 =====")
    try:
        report = consolidate_knowledge_base()
        logger.info(f"整合报告: {report}")
    except Exception:
        logger.exception("月度整合任务执行失败")
    logger.info("===== 定时任务结束 =====")


def create_scheduler() -> AsyncIOScheduler:
    """创建并配置定时任务调度器。

    调度策略：每天凌晨 {CRON_HOUR}:{CRON_MINUTE} 执行爬取。
    时间可在 .env 中配置，默认凌晨 2:00。
    """
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        daily_crawl_job,
        trigger="cron",
        hour=settings.cron_hour,
        minute=settings.cron_minute,
        id="daily_gitcode_crawl",
        name="每日 GitCode Issue 增量爬取",
        replace_existing=True,
    )

    scheduler.add_job(
        monthly_consolidation_job,
        trigger="cron",
        day=1,
        hour=3,
        minute=0,
        id="monthly_knowledge_consolidation",
        name="每月知识库整合（合并相似知识条目）",
        replace_existing=True,
    )

    logger.info(
        f"定时任务已注册:\n"
        f"  每日 {settings.cron_hour:02d}:{settings.cron_minute:02d} 增量爬取\n"
        f"  每月 1 号 03:00 知识库整合"
    )
    return scheduler
