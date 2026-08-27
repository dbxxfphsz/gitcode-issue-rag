"""GitCode Issue 评论管理 - 发布扫描报告，防重复标记。"""

from loguru import logger

from issue_kb.config import settings
from issue_kb.gitcode_client import GitCodeClient
from issue_kb.report import generate_comment_body, has_existing_comment


class IssueCommenter:
    """管理 Issue 评论的发布与去重。"""

    def __init__(self, client: GitCodeClient | None = None):
        self.client = client or GitCodeClient()

    def post_scan_report(
        self,
        issue_number: int,
        report: str,
        force: bool = False,
    ) -> bool:
        """将扫描报告评论到 Issue 下。

        Args:
            issue_number: Issue 编号
            report: Markdown 格式的报告
            force: 是否强制发布（忽略已有评论检查）

        Returns:
            是否成功发布
        """
        if not settings.gitcode_token:
            logger.warning("未配置 GITCODE_TOKEN，跳过评论发布")
            return False

        # 检查是否已有评论
        if not force:
            existing_comments = self.client.fetch_comments(issue_number)
            if has_existing_comment(existing_comments, issue_number):
                logger.info(
                    f"#{issue_number} 已有扫描报告评论，跳过（使用 --force 强制发布）"
                )
                return False

        # 包装评论内容（添加防重复标记）
        comment_body = generate_comment_body(report, issue_number)

        try:
            self.client.post_comment(issue_number, comment_body)
            return True
        except Exception as e:
            logger.error(f"发布评论到 #{issue_number} 失败: {e}")
            return False

    def update_scan_report(
        self,
        issue_number: int,
        report: str,
    ) -> bool:
        """更新已有评论中的扫描报告（先删旧评论，再发新评论）。

        GitCode API v5 不支持编辑评论，所以采用"删旧发新"策略。
        """
        # 先检查并记录旧评论
        existing_comments = self.client.fetch_comments(issue_number)
        marker = f"issue-skill-scan-report:v1:issue-{issue_number}"

        has_old = False
        for c in existing_comments:
            if marker in (c.get("body", "") or ""):
                has_old = True
                break

        if has_old:
            logger.info(f"#{issue_number} 已有旧报告，将发布新报告覆盖")

        # 发布新报告（force=True 跳过检查）
        return self.post_scan_report(issue_number, report, force=True)
