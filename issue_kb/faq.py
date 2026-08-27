"""FAQ 文档生成 - 从知识库中筛选已解决的 Issue，聚类合并后生成 FAQ。

支持：
  - 全量生成 / 增量更新 / 指定 Issue 生成
  - 按组件、标签或问题类型分类
  - 相似 Issue 聚类合并，避免重复
  - 草稿模式（默认生成待审核内容）
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from issue_kb.config import settings
from issue_kb.similarity import SimilarityEngine, _build_issue_text


class FAQGenerator:
    """FAQ 文档生成器。"""

    def __init__(self, kb_dir: str | Path | None = None, faq_dir: str | Path | None = None):
        self.kb_dir = Path(kb_dir or settings.kb_dir)
        self.faq_dir = Path(faq_dir or settings.faq_dir)
        self.faq_dir.mkdir(parents=True, exist_ok=True)
        self.engine = SimilarityEngine(self.kb_dir)

    def generate(
        self,
        issues: list[dict],
        category: str | None = None,
        incremental: bool = False,
        draft: bool = True,
    ) -> list[Path]:
        """从 issue 列表生成 FAQ 文档。

        Args:
            issues: issue 数据列表
            category: 按分类生成（如 "安装", "Timeline", "NUMA"），None 则全量
            incremental: 增量模式（只处理新增/更新的 issue）
            draft: 是否标记为草稿

        Returns:
            生成的文件路径列表
        """
        # 1. 筛选已解决的 issue
        resolved = [i for i in issues if i.get("state") == "closed" and i.get("solution")]
        if not resolved:
            logger.warning("没有已解决且有解决方案的 Issue")
            return []

        logger.info(f"筛选出 {len(resolved)} 条已解决 Issue")

        # 2. 按标签/分类分组
        groups = self._group_by_category(resolved, category)

        # 3. 对每组进行相似聚类
        generated_files = []
        for group_name, group_issues in groups.items():
            clusters = self._cluster_similar(group_issues)
            logger.info(
                f"分类 [{group_name}]: {len(group_issues)} 条 Issue → {len(clusters)} 个聚类"
            )

            # 4. 生成 FAQ Markdown
            faq_content = self._render_faq(group_name, clusters, draft)

            # 5. 写入文件
            safe_name = group_name.replace("/", "_").replace(" ", "_")
            suffix = "_draft" if draft else ""
            filename = f"{safe_name}{suffix}.md"
            filepath = self.faq_dir / filename
            filepath.write_text(faq_content, encoding="utf-8")
            generated_files.append(filepath)
            logger.info(f"  已生成: {filepath}")

        return generated_files

    def generate_single(self, issue: dict, draft: bool = True) -> Path | None:
        """为单条 Issue 生成 FAQ 条目。"""
        if not issue.get("solution"):
            logger.warning(f"#{issue.get('number')} 没有解决方案，跳过")
            return None

        category = self._infer_category(issue)
        faq_content = self._render_single_faq(issue, category, draft)

        safe_name = f"issue_{issue['number']}"
        suffix = "_draft" if draft else ""
        filename = f"{safe_name}{suffix}.md"
        filepath = self.faq_dir / filename
        filepath.write_text(faq_content, encoding="utf-8")
        logger.info(f"已生成: {filepath}")
        return filepath

    def _group_by_category(
        self, issues: list[dict], category: str | None
    ) -> dict[str, list[dict]]:
        """按标签/分类将 issue 分组。"""
        if category:
            # 只保留匹配指定分类的
            filtered = [
                i for i in issues if category.lower() in
                [lb.lower() for lb in i.get("labels", [])]
            ]
            return {category: filtered} if filtered else {"未分类": issues}

        groups: dict[str, list[dict]] = defaultdict(list)
        for issue in issues:
            cat = self._infer_category(issue)
            groups[cat].append(issue)
        return dict(groups)

    def _infer_category(self, issue: dict) -> str:
        """从标签推断 issue 分类。"""
        known_categories = [
            "安装", "导入", "timeline", "numa", "性能", "报错",
            "install", "import", "performance", "error", "bug",
        ]
        for label in issue.get("labels", []):
            if label.lower() in known_categories:
                return label
        return "其他"

    def _cluster_similar(self, issues: list[dict]) -> list[list[dict]]:
        """将相似 issue 聚类。简单策略：基于 embedding 相似度分组。"""
        if len(issues) <= 1:
            return [issues] if issues else []

        # 构建文本列表
        texts = [_build_issue_text(i, include_comments=False) for i in issues]

        # 如果索引为空或太小，直接返回不聚类
        if self.engine.index_size() == 0:
            return [[i] for i in issues]

        # 用每条 issue 搜索相似的，贪心分组
        clustered: set[int] = set()
        clusters: list[list[dict]] = []

        for i, issue in enumerate(issues):
            if i in clustered:
                continue
            cluster = [issue]
            # 用 embedding 搜索
            results = self.engine.search(
                texts[i], top_k=min(10, len(issues)), exclude_number=issue.get("number")
            )
            for r in results:
                if r["score"] < 0.85:
                    continue
                for j, other in enumerate(issues):
                    if j != i and j not in clustered and other["number"] == r["number"]:
                        cluster.append(other)
                        clustered.add(j)
                        break
            clustered.add(i)
            clusters.append(cluster)

        return clusters

    def _render_faq(
        self, category: str, clusters: list[list[dict]], draft: bool
    ) -> str:
        """渲染一个分类的 FAQ Markdown。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# FAQ: {category}",
            "",
            f"> 生成时间: {now}",
            f"> 来源: {settings.gitcode_repo} 历史 Issue",
        ]
        if draft:
            lines += ["", "> ⚠️ **草稿** - 请维护者审核后发布"]
        lines.append("")

        for i, cluster in enumerate(clusters, 1):
            representative = cluster[0]
            related = cluster[1:] if len(cluster) > 1 else []

            lines += [
                f"## {i}. {representative.get('title', '未知问题')}",
                "",
                f"**问题现象**:",
                f"> {representative.get('body', '')[:300]}",
                "",
            ]

            # 适用版本（从标签或正文提取）
            versions = [lb for lb in representative.get("labels", []) if "v" in lb.lower()]
            if versions:
                lines.append(f"**适用版本**: {', '.join(versions)}")
                lines.append("")

            # 可能原因
            lines += [
                f"**可能原因**:",
                f"> 待补充（基于 Issue 描述推断）",
                "",
            ]

            # 解决方法
            solution = representative.get("solution", "")
            if solution:
                lines += [
                    f"**解决方法**:",
                    f"> {solution[:500]}",
                    "",
                ]
            else:
                lines += [
                    f"**解决方法**:",
                    f"> 参考关联 Issue 中的讨论",
                    "",
                ]

            # 关联 Issue
            all_related = related
            lines.append(f"**关联 Issue**:")
            lines.append(f"- #{representative.get('number')} ({representative.get('url', '')})")
            for r in all_related:
                lines.append(f"- #{r.get('number')} ({r.get('url', '')})")
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _render_single_faq(self, issue: dict, category: str, draft: bool) -> str:
        """为单条 Issue 渲染 FAQ。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# FAQ: {issue.get('title', '未知问题')}",
            "",
            f"> 生成时间: {now}",
            f"> 分类: {category}",
        ]
        if draft:
            lines.append("> ⚠️ **草稿** - 请维护者审核后发布")
        lines += [
            "",
            f"**问题现象**:",
            f"> {issue.get('body', '')[:500]}",
            "",
            f"**解决方法**:",
            f"> {issue.get('solution', '待补充')[:500]}",
            "",
            f"**关联 Issue**: #{issue.get('number')} ({issue.get('url', '')})",
            f"**标签**: {', '.join(issue.get('labels', [])) or '无'}",
        ]
        return "\n".join(lines)
