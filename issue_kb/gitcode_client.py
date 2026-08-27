"""GitCode REST API 客户端 - 支持 Issue 读取与评论发布。

API 文档: https://gitcode.com/api/v5/ (Swagger)
所有方法均为同步 httpx 调用，方便脚本直接使用。
"""

import time

import httpx
from loguru import logger

from issue_kb.config import settings


class GitCodeClient:
    """GitCode v5 API 客户端。"""

    def __init__(self, token: str | None = None):
        self.token = token or settings.gitcode_token
        self.base = settings.api_prefix
        self.repo = settings.gitcode_repo
        self._client = httpx.Client(
            timeout=30,
            params={"access_token": self.token} if self.token else {},
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ---- Issue 读取 ----

    def fetch_all_issues(
        self,
        state: str = "all",
        since: str | None = None,
    ) -> list[dict]:
        """分页拉取所有 issue。

        Args:
            state: open / closed / all
            since: ISO 时间戳，只返回此时间后更新的 issue
        """
        issues: list[dict] = []
        page = 1
        while True:
            params: dict = {
                "state": state,
                "page": page,
                "per_page": settings.crawl_page_size,
                "sort": "updated",
                "direction": "desc",
            }
            if since:
                params["since"] = since

            data = self._get(f"/repos/{self.repo}/issues", params)
            if not data:
                break
            issues.extend(data)
            logger.info(f"  第 {page} 页: {len(data)} 条，累计 {len(issues)} 条")
            if len(data) < settings.crawl_page_size:
                break
            page += 1
            time.sleep(settings.crawl_delay)
        return issues

    def fetch_issue(self, issue_number: int) -> dict:
        """获取单条 issue 详情。"""
        return self._get(f"/repos/{self.repo}/issues/{issue_number}")

    def fetch_comments(self, issue_number: int) -> list[dict]:
        """获取 issue 下的所有评论。"""
        comments: list[dict] = []
        page = 1
        while True:
            params = {"page": page, "per_page": settings.crawl_page_size}
            data = self._get(
                f"/repos/{self.repo}/issues/{issue_number}/comments", params
            )
            if not data:
                break
            comments.extend(data)
            if len(data) < settings.crawl_page_size:
                break
            page += 1
            time.sleep(settings.crawl_delay)
        return comments

    # ---- 评论发布 ----

    def post_comment(self, issue_number: int, body: str) -> dict:
        """在 issue 下发布评论。"""
        resp = self._client.post(
            f"{self.base}/repos/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
        logger.info(f"已评论到 #{issue_number}")
        return resp.json()

    def fetch_issue_comments(self, issue_number: int) -> list[dict]:
        """获取 issue 评论（别名，与 fetch_comments 相同）。"""
        return self.fetch_comments(issue_number)

    # ---- 内部方法 ----

    def _get(self, path: str, params: dict | None = None) -> list | dict:
        """发起 GET 请求，处理错误。"""
        url = f"{self.base}{path}"
        try:
            resp = self._client.get(url, params=params or {})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP {e.response.status_code}: {url}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"请求失败: {e}")
            raise
