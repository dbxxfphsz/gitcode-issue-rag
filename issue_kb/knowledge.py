"""文件型知识库管理 - Issue 数据的 CRUD、游标追踪、增量更新。

目录结构:
    issue-knowledge-base/
    ├── issues/              # 每条 issue 一个 JSON 文件
    │   ├── 123.json
    │   └── 456.json
    ├── embeddings.json      # embedding 索引 (由 similarity.py 管理)
    └── metadata.json        # 游标、统计、更新时间
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from issue_kb.config import settings


def _to_int(value):
    """将 Issue 编号统一为 int，兼容历史数据中以字符串存储的编号。

    相似性搜索引擎返回的编号为 int，而部分历史 JSON 文件将 number 存为
    字符串，若不归一化会导致按编号查字典时匹配失败（报告详情显示为"未知"）。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


class IssueData:
    """标准化 Issue 数据结构。"""

    @staticmethod
    def from_gitcode(raw: dict, comments: list[dict] | None = None) -> dict:
        """从 GitCode API 原始响应提取标准化字段。"""
        labels = [lb.get("name", "") for lb in raw.get("labels", [])]
        return {
            "number": _to_int(raw.get("number")),
            "title": raw.get("title", ""),
            "body": raw.get("body", "") or "",
            "state": raw.get("state", "open"),
            "url": raw.get("html_url", ""),
            "labels": labels,
            "author": raw.get("user", {}).get("login", ""),
            "created_at": raw.get("created_at", ""),
            "updated_at": raw.get("updated_at", ""),
            "closed_at": raw.get("closed_at", ""),
            "comments_data": comments or [],
            "kb_added_at": None,
            "kb_updated_at": None,
            "solution": _extract_solution(raw, comments),
        }

    @staticmethod
    def validate(data: dict) -> bool:
        return bool(data.get("number") and data.get("title"))


def _extract_solution(raw: dict, comments: list[dict] | None) -> str:
    """尝试从 issue 或评论中提取解决方案。"""
    body = raw.get("body", "") or ""
    # 简单启发式：如果 body 中有"解决"、"fix"等关键词，取相关段落
    for keyword in ["解决方案", "解决方法", "solution", "workaround", "已修复"]:
        if keyword in body.lower():
            idx = body.lower().index(keyword)
            return body[idx : idx + 500].strip()
    # 从评论中找（取最后一条含解决关键词的评论）
    if comments:
        for c in reversed(comments):
            cbody = c.get("body", "") or ""
            for kw in ["解决", "fix", "solution", "已修复", "close"]:
                if kw in cbody.lower():
                    return cbody[:500].strip()
    return ""


class KnowledgeBase:
    """文件型知识库管理器。"""

    def __init__(self, kb_dir: str | Path | None = None):
        self.kb_dir = Path(kb_dir or settings.kb_dir)
        self.issues_dir = self.kb_dir / "issues"
        self.meta_file = self.kb_dir / "metadata.json"
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.issues_dir.mkdir(parents=True, exist_ok=True)

    # ---- 元数据 ----

    def _load_meta(self) -> dict:
        if self.meta_file.exists():
            return json.loads(self.meta_file.read_text(encoding="utf-8"))
        return {
            "scan_cursor": None,
            "last_scan_at": None,
            "last_kb_build_at": None,
            "processed_issues": [],
            "total_issues": 0,
        }

    def _save_meta(self, meta: dict):
        self.meta_file.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_cursor(self) -> str | None:
        return self._load_meta().get("scan_cursor")

    def set_cursor(self, cursor: str):
        meta = self._load_meta()
        meta["scan_cursor"] = cursor
        meta["last_scan_at"] = datetime.now(timezone.utc).isoformat()
        self._save_meta(meta)

    def get_processed_ids(self) -> set[int]:
        meta = self._load_meta()
        return set(meta.get("processed_issues", []))

    def mark_processed(self, issue_number: int):
        meta = self._load_meta()
        processed = set(meta.get("processed_issues", []))
        processed.add(issue_number)
        meta["processed_issues"] = sorted(processed)
        self._save_meta(meta)

    # ---- Issue CRUD ----

    def _issue_file(self, number: int) -> Path:
        return self.issues_dir / f"{number}.json"

    def get_issue(self, number: int) -> dict | None:
        f = self._issue_file(number)
        if not f.exists():
            return None
        data = json.loads(f.read_text(encoding="utf-8"))
        data["number"] = _to_int(data.get("number"))
        return data

    def save_issue(self, data: dict):
        """保存或更新一条 issue。"""
        number = data["number"]
        existing = self.get_issue(number)
        if existing:
            data["kb_added_at"] = existing.get("kb_added_at")
            data["kb_updated_at"] = datetime.now(timezone.utc).isoformat()
        else:
            data["kb_added_at"] = datetime.now(timezone.utc).isoformat()
        f = self._issue_file(number)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._update_count()

    def delete_issue(self, number: int) -> bool:
        f = self._issue_file(number)
        if f.exists():
            f.unlink()
            self._update_count()
            return True
        return False

    def list_issues(self, state: str | None = None) -> list[dict]:
        """列出所有 issue。可按状态过滤。"""
        issues = []
        for f in sorted(self.issues_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            data["number"] = _to_int(data.get("number"))
            if state and data.get("state") != state:
                continue
            issues.append(data)
        return issues

    def issue_count(self) -> int:
        return len(list(self.issues_dir.glob("*.json")))

    def _update_count(self):
        meta = self._load_meta()
        meta["total_issues"] = self.issue_count()
        self._save_meta(meta)

    # ---- 批量操作 ----

    def save_issues_batch(self, issues: list[dict]) -> tuple[int, int]:
        """批量保存 issue。返回 (新增数, 更新数)。"""
        added = 0
        updated = 0
        for data in issues:
            number = data.get("number")
            if not number:
                continue
            if self._issue_file(number).exists():
                updated += 1
            else:
                added += 1
            self.save_issue(data)
        logger.info(f"批量保存: 新增 {added}, 更新 {updated}")
        return added, updated

    def get_stats(self) -> dict:
        """知识库统计信息。"""
        meta = self._load_meta()
        all_issues = self.list_issues()
        states = {}
        labels_set: set[str] = set()
        for issue in all_issues:
            s = issue.get("state", "unknown")
            states[s] = states.get(s, 0) + 1
            for lb in issue.get("labels", []):
                labels_set.add(lb)
        return {
            "total": len(all_issues),
            "states": states,
            "labels": sorted(labels_set),
            "scan_cursor": meta.get("scan_cursor"),
            "last_scan_at": meta.get("last_scan_at"),
            "last_kb_build_at": meta.get("last_kb_build_at"),
            "processed_count": len(meta.get("processed_issues", [])),
        }

    def rebuild(self):
        """清空知识库，重建目录结构。"""
        import shutil

        if self.issues_dir.exists():
            shutil.rmtree(self.issues_dir)
        self._ensure_dirs()
        self._save_meta({
            "scan_cursor": None,
            "last_scan_at": None,
            "last_kb_build_at": None,
            "processed_issues": [],
            "total_issues": 0,
        })
        # 清空 embedding 索引
        emb_file = self.kb_dir / "embeddings.json"
        if emb_file.exists():
            emb_file.unlink()
        logger.info("知识库已清空，可重新构建")
