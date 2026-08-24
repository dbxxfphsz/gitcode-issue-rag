"""知识库整合 - 定期合并相似知识条目，保持知识库精简。

每月执行一次（由 scheduler 触发）：
  1. 从向量库加载所有知识条目
  2. 两两比较相似度，找出相似组
  3. 用 LLM 将相似条目合并为一个
  4. 删除旧条目，写入合并后的新条目

类比前端：类似 dedup 去重，但这里是用 LLM 理解语义后合并。
"""

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import BaseModel, Field

from app.config import settings
from app.knowledge.knowledge import KnowledgeEntry
from app.shared.models import get_vectorstore

# ---- 整合配置 ----
CONSOLIDATION_BATCH_SIZE = 50  # 每次比较的批次大小

# ---- 合并 Prompt ----

_MERGE_PROMPT = ChatPromptTemplate.from_template(
    """你是一个知识库管理员。以下两个知识条目描述了相似的问题，请将它们合并为一条。

条目 1:
标题: {title1}
分类: {category1}
问题: {problem1}
解决方案: {solution1}
标签: {tags1}

条目 2:
标题: {title2}
分类: {category2}
问题: {problem2}
解决方案: {solution2}
标签: {tags2}

请合并为一条完整的知识条目，保留所有有用信息，去除重复内容。
""",
)


class MergedEntry(BaseModel):
    """LLM 合并结果。"""

    title: str
    category: str
    problem: str
    solution: str
    tags: list[str] = Field(default_factory=list)


def _merge_two_entries(
    e1: KnowledgeEntry, e2: KnowledgeEntry
) -> KnowledgeEntry:
    """用 LLM 将两条相似知识合并为一条。"""
    llm = ChatOpenAI(
        model=settings.llm_model,
        openai_api_key=settings.openai_api_key,
        openai_api_base=settings.openai_api_base,
        temperature=0,
    )
    structured_llm = llm.with_structured_output(MergedEntry)

    try:
        merged = structured_llm.invoke(
            _MERGE_PROMPT.format(
                title1=e1.title,
                category1=e1.category,
                problem1=e1.problem,
                solution1=e1.solution,
                tags1=", ".join(e1.tags),
                title2=e2.title,
                category2=e2.category,
                problem2=e2.problem,
                solution2=e2.solution,
                tags2=", ".join(e2.tags),
            )
        )
        return KnowledgeEntry(
            title=merged.title,
            category=merged.category,
            problem=merged.problem,
            solution=merged.solution,
            related_issue_ids=list(
                set(e1.related_issue_ids + e2.related_issue_ids)
            ),
            tags=list(set(merged.tags)),
        )
    except Exception as e:
        logger.warning(f"合并失败，保留第一条: {e}")
        # 合并失败时手动拼接保留两者信息
        return KnowledgeEntry(
            title=e1.title,
            category=e1.category,
            problem=f"{e1.problem}\n\n---\n\n{e2.problem}",
            solution=e1.solution or e2.solution,
            related_issue_ids=list(
                set(e1.related_issue_ids + e2.related_issue_ids)
            ),
            tags=list(set(e1.tags + e2.tags)),
        )


def consolidate_knowledge_base() -> dict:
    """整合知识库：找出相似条目并合并。

    Returns:
        整合报告字典，包含合并组数、删除数、最终条目数
    """
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    all_data = collection.get(include=["documents", "metadatas"])

    if not all_data["ids"]:
        logger.info("知识库为空，跳过整合")
        return {"merged_groups": 0, "removed": 0, "final_count": 0}

    total = len(all_data["ids"])
    logger.info(f"开始整合知识库，当前 {total} 条知识")

    # 1. 重建知识条目列表
    entries: list[KnowledgeEntry] = []
    ids: list[str] = []
    for i, doc_id in enumerate(all_data["ids"]):
        meta = all_data["metadatas"][i]
        entry = KnowledgeEntry(
            title=meta.get("title", ""),
            category=meta.get("category", "other"),
            problem=meta.get("problem", ""),
            solution=meta.get("solution", ""),
            related_issue_ids=(
                meta.get("related_issue_ids", "").split(",")
                if meta.get("related_issue_ids")
                else []
            ),
            tags=(
                meta.get("tags", "").split(",") if meta.get("tags") else []
            ),
        )
        entries.append(entry)
        ids.append(doc_id)

    # 2. 找出相似组（贪心聚类）
    merged_set: set[int] = set()
    clusters: list[list[int]] = []

    for i in range(len(entries)):
        if i in merged_set:
            continue
        cluster = [i]
        # 用第 i 条的文本做相似度搜索
        results = vectorstore.similarity_search_with_relevance_scores(
            entries[i].to_document_text(),
            k=min(10, total),
        )
        for doc, score in results:
            if score < settings.consolidation_similarity_threshold:
                continue
            # 找到对应的索引
            doc_id = doc.metadata.get("_id", "")
            for j in range(len(entries)):
                if j == i or j in merged_set:
                    continue
                if ids[j] == doc_id:
                    cluster.append(j)
                    merged_set.add(j)
                    break

        if len(cluster) > 1:
            merged_set.add(i)
            clusters.append(cluster)

    if not clusters:
        logger.info("没有发现需要合并的相似条目")
        return {"merged_groups": 0, "removed": 0, "final_count": total}

    logger.info(f"发现 {len(clusters)} 组相似条目，开始合并...")

    # 3. 合并每组
    new_entries: list[KnowledgeEntry] = []
    old_ids_to_delete: list[str] = []

    for cluster in clusters:
        # 从第一个开始，依次合并
        merged = entries[cluster[0]]
        for idx in cluster[1:]:
            merged = _merge_two_entries(merged, entries[idx])
        new_entries.append(merged)
        old_ids_to_delete.extend(ids[i] for i in cluster)

    # 4. 更新向量库：删旧写新
    collection.delete(ids=old_ids_to_delete)

    new_docs = []
    for entry in new_entries:
        new_docs.append(
            Document(
                page_content=entry.to_document_text(),
                metadata={
                    "title": entry.title,
                    "category": entry.category,
                    "problem": entry.problem,
                    "solution": entry.solution,
                    "related_issue_ids": ",".join(entry.related_issue_ids),
                    "tags": ",".join(entry.tags),
                    "type": "knowledge_entry",
                },
            )
        )
    vectorstore.add_documents(new_docs)

    final_count = total - len(old_ids_to_delete) + len(new_entries)
    report = {
        "merged_groups": len(clusters),
        "removed": len(old_ids_to_delete),
        "added": len(new_entries),
        "final_count": final_count,
    }
    logger.info(
        f"整合完成: {len(clusters)} 组合并，"
        f"删除 {len(old_ids_to_delete)} 条，新增 {len(new_entries)} 条，"
        f"当前总计 {final_count} 条"
    )
    return report
