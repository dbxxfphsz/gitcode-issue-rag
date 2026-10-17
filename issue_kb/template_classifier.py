"""Issue 模板噪声清洗 - 频率预筛候选 + LLM 语义判定 keep/remove。

GitCode 仓库的 Issue 常带固定模板：既有"无意义噪声"（社区页脚客套话、提交须知、
安全信息提醒等，与具体问题无关、抬高相似度基线），也有"有意义的结构骨架"（如
"### 🐛 问题描述""### 环境信息"，有助于阅读 Issue）。纯频率统计无法区分二者——
高频行既可能是噪声也可能是结构标题。

本模块用"混合策略"：
1. 频率仅用于**预筛候选**——只把在多条 Issue 中重复出现的行交给 LLM（只出现一次的
   用户独特内容天然保留、不浪费调用），把 LLM 判定量压到"重复行"级别；
2. remove/keep 的**最终判定 100% 由 LLM 语义决定**，不再仅靠相似度/频率。

判定结果持久化在 kb_dir/llm_template_cache.json（人可读可编辑，可手改 verdict 后
重落地）。clean_body 仅查缓存、幂等，保证录入侧与查询侧对称；LLM 失败时降级为保留，
绝不误删用户内容。
"""

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from issue_kb.config import settings
from issue_kb.llm import chat_json

# LLM 判定提示：用用户给的例子锚定 remove/keep 标准，要求仅输出 JSON。
_CLASSIFY_SYSTEM = """你是 Issue 文本清洗助手。给你若干来自 GitCode Issue 正文的"候选行"，请逐行判定：

- "remove"（剔除）：与具体问题无关的无意义模板噪声。包括平台页脚/客套话、提交须知、安全或敏感信息提醒、通用引导语、未填写的空模板占位等。这些文字在几乎每条 Issue 中都雷同、不提供区分度、无助于理解具体问题。
- "keep"（保留）：有助于阅读或理解 Issue 的内容。包括结构性标题/字段标签（如"### 🐛 问题描述""### 环境信息""### 替代方案"），以及任何用户填写的具体描述、环境值、报错信息、复现步骤、期望结果等。

判定原则：剔除"样板客套话与须知"，保留"结构骨架 + 用户真实内容"。宁可保守保留，也不误删用户信息。

示例：
- "欢迎加入社区，感谢您对社区的贡献 🎉!" → remove（社区页脚客套话）
- "**提交提案之前，请先检索仓库内是否已有相同的提案，如已有请在同一提案中进行讨论。**" → remove（提交须知）
- "⚠️ **安全信息提醒**：请仔细检查提供的文本内容，确保其不包含敏感数据信息" → remove（安全提醒模板）
- "### 🐛 问题描述" → keep（结构标题，帮助定位问题描述内容）
- "### 环境信息" → keep（结构标题）
- "### 替代方案" → keep（结构标题）
- "系统：windows 11 专业版" → keep（用户填写的环境值）
- "打开工具界面后点击导入按钮报错 500" → keep（用户描述的具体问题）

仅输出 JSON，不要任何额外文字，格式：
{"classifications": [{"index": <行号，从1开始>, "verdict": "remove" 或 "keep", "reason": "<简要中文理由>"}]}"""


class TemplateClassifier:
    """模板行 LLM 语义判定与 body 清洗。"""

    def __init__(self, kb_dir: str | Path | None = None):
        self.kb_dir = Path(kb_dir or settings.kb_dir)
        self.cache_file = self.kb_dir / "llm_template_cache.json"
        self._cache: dict[str, dict] | None = None

    # ---- 缓存读写 ----

    def _load(self) -> dict[str, dict]:
        """加载判定缓存 {text: {"verdict","reason"}}（带内存缓存）。文件不存在返回空。"""
        if self._cache is not None:
            return self._cache
        if self.cache_file.exists():
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self._cache = data.get("lines", {})
        else:
            self._cache = {}
        return self._cache

    def reload(self):
        """清除内存缓存，下次 _load 重新读文件（手改缓存文件后用）。"""
        self._cache = None

    def _save(self):
        """持久化判定缓存（人可读可编辑）。"""
        cache = self._load()
        payload = {
            "model": settings.llm_model,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_classified": len(cache),
            "min_support": settings.template_min_support,
            "lines": cache,
        }
        self.cache_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def verdict(self, text: str) -> dict | None:
        """查询单行的缓存判定结果（{"verdict","reason"} 或 None）。"""
        return self._load().get(text.strip())

    def cache_size(self) -> int:
        """当前缓存的判定行数。"""
        return len(self._load())

    # ---- 频率预筛（仅缩小 LLM 判定范围，不做 remove/keep 决策）----

    def _doc_freq(self, issues: list[dict]) -> Counter:
        """统计规范化行的文档频率（一行出现在多少条 Issue 中）。"""
        df: Counter = Counter()
        for issue in issues:
            raw = issue.get("body_raw") or issue.get("body", "") or ""
            seen: set[str] = set()
            for line in raw.split("\n"):
                norm = line.strip()
                if len(norm) >= settings.template_min_line_len:
                    seen.add(norm)
            for norm in seen:  # 每 issue 内去重，统计"出现的 issue 数"
                df[norm] += 1
        return df

    def discover_candidates(self, issues: list[dict]) -> list[dict]:
        """频率预筛：返回出现数 >= min_support 的重复行 [{"text","count"}]，按 count 降序。

        这一步只负责"哪些行值得送 LLM 判定"（重复出现的行），不做 remove/keep 决策。
        只出现一次的行（用户独特内容）不会成为候选，天然保留。
        """
        df = self._doc_freq(issues)
        candidates = [
            {"text": text, "count": count}
            for text, count in df.items()
            if count >= settings.template_min_support
        ]
        candidates.sort(key=lambda x: x["count"], reverse=True)
        return candidates

    # ---- LLM 语义判定 ----

    def _classify_batch(self, lines: list[str]) -> list[tuple[str, str, str]] | None:
        """调用 LLM 判定一批行。返回 [(text, verdict, reason)]；整批失败返回 None。"""
        numbered = "\n".join(f"{i + 1}. {ln}" for i, ln in enumerate(lines))
        messages = [
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": f"请判定以下 {len(lines)} 行：\n{numbered}"},
        ]
        data = chat_json(messages, temperature=0.0)
        if not isinstance(data, dict) or not isinstance(data.get("classifications"), list):
            return None
        out: list[tuple[str, str, str]] = []
        seen_idx: set[int] = set()
        for item in data["classifications"]:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if not (1 <= idx <= len(lines)) or idx in seen_idx:
                continue  # 越界或重复行号，忽略
            seen_idx.add(idx)
            verdict = str(item.get("verdict", "")).strip().lower()
            verdict = verdict if verdict in ("remove", "keep") else "keep"  # 非法/缺失 → 保守保留
            reason = str(item.get("reason", "")).strip()
            out.append((lines[idx - 1], verdict, reason))
        return out

    def classify_lines(self, lines: list[str]) -> dict:
        """批量调用 LLM 判定 remove/keep，写缓存。返回统计。

        只判定未缓存的行；每批成功即落盘（支持中断续跑）；LLM 失败的行保持未缓存
        （= clean_body 中保留），重跑可自动补判。
        """
        cache = self._load()
        # 去重 + 过滤已缓存，保持顺序
        pending: list[str] = []
        seen: set[str] = set()
        for ln in lines:
            if ln in cache or ln in seen:
                continue
            seen.add(ln)
            pending.append(ln)
        if not pending:
            logger.info("无新增候选行需 LLM 判定（全部已缓存）")
            return {"classified": 0, "remove": 0, "keep": 0, "failed": 0}

        batch = settings.template_llm_batch
        total_batches = (len(pending) + batch - 1) // batch
        classified = removed = kept = failed = 0
        logger.info(f"送 LLM 判定 {len(pending)} 行候选（批次大小 {batch}，共 {total_batches} 批）")
        for i in range(0, len(pending), batch):
            chunk = pending[i : i + batch]
            bno = i // batch + 1
            result = self._classify_batch(chunk)
            if result is None:
                failed += len(chunk)
                logger.warning(
                    f"  批次 {bno}/{total_batches}：{len(chunk)} 行 LLM 判定失败，"
                    f"保持未缓存（=保留），重跑可补判"
                )
                continue
            for text, verdict, reason in result:
                cache[text] = {"verdict": verdict, "reason": reason}
                classified += 1
                if verdict == "remove":
                    removed += 1
                else:
                    kept += 1
            self._save()  # 每批落盘：中断或后续批次失败时，已判定部分不丢失
            logger.info(
                f"  批次 {bno}/{total_batches}：判定 {len(result)} 行"
                f"（累计 remove {removed} / keep {kept}）"
            )
        logger.info(
            f"LLM 模板判定完成：新增 {classified} 行（remove {removed} / keep {kept}），"
            f"失败 {failed} 行"
        )
        return {"classified": classified, "remove": removed, "keep": kept, "failed": failed}

    def refresh(self, issues: list[dict]) -> dict:
        """频率预筛候选 → LLM 判定未缓存行 → 写缓存。供 build 预pass 与 --preview 复用。"""
        candidates = self.discover_candidates(issues)
        stats = self.classify_lines([c["text"] for c in candidates])
        stats["candidates"] = len(candidates)
        return stats

    # ---- 清洗（仅查缓存，不触发 LLM）----

    def clean_body(self, body: str) -> str:
        """按缓存剔除 verdict=remove 的行；其余（keep/未缓存/独特行）保留。

        幂等：已清洗文本再清洗无变化。未启用清洗或缓存为空时原样返回。
        """
        if not settings.clean_template:
            return body
        cache = self._load()
        if not cache or not body:
            return body
        remove_set = {t for t, v in cache.items() if v.get("verdict") == "remove"}
        if not remove_set:
            return body
        kept = []
        for line in body.split("\n"):
            if line.strip() in remove_set:
                continue  # 命中"剔除"判定，丢弃
            kept.append(line)
        # 合并因剔除产生的连续空行，并去首尾空白
        return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
