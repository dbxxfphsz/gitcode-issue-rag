"""FAQ 文档生成 - 从知识库中筛选已解决的 Issue，聚类合并后生成 FAQ。

支持：
  - 全量生成 / 增量更新 / 指定 Issue 生成
  - 按组件、标签或问题类型分类
  - 相似 Issue 聚类合并，避免重复
  - 草稿模式（默认生成待审核内容）
  - 中英双语：中文与英文分别输出到 docs/faq/zh/ 和 docs/faq/en/ 两个目录。
    LLM 每条 Issue 只调用一次即同时产出中英文字段；LLM 不可用时降级为仅中文，
    并跳过英文文档（不产生半成品）。
"""

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from issue_kb.config import settings
from issue_kb.llm import chat_json
from issue_kb.similarity import SimilarityEngine, _build_issue_text


class FAQGenerator:
    """FAQ 文档生成器（中英双语，分目录输出）。"""

    # 分类名中英映射（英文文档使用；未命中的分类保留原名）
    _CATEGORY_EN = {
        "安装": "Installation",
        "导入": "Import",
        "性能": "Performance",
        "报错": "Error",
        "其他": "Others",
        "未分类": "Uncategorized",
        "timeline": "Timeline",
        "numa": "NUMA",
        "install": "Installation",
        "import": "Import",
        "performance": "Performance",
        "error": "Error",
        "bug": "Bug",
    }

    def __init__(self, kb_dir: str | Path | None = None, faq_dir: str | Path | None = None):
        self.kb_dir = Path(kb_dir or settings.kb_dir)
        self.faq_dir = Path(faq_dir or settings.faq_dir)
        # 中英文分目录输出
        self.zh_dir = self.faq_dir / "zh"
        self.en_dir = self.faq_dir / "en"
        self.zh_dir.mkdir(parents=True, exist_ok=True)
        self.en_dir.mkdir(parents=True, exist_ok=True)
        self.engine = SimilarityEngine(self.kb_dir)

    def generate(
        self,
        issues: list[dict],
        category: str | None = None,
        incremental: bool = False,
        draft: bool = True,
        limit: int | None = None,
    ) -> list[Path]:
        """从 issue 列表生成 FAQ 文档（中英文分别写入 zh/ 与 en/ 目录）。

        Args:
            issues: issue 数据列表
            category: 按分类生成（如 "安装", "Timeline", "NUMA"），None 则全量
            incremental: 增量模式（只处理新增/更新的 issue）
            draft: 是否标记为草稿
            limit: 仅处理前 N 条已解决 Issue（调试用，降低 LLM 调用开销），None 为全量

        Returns:
            生成的文件路径列表
        """
        # 1. 筛选已解决的 issue
        resolved = [i for i in issues if i.get("state") == "closed" and i.get("solution")]
        if not resolved:
            logger.warning("没有已解决且有解决方案的 Issue")
            return []

        logger.info(f"筛选出 {len(resolved)} 条已解决 Issue")

        # 调试友好：limit 限制处理条数，避免全量生成时 LLM 调用开销过大
        if limit is not None and limit > 0 and len(resolved) > limit:
            logger.info(f"调试模式：仅处理前 {limit} 条（共 {len(resolved)} 条）")
            resolved = resolved[:limit]

        # 2. 按标签/分类分组
        groups = self._group_by_category(resolved, category)

        # 3. 对每组进行相似聚类，生成中英文两份文档
        generated_files = []
        for group_name, group_issues in groups.items():
            clusters = self._cluster_similar(group_issues)
            logger.info(
                f"分类 [{group_name}]: {len(group_issues)} 条 Issue → {len(clusters)} 个聚类"
            )

            # 预取每个聚类的双语字段：LLM 每条只调用一次，中英文渲染共用
            cluster_data = self._build_cluster_data(clusters)

            safe_name = group_name.replace("/", "_").replace(" ", "_")
            suffix = "_draft" if draft else ""
            filename = f"{safe_name}{suffix}.md"

            # 4. 分别渲染并写入中文 / 英文文档
            generated_files += self._write_pair(
                group_name, cluster_data, draft, filename
            )

        return generated_files

    def _write_pair(
        self, category: str, cluster_data: list[dict], draft: bool, filename: str
    ) -> list[Path]:
        """将同一批聚类渲染为中英文两份文档，分别写入 zh/ 与 en/ 目录。"""
        written: list[Path] = []

        zh_content = self._render_faq(category, cluster_data, draft, lang="zh")
        zh_path = self.zh_dir / filename
        zh_path.write_text(zh_content, encoding="utf-8")
        written.append(zh_path)
        logger.info(f"  已生成(中文): {zh_path}")

        en_content = self._render_faq(category, cluster_data, draft, lang="en")
        if en_content:
            en_path = self.en_dir / filename
            en_path.write_text(en_content, encoding="utf-8")
            written.append(en_path)
            logger.info(f"  已生成(英文): {en_path}")
        else:
            logger.warning(
                f"分类 [{category}] 无英文内容（LLM 未启用或降级），跳过英文文档"
            )

        return written

    def generate_single(self, issue: dict, draft: bool = True) -> Path | None:
        """为单条 Issue 生成 FAQ 条目（中英文分别写入 zh/ 与 en/ 目录）。"""
        if not issue.get("solution"):
            logger.warning(f"#{issue.get('number')} 没有解决方案，跳过")
            return None

        category = self._infer_category(issue)
        # LLM 只调用一次，中英文共用字段
        fields = self._faq_fields(issue)

        safe_name = f"issue_{issue['number']}"
        suffix = "_draft" if draft else ""
        filename = f"{safe_name}{suffix}.md"

        zh_path = self.zh_dir / filename
        zh_path.write_text(
            self._render_single_faq(issue, category, draft, fields, lang="zh"),
            encoding="utf-8",
        )
        logger.info(f"已生成(中文): {zh_path}")

        en_content = self._render_single_faq(issue, category, draft, fields, lang="en")
        if en_content:
            en_path = self.en_dir / filename
            en_path.write_text(en_content, encoding="utf-8")
            logger.info(f"已生成(英文): {en_path}")
        else:
            logger.warning(
                f"#{issue.get('number')} 无英文内容（LLM 降级），跳过英文文档"
            )

        return zh_path

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

    def _build_cluster_data(self, clusters: list[list[dict]]) -> list[dict]:
        """为每个聚类预取双语字段（LLM 每条只调用一次），供中英文渲染共用。"""
        cluster_data = []
        total = len(clusters)
        for i, cluster in enumerate(clusters, 1):
            representative = cluster[0]
            related = cluster[1:] if len(cluster) > 1 else []
            if total > 1:
                logger.info(
                    f"  生成双语字段 {i}/{total}: #{representative.get('number')}"
                )
            fields = self._faq_fields(representative)
            cluster_data.append(
                {
                    "representative": representative,
                    "related": related,
                    "fields": fields,
                }
            )
        return cluster_data

    def _build_bilingual_fields(self, issue: dict) -> dict | None:
        """调用 LLM 生成中英双语 FAQ 字段；LLM 不可用或返回异常时返回 None。"""
        title = issue.get("title", "")
        body = (issue.get("body", "") or "")[:1500]
        solution = (issue.get("solution", "") or "")[:1500]
        labels = ", ".join(issue.get("labels", [])) or "无"

        system = (
            "你是技术文档助手，负责把 GitCode Issue 整理成中英双语 FAQ 条目。"
            "必须严格输出 JSON，不要包含任何解释或 Markdown 代码块围栏。"
        )
        user = (
            "请根据以下 Issue 信息，提炼并生成一条中英双语 FAQ。\n\n"
            f"标题: {title}\n"
            f"问题描述: {body}\n"
            f"解决方案: {solution}\n"
            f"标签: {labels}\n\n"
            "要求:\n"
            "1. 提炼「问题现象」「可能原因」「解决方法」三部分，每部分各给出中文与英文。\n"
            "2. 标题也翻译成英文。\n"
            "3. 原文缺失的信息（尤其「可能原因」）可基于 Issue 描述合理推断，推断内容简洁准确。\n"
            "4. 中英文语义一致，术语专业。\n"
            "5. 严格返回如下结构的 JSON（键名固定，值为字符串）:\n"
            '{"title_zh": "", "title_en": "", "problem_zh": "", "problem_en": "", '
            '"cause_zh": "", "cause_en": "", "solution_zh": "", "solution_en": ""}'
        )

        data = chat_json([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        if not data:
            return None
        if not all(data.get(k) for k in ("title_zh", "problem_zh", "solution_zh")):
            logger.warning(f"#{issue.get('number')} LLM 返回字段不完整，降级为单语")
            return None
        return data

    def _faq_fields(self, issue: dict) -> dict:
        """获取双语 FAQ 字段；LLM 不可用时降级为单语（仅中文原文，英文留空）。"""
        bi = self._build_bilingual_fields(issue)
        if bi:
            return {
                "title_zh": bi.get("title_zh") or issue.get("title", "未知问题"),
                "title_en": bi.get("title_en", ""),
                "problem_zh": bi.get("problem_zh", ""),
                "problem_en": bi.get("problem_en", ""),
                "cause_zh": bi.get("cause_zh", ""),
                "cause_en": bi.get("cause_en", ""),
                "solution_zh": bi.get("solution_zh") or "参考关联 Issue 中的讨论",
                "solution_en": bi.get("solution_en", ""),
            }
        # 降级：纯中文模板，英文字段留空
        solution = issue.get("solution", "") or ""
        return {
            "title_zh": issue.get("title", "未知问题"),
            "title_en": "",
            "problem_zh": (issue.get("body", "") or "")[:300],
            "problem_en": "",
            "cause_zh": "待补充（基于 Issue 描述推断）",
            "cause_en": "",
            "solution_zh": solution[:500] if solution else "参考关联 Issue 中的讨论",
            "solution_en": "",
        }

    @staticmethod
    def _render_block(label: str, text: str) -> list[str]:
        """渲染单个段落（单语）。"""
        return [f"**{label}:**", f"> {text}", ""]

    def _category_name(self, category: str, lang: str) -> str:
        """按语言返回分类名（英文文档尝试翻译，未命中保留原名）。"""
        if lang == "en":
            return self._CATEGORY_EN.get(category.lower(), category)
        return category

    def _render_faq(
        self, category: str, cluster_data: list[dict], draft: bool, lang: str = "zh"
    ) -> str:
        """渲染一个分类的 FAQ Markdown。

        lang="zh" 输出中文文档；lang="en" 输出英文文档（仅含成功生成英文的条目，
        全部缺失时返回空串，由调用方跳过写文件）。
        """
        en = lang == "en"

        # 英文文档：过滤掉降级（无英文内容）的条目
        if en:
            cluster_data = [cd for cd in cluster_data if cd["fields"].get("title_en")]
            if not cluster_data:
                return ""

        cat_name = self._category_name(category, lang)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # 各段落的单语标签
        L_problem = "Problem" if en else "问题现象"
        L_cause = "Possible Cause" if en else "可能原因"
        L_solution = "Solution" if en else "解决方法"
        L_versions = "Applicable Versions" if en else "适用版本"
        L_related = "Related Issues" if en else "关联 Issue"

        if en:
            lines = [
                f"# FAQ: {cat_name}",
                "",
                f"> Generated: {now}",
                f"> Source: {settings.gitcode_repo} historical issues",
            ]
            if draft:
                lines += ["", "> ⚠️ **Draft** - Please review before publishing"]
        else:
            lines = [
                f"# FAQ: {cat_name}",
                "",
                f"> 生成时间: {now}",
                f"> 来源: {settings.gitcode_repo} 历史 Issue",
            ]
            if draft:
                lines += ["", "> ⚠️ **草稿** - 请维护者审核后发布"]
        lines.append("")

        for i, cd in enumerate(cluster_data, 1):
            representative = cd["representative"]
            related = cd["related"]
            fields = cd["fields"]

            title = fields["title_en"] if en else fields["title_zh"]
            lines.append(f"## {i}. {title}")
            lines.append("")

            lines += self._render_block(
                L_problem, fields["problem_en"] if en else fields["problem_zh"]
            )

            # 适用版本（从标签中提取含数字的版本号，避免把 resolved/bug 等误判为版本）
            versions = [
                lb for lb in representative.get("labels", []) if re.search(r"\d", lb)
            ]
            if versions:
                lines.append(f"**{L_versions}:** {', '.join(versions)}")
                lines.append("")

            lines += self._render_block(
                L_cause, fields["cause_en"] if en else fields["cause_zh"]
            )
            lines += self._render_block(
                L_solution, fields["solution_en"] if en else fields["solution_zh"]
            )

            # 关联 Issue
            lines.append(f"**{L_related}:**")
            lines.append(
                f"- #{representative.get('number')} ({representative.get('url', '')})"
            )
            for r in related:
                lines.append(f"- #{r.get('number')} ({r.get('url', '')})")
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _render_single_faq(
        self, issue: dict, category: str, draft: bool, fields: dict, lang: str = "zh"
    ) -> str:
        """为单条 Issue 渲染 FAQ。lang="en" 且无英文内容时返回空串。"""
        en = lang == "en"
        if en and not fields.get("title_en"):
            return ""

        cat_name = self._category_name(category, lang)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        title = fields["title_en"] if en else fields["title_zh"]

        if en:
            lines = [
                f"# FAQ: {title}",
                "",
                f"> Generated: {now}",
                f"> Category: {cat_name}",
            ]
            if draft:
                lines.append("> ⚠️ **Draft** - Please review before publishing")
        else:
            lines = [
                f"# FAQ: {title}",
                "",
                f"> 生成时间: {now}",
                f"> 分类: {cat_name}",
            ]
            if draft:
                lines.append("> ⚠️ **草稿** - 请维护者审核后发布")
        lines.append("")

        lines += self._render_block(
            "Problem" if en else "问题现象",
            fields["problem_en"] if en else fields["problem_zh"],
        )
        lines += self._render_block(
            "Possible Cause" if en else "可能原因",
            fields["cause_en"] if en else fields["cause_zh"],
        )
        lines += self._render_block(
            "Solution" if en else "解决方法",
            fields["solution_en"] if en else fields["solution_zh"],
        )

        labels_text = ", ".join(issue.get("labels", [])) or ("None" if en else "无")
        if en:
            lines += [
                f"**Related Issue:** #{issue.get('number')} ({issue.get('url', '')})",
                f"**Labels:** {labels_text}",
            ]
        else:
            lines += [
                f"**关联 Issue:** #{issue.get('number')} ({issue.get('url', '')})",
                f"**标签:** {labels_text}",
            ]
        return "\n".join(lines)
