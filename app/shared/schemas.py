"""Issue 数据模型 - 定义从 GitCode 爬取到的 issue 结构。"""

import json
from pathlib import Path

from pydantic import BaseModel

# 爬取数据的本地缓存路径
CACHE_DIR = Path("data")
CACHE_FILE = CACHE_DIR / "issues_cache.json"


class Issue(BaseModel):
    """一条 GitCode Issue 的结构化数据。"""

    issue_id: str  # issue 编号，如 "#123"
    title: str  # issue 标题
    body: str  # issue 正文内容
    url: str  # issue 详情页 URL
    state: str = "closed"  # open / closed
    author: str = ""  # 提交者
    created_at: str = ""  # 创建时间
    labels: list[str] = []  # 标签列表

    def to_document_text(self) -> str:
        """将 issue 拼成一段文本，用于 embedding。

        标题权重最高（重复出现），类似 SEO 的做法。
        """
        parts = [
            f"标题: {self.title}",
            f"问题描述: {self.body}",
        ]
        if self.labels:
            parts.append(f"标签: {', '.join(self.labels)}")
        return "\n".join(parts)


def save_issues_json(issues: list[Issue]) -> Path:
    """将爬取的 issue 列表保存到本地 JSON 文件。

    爬取后立即保存，后续 embedding 失败时可以跳过爬取直接读文件重试。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = [issue.model_dump() for issue in issues]
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return CACHE_FILE


def load_issues_json() -> list[Issue]:
    """从本地 JSON 缓存加载 issue 列表。

    如果缓存文件不存在，返回空列表。
    """
    if not CACHE_FILE.exists():
        return []
    data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return [Issue(**item) for item in data]


def clear_issues_cache() -> bool:
    """删除本地缓存文件（用于 --fresh 从头开始）。"""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
        return True
    return False
