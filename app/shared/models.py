"""Embedding 模型和向量库的工厂函数 - 保证全局使用同一个实例。

类比前端：就像 React 的 Context Provider，全局提供同一个实例，
避免不同模块创建不同的 embedding 模型导致向量不兼容。
"""

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

from app.config import settings

# ---- 模块级单例 ----
_embeddings: OpenAIEmbeddings | None = None
_vectorstore: Chroma | None = None


def get_embeddings() -> OpenAIEmbeddings:
    """获取 Embedding 模型单例。

    索引和查询必须用同一个 embedding 模型，否则向量维度/语义空间不同，
    搜索结果会完全不准——这是 RAG 最常见的坑之一。
    """
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(
            model=settings.embedding_model,
            openai_api_key=settings.openai_api_key,
            openai_api_base=settings.openai_api_base,
            # 关键：禁止 langchain 先把文本转成 token ID 再发给 API。
            # 百炼的接口只接受纯文本字符串，收到 token ID 会报 InvalidParameter。
            check_embedding_ctx_length=False,
        )
    return _embeddings


def get_vectorstore() -> Chroma:
    """获取 Chroma 向量库单例（自动持久化到磁盘）。

    如果本地已有数据会自动加载，没有则创建新集合。
    """
    global _vectorstore
    if _vectorstore is None:
        settings.chroma_persist_path.mkdir(parents=True, exist_ok=True)
        _vectorstore = Chroma(
            collection_name=settings.chroma_collection_name,
            embedding_function=get_embeddings(),
            persist_directory=str(settings.chroma_persist_path),
        )
    return _vectorstore
