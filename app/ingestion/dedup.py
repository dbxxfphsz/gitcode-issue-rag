"""Issue 查重服务 - 接收新 issue 描述，返回是否重复 + 已有答案链接。

核心逻辑：
  1. 将新 issue 的描述文本做 embedding
  2. 在向量库中做相似度检索（top-k）
  3. 如果最高相似度 > 阈值，判定为重复，返回对应 issue 的 URL
  4. 否则判定为新问题

类比前端：类似搜索框的"联想建议"，只不过这里判断的是"有没有一样的"。
"""

from pydantic import BaseModel
from loguru import logger

from app.config import settings
from app.shared.models import get_vectorstore


class DedupResult(BaseModel):
    """查重结果。"""

    is_duplicate: bool  # 是否重复
    duplicate_url: str | None = None  # 重复 issue 的 URL（仅重复时有值）
    similarity: float = 0.0  # 最高相似度分数
    matched_title: str | None = None  # 匹配到的 issue 标题


def check_duplicate(query_text: str) -> DedupResult:
    """检查给定的 issue 描述是否已有相同问题。

    Args:
        query_text: 新 issue 的描述文本（标题 + 正文）

    Returns:
        DedupResult: 包含是否重复、重复链接、相似度分数
    """
    vectorstore = get_vectorstore()

    # 相似度检索，返回 top-k 结果
    results = vectorstore.similarity_search_with_relevance_scores(
        query_text,
        k=settings.dedup_top_k,
    )

    if not results:
        logger.info("向量库为空或无匹配结果")
        return DedupResult(is_duplicate=False)

    # 取最高分的结果
    best_doc, best_score = results[0]
    metadata = best_doc.metadata

    logger.info(
        f"查重结果: 最高相似度={best_score:.4f}, "
        f"匹配 issue={metadata.get('issue_id')} '{metadata.get('title')}'"
    )

    # 判断是否超过阈值
    is_duplicate = best_score >= settings.dedup_similarity_threshold

    return DedupResult(
        is_duplicate=is_duplicate,
        duplicate_url=metadata.get("url") if is_duplicate else None,
        similarity=round(best_score, 4),
        matched_title=metadata.get("title") if is_duplicate else None,
    )
