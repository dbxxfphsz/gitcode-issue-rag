"""相似性搜索引擎 - 直接调用 OpenAI Embedding API + numpy 余弦相似度。

不依赖 LangChain 或 ChromaDB，所有 embedding 缓存在知识库目录中。
"""

import json
from pathlib import Path

import httpx
import numpy as np
from loguru import logger

from issue_kb.config import settings


def _get_embeddings_api(texts: list[str]) -> list[list[float]]:
    """调用 OpenAI 兼容 API 获取 embedding 向量。"""
    resp = httpx.post(
        f"{settings.openai_api_base}/embeddings",
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={"model": settings.embedding_model, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return [item["embedding"] for item in data["data"]]


def _build_issue_text(issue: dict, include_comments: bool = True) -> str:
    """将 issue 数据拼成适合 embedding 的文本。"""
    parts = [
        f"标题: {issue.get('title', '')}",
        f"标题: {issue.get('title', '')}",  # 重复提高权重
        f"问题描述: {issue.get('body', '')}",
    ]
    labels = issue.get("labels", [])
    if labels:
        parts.append(f"标签: {', '.join(labels)}")
    solution = issue.get("solution", "")
    if solution:
        parts.append(f"解决方案: {solution}")
    if include_comments and issue.get("comments_data"):
        # 只取前 3 条评论的摘要
        for c in issue["comments_data"][:3]:
            cbody = (c.get("body", "") or "")[:200]
            if cbody:
                parts.append(f"评论: {cbody}")
    return "\n".join(parts)


class SimilarityEngine:
    """基于 embedding 缓存的相似性搜索引擎。"""

    def __init__(self, kb_dir: str | Path | None = None):
        self.kb_dir = Path(kb_dir or settings.kb_dir)
        self.index_file = self.kb_dir / "embeddings.json"
        self._index: dict[str, list[float]] | None = None

    def _load_index(self) -> dict[str, list[float]]:
        if self._index is not None:
            return self._index
        if self.index_file.exists():
            self._index = json.loads(self.index_file.read_text(encoding="utf-8"))
        else:
            self._index = {}
        return self._index

    def _save_index(self):
        if self._index is not None:
            self.index_file.write_text(
                json.dumps(self._index), encoding="utf-8"
            )

    def update_embedding(self, issue_number: int | str, text: str):
        """为一条 issue 计算并缓存 embedding。"""
        idx = self._load_index()
        key = str(issue_number)
        vectors = _get_embeddings_api([text])
        idx[key] = vectors[0]
        self._save_index()

    def remove_embedding(self, issue_number: int | str):
        """移除一条 issue 的 embedding（内容更新后需重算时使用）。"""
        idx = self._load_index()
        if idx.pop(str(issue_number), None) is not None:
            self._save_index()

    # ---- 批量构建 ----

    def _embed_batches(
        self, texts: list[str], numbers: list[str], batch_size: int
    ) -> list[str]:
        """分批调用 embedding API，每批成功后立即落盘（支持断点续建）。

        Returns:
            失败批次包含的 issue 编号列表（供记录与重试）
        """
        idx = self._load_index()
        failed: list[str] = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_nums = numbers[i : i + batch_size]
            batch_no = i // batch_size + 1
            try:
                vectors = _get_embeddings_api(batch_texts)
                for num, vec in zip(batch_nums, vectors):
                    idx[num] = vec
                # 每批成功即保存：中断或后续批次失败时，已构建部分不丢失
                self._save_index()
                logger.info(
                    f"  批次 {batch_no}: {len(batch_texts)} 条成功"
                    f"（累计 {len(idx)} 条）"
                )
            except Exception as e:
                logger.error(
                    f"  批次 {batch_no} 失败（{len(batch_nums)} 条: "
                    f"{', '.join(batch_nums)}）: {e}"
                )
                failed.extend(batch_nums)
        return failed

    def _retry_failed(
        self,
        text_by_num: dict[str, str],
        failed: list[str],
        batch_size: int,
        rounds: int = 1,
    ) -> list[str]:
        """对失败的 issue 在最后统一重试，返回重试后仍失败的编号列表。"""
        for round_num in range(1, rounds + 1):
            if not failed:
                break
            logger.info(f"最后重试第 {round_num} 轮: {len(failed)} 条失败项...")
            texts = [text_by_num[n] for n in failed]
            failed = self._embed_batches(texts, list(failed), batch_size)
        return failed

    def ensure_index(
        self, issues: list[dict], batch_size: int = 10, retry_rounds: int = 1
    ) -> dict:
        """增量构建 embedding 索引：跳过已有向量的 issue，只计算新增部分。

        失败批次会被记录并在最后重试；成功的批次即时落盘，
        中断后重新运行只需补齐未完成部分。

        Returns:
            {"added": 新增条数, "skipped": 跳过条数, "failed": [失败编号]}
        """
        idx = self._load_index()
        pending = [i for i in issues if str(i["number"]) not in idx]
        skipped = len(issues) - len(pending)
        if skipped:
            logger.info(f"{skipped} 条 issue 已有 embedding，跳过")
        if not pending:
            return {"added": 0, "skipped": skipped, "failed": []}

        texts = [
            _build_issue_text(i, settings.include_comments) for i in pending
        ]
        numbers = [str(i["number"]) for i in pending]
        text_by_num = dict(zip(numbers, texts))

        logger.info(f"开始增量 embedding: {len(texts)} 条（批次大小 {batch_size}）")
        failed = self._embed_batches(texts, numbers, batch_size)
        failed = self._retry_failed(text_by_num, failed, batch_size, retry_rounds)

        if failed:
            logger.warning(
                f"最终仍有 {len(failed)} 条失败: {failed}，"
                f"重新运行构建命令即可自动补齐"
            )
        return {
            "added": len(texts) - len(failed),
            "skipped": skipped,
            "failed": [int(n) for n in failed],
        }

    def rebuild_index(
        self, issues: list[dict], batch_size: int = 10, retry_rounds: int = 1
    ) -> dict:
        """全量重建 embedding 索引（清空现有索引）。失败批次同样记录并重试。"""
        self._index = {}
        texts = [
            _build_issue_text(i, settings.include_comments) for i in issues
        ]
        numbers = [str(i["number"]) for i in issues]
        text_by_num = dict(zip(numbers, texts))

        logger.info(f"开始全量重建 embedding 索引: {len(texts)} 条")
        failed = self._embed_batches(texts, numbers, batch_size)
        failed = self._retry_failed(text_by_num, failed, batch_size, retry_rounds)

        logger.info(f"embedding 索引重建完成: {len(self._index)} 条")
        if failed:
            logger.warning(f"最终仍有 {len(failed)} 条失败: {failed}")
        return {
            "added": len(texts) - len(failed),
            "skipped": 0,
            "failed": [int(n) for n in failed],
        }

    def search(
        self,
        query_text: str,
        top_k: int | None = None,
        exclude_number: int | str | None = None,
    ) -> list[dict]:
        """搜索相似 issue。

        Args:
            query_text: 查询文本
            top_k: 返回条数
            exclude_number: 排除的 issue 编号（避免自匹配，支持 int/str）

        Returns:
            [{"number": str, "score": float, "issue": dict}, ...]
        """
        k = top_k or settings.scan_top_k
        idx = self._load_index()

        if not idx:
            logger.warning("embedding 索引为空，请先构建知识库")
            return []

        # 计算查询向量
        query_vec = _get_embeddings_api([query_text])[0]
        query_arr = np.array(query_vec)

        # 统一 exclude_number 为 str，与 key 类型一致
        exclude_key = str(exclude_number) if exclude_number is not None else None

        # 计算余弦相似度
        results = []
        for key, vec in idx.items():
            if exclude_key is not None and key == exclude_key:
                continue
            vec_arr = np.array(vec)
            score = float(
                np.dot(query_arr, vec_arr)
                / (np.linalg.norm(query_arr) * np.linalg.norm(vec_arr) + 1e-10)
            )
            results.append({"number": key, "score": round(score, 4)})

        # 按分数降序排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:k]

    def index_size(self) -> int:
        return len(self._load_index())
