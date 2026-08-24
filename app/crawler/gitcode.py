"""GitCode Issue 爬虫 - 通过 GitCode REST API 获取 issue 数据。

GitCode 提供类 GitHub 的 v5 API，返回 JSON，无需解析 HTML。
API 文档参考：https://gitcode.com/api/v5/（Swagger）

关键发现：
  - GET /api/v5/repos/{owner}/{repo}/issues 返回分页 issue 列表
  - 支持 state 参数（open/closed/all）
  - 支持 page + per_page 分页
  - 每条 issue 包含 id, number, title, body, html_url, labels, user 等字段
"""

import asyncio
from datetime import datetime, timezone

import httpx
from loguru import logger

from app.config import settings
from app.shared.schemas import Issue


class GitCodeCrawler:
    """GitCode Issue 异步爬虫。

    设计思路（类比前端）：
    - 类似前端的分页请求，一页页拉数据，直到拉完或到达截止日期
    - 用 httpx.AsyncClient 做异步请求，类比 axios 但支持并发
    """

    API_BASE = "https://gitcode.com/api/v5"

    def __init__(self):
        self.repo_path = settings.gitcode_repo  # 如 "Ascend/msinsight"
        self.page_size = settings.crawl_page_size
        self.delay = settings.crawl_delay

    async def fetch_all_issues(
        self,
        state: str = "closed",
        since: str | None = None,
    ) -> list[Issue]:
        """全量/增量获取 issue 列表。

        Args:
            state: 筛选状态，"closed" / "open" / "all"
            since: 只获取此时间之后更新的 issue（ISO 格式，如 "2026-08-17T00:00:00+08:00"）
                   用于增量爬取，None 则拉全量

        Returns:
            Issue 列表，按创建时间降序
        """
        issues: list[Issue] = []
        page = 1

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                url = f"{self.API_BASE}/repos/{self.repo_path}/issues"
                params = {
                    "state": state,
                    "page": page,
                    "per_page": self.page_size,
                }
                if since:
                    params["since"] = since

                logger.info(f"爬取第 {page} 页: {url}, params={params}")

                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    logger.error(f"请求失败: {e}")
                    break

                data = resp.json()
                if not data:
                    logger.info(f"第 {page} 页无数据，爬取结束")
                    break

                for item in data:
                    issue = self._parse_issue(item)
                    if issue:
                        # 增量模式：如果 issue 创建时间早于 since，可以停止
                        if since and issue.created_at < since:
                            logger.info(f"到达截止日期 {since}，停止爬取")
                            return issues
                        issues.append(issue)

                logger.info(f"第 {page} 页获取 {len(data)} 条，累计 {len(issues)} 条")

                # 如果返回数量不足一页，说明已到底
                if len(data) < self.page_size:
                    break

                page += 1
                await asyncio.sleep(self.delay)

        logger.info(f"爬取完成，共 {len(issues)} 条 issue")
        return issues

    async def fetch_today_issues(self) -> list[Issue]:
        """获取今天更新过的 issue（增量爬取入口）。

        定时任务每天调用此方法，只拉当天有变化的 issue。
        """
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        since = today.isoformat()
        logger.info(f"增量爬取：获取 {since} 之后更新的 issue")
        return await self.fetch_all_issues(state="all", since=since)

    @staticmethod
    def _parse_issue(raw: dict) -> Issue | None:
        """将 API 返回的 JSON 对象解析为 Issue 模型。"""
        try:
            labels = [label["name"] for label in raw.get("labels", [])]
            return Issue(
                issue_id=f"#{raw['number']}",
                title=raw["title"],
                body=raw.get("body") or "",
                url=raw["html_url"],
                state=raw["state"],
                author=raw.get("user", {}).get("login", ""),
                created_at=raw.get("created_at", ""),
                labels=labels,
            )
        except (KeyError, TypeError) as e:
            logger.warning(f"解析 issue 失败: {e}, 原始数据: {raw.get('number')}")
            return None
