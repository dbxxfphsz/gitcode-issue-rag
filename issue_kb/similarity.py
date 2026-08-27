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

    def update_embedding(self, issue_number: int, text: str):
        """为一条 issue 计算并缓存 embedding。"""
        idx = self._load_index()
        key = str(issue_number)
        vectors = _get_embeddings_api([text])
        idx[key] = vectors[0]
        self._save_index()

    def rebuild_index(self, issues: list[dict], batch_size: int = 10):
        """从 issue 列表重建 embedding 索引。"""
        self._index = {}
        texts = []
        numbers = []
        for issue in issues:
            text = _build_issue_text(issue, settings.include_comments)
            texts.append(text)
            numbers.append(str(issue["number"]))

        total = len(texts)
        logger.info(f"开始重建 embedding 索引: {total} 条 issue")

        for i in range(0, total, batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_nums = numbers[i : i + batch_size]
            try:
                vectors = _get_embeddings_api(batch_texts)
                for num, vec in zip(batch_nums, vectors):
                    self._index[num] = vec
                logger.info(
                    f"  embedding 批次 {i // batch_size + 1}: "
                    f"{len(batch_texts)} 条"
                )
            except Exception as e:
                logger.error(f"  embedding 批次失败: {e}")

        self._save_index()
        logger.info(f"embedding 索引重建完成: {len(self._index)} 条")

    def search(
        self,
        query_text: str,
        top_k: int | None = None,
        exclude_number: int | None = None,
    ) -> list[dict]:
        """搜索相似 issue。

        Args:
            query_text: 查询文本
            top_k: 返回条数
            exclude_number: 排除的 issue 编号（避免自匹配）

        Returns:
            [{"number": int, "score": float, "issue": dict}, ...]
        """
        k = top_k or settings.scan_top_k
        idx = self._load_index()

        if not idx:
            logger.warning("embedding 索引为空，请先构建知识库")
            return []

        # 计算查询向量
        query_vec = _get_embeddings_api([query_text])[0]
        query_arr = np.array(query_vec)

        # 计算余弦相似度
        results = []
        for key, vec in idx.items():
            num = int(key)
            if exclude_number is not None and num == exclude_number:
                continue
            vec_arr = np.array(vec)
            score = float(
                np.dot(query_arr, vec_arr)
                / (np.linalg.norm(query_arr) * np.linalg.norm(vec_arr) + 1e-10)
            )
            results.append({"number": num, "score": round(score, 4)})

        # 按分数降序排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:k]

    def index_size(self) -> int:
        return len(self._load_index())
