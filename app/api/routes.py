"""FastAPI 路由 - 对外提供 Issue 查重接口。

接口设计：
  POST /api/check-duplicate  — 检查新 issue 是否已有相同问题
  POST /api/ingest           — 手动触发增量爬取入库（管理用）
  GET  /api/health           — 健康检查
  GET  /api/stats            — 查看知识库统计信息
"""

from fastapi import APIRouter
from pydantic import BaseModel
from loguru import logger

from app.ingestion import ingest_issues, get_existing_issue_ids
from app.ingestion.dedup import check_duplicate, DedupResult
from app.crawler.gitcode import GitCodeCrawler
from app.shared.models import get_vectorstore

router = APIRouter(prefix="/api")


# ==================== 请求/响应模型 ====================


class CheckRequest(BaseModel):
    """查重请求。"""

    title: str  # issue 标题
    body: str = ""  # issue 正文（可选，但建议提供以提高准确度）


class CheckResponse(BaseModel):
    """查重响应 - 对应你要求的两个返回值。"""

    is_duplicate: bool  # 是否重复
    duplicate_url: str | None = None  # 重复的 issue 链接
    similarity: float = 0.0  # 相似度分数（供参考）
    matched_title: str | None = None  # 匹配到的已有 issue 标题


class IngestResponse(BaseModel):
    """入库结果。"""

    success: bool
    message: str
    new_count: int = 0  # 新增入库的 issue 数量


class StatsResponse(BaseModel):
    """知识库统计。"""

    total_chunks: int  # 向量库中的文档块总数
    unique_issues: int  # 去重后的 issue 数量


# ==================== 路由 ====================


@router.post("/check-duplicate", response_model=CheckResponse)
async def api_check_duplicate(req: CheckRequest):
    """检查新 issue 是否与知识库中已有问题重复。

    示例请求：
    ```json
    {
        "title": "Timeline 不支持 MODEL_EXECUTE 跳转",
        "body": "在多子图场景下，无法从 MODEL_EXECUTE 定位到关联 Stream..."
    }
    ```

    示例响应（重复）：
    ```json
    {
        "is_duplicate": true,
        "duplicate_url": "https://gitcode.com/Ascend/msinsight/issues/500",
        "similarity": 0.9234,
        "matched_title": "[Feature]: Timeline 支持 MODEL_EXECUTE 跳转并高亮对应 Stream 泳道"
    }
    ```
    """
    query_text = f"标题: {req.title}\n问题描述: {req.body}"
    result: DedupResult = check_duplicate(query_text)

    logger.info(
        f"查重请求: title='{req.title[:30]}...', "
        f"结果: duplicate={result.is_duplicate}, score={result.similarity}"
    )

    return CheckResponse(
        is_duplicate=result.is_duplicate,
        duplicate_url=result.duplicate_url,
        similarity=result.similarity,
        matched_title=result.matched_title,
    )


@router.post("/ingest", response_model=IngestResponse)
async def api_ingest():
    """手动触发一次增量爬取入库。

    定时任务会自动调用，这个接口用于手动触发（比如初始化或调试时）。
    """
    crawler = GitCodeCrawler()

    try:
        # 获取今天的 issue（增量）
        issues = await crawler.fetch_today_issues()

        # 过滤已入库的
        existing_ids = get_existing_issue_ids()
        new_issues = [i for i in issues if i.issue_id not in existing_ids]

        if not new_issues:
            return IngestResponse(
                success=True,
                message="没有新的 issue 需要入库",
                new_count=0,
            )

        chunk_count = ingest_issues(new_issues)
        return IngestResponse(
            success=True,
            message=f"入库完成：{len(new_issues)} 条新 issue，{chunk_count} 个文档块",
            new_count=len(new_issues),
        )
    except Exception as e:
        logger.exception("入库失败")
        return IngestResponse(success=False, message=f"入库失败: {str(e)}")


@router.get("/health")
async def api_health():
    """健康检查接口。"""
    return {"status": "ok"}


@router.get("/stats", response_model=StatsResponse)
async def api_stats():
    """查看知识库统计信息。"""
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    total = collection.count()
    issue_ids = get_existing_issue_ids()

    return StatsResponse(
        total_chunks=total,
        unique_issues=len(issue_ids),
    )
