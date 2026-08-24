"""入库流水线 - 文本分块 + embedding + 写入向量库。

RAG 核心流程（类比前端）：
  原始数据 → 清洗转换 → 拆分成小块 → 向量化 → 存储
  类似：API数据 → map/filter → chunk → JSON.stringify → IndexedDB
"""

import time

from loguru import logger
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.shared.schemas import Issue
from app.shared.models import get_vectorstore

# ---- 分批配置 ----
BATCH_SIZE = 10  # 百炼 text-embedding-v3 单次最多 10 条，超过会报 InvalidParameter
MAX_RETRIES = 3  # 单批最多重试次数
RETRY_BASE_DELAY = 2  # 重试基础等待秒数（指数退避：2s, 4s, 8s）

# ---- 文本分块器 ----
# chunk_size=800: 每个块约 800 字符，issue 内容长短不一，这个值比较平衡
# chunk_overlap=100: 块之间重叠 100 字符，避免在边界处切断上下文
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,
    separators=["\n\n", "\n", "。", " ", ""],  # 中文友好的分隔符
)


def issue_to_document(issue: Issue) -> Document:
    """将 Issue 转为 LangChain Document 对象。

    metadata 中存入 issue 的关键信息，方便检索时直接拿到：
    - issue_id: 用于去重判断
    - url: 查重结果需要返回的链接
    - title: 便于日志和调试
    """
    return Document(
        page_content=issue.to_document_text(),
        metadata={
            "issue_id": issue.issue_id,
            "url": issue.url,
            "title": issue.title,
            "state": issue.state,
            "labels": ",".join(issue.labels) if issue.labels else "",
        },
    )


def ingest_issues(issues: list[Issue]) -> int:
    """将一批 issue 入库到向量库（分批 + 重试）。

    流程：Issue → Document → 分块 → 分批 embedding + 写入 ChromaDB
    每批最多 BATCH_SIZE 个块，失败时指数退避重试。

    Args:
        issues: 要入库的 issue 列表

    Returns:
        实际写入的文档块数量
    """
    if not issues:
        logger.warning("没有需要入库的 issue")
        return 0

    # 1. 转为 Document
    docs = [issue_to_document(issue) for issue in issues]

    # 2. 分块
    chunks = _splitter.split_documents(docs)
    total = len(chunks)
    logger.info(f"{len(issues)} 条 issue 分成 {total} 个块，将分批入库（每批 {BATCH_SIZE} 个）")

    # 3. 分批写入向量库（带重试）
    vectorstore = get_vectorstore()
    written = 0

    for i in range(0, total, BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                vectorstore.add_documents(batch)
                written += len(batch)
                logger.info(
                    f"  批次 {batch_num}/{total_batches} 成功 "
                    f"({len(batch)} 个块，累计 {written}/{total})"
                )
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    logger.error(
                        f"  批次 {batch_num}/{total_batches} 重试 {MAX_RETRIES} 次仍失败: {e}"
                    )
                    raise
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    f"  批次 {batch_num}/{total_batches} 第 {attempt} 次失败: {e}，"
                    f"{delay}s 后重试"
                )
                time.sleep(delay)

        # 批次间短暂停顿，避免触发限流
        if i + BATCH_SIZE < total:
            time.sleep(0.5)

    logger.info(f"入库完成: {written} 个块已写入 ChromaDB")
    return written


def get_existing_issue_ids() -> set[str]:
    """获取向量库中已有的所有 issue_id，用于增量去重。

    遍历整个集合拿 metadata，如果数据量大了（几万条以上），
    可以改为用 SQLite 单独维护一个已入库的 ID 表。
    """
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    # ChromaDB 的 get() 返回所有文档的 metadata
    all_metadata = collection.get(include=["metadatas"])

    issue_ids = set()
    for meta in all_metadata.get("metadatas", []):
        if meta and "issue_id" in meta:
            issue_ids.add(meta["issue_id"])

    return issue_ids
