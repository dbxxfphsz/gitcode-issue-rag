"""应用启动入口 - 同时启动 FastAPI 服务和定时任务。

启动方式：
    cd gitcode-issue-rag
    python -m main

    或者用 uvicorn 直接启动（适合生产）：
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from loguru import logger

from app.config import settings
from app.api.routes import router
from app.crawler.scheduler import create_scheduler


# ---- 生命周期管理 ----
# FastAPI 的 lifespan 在应用启动时运行，关闭时清理
# 类比前端：类似 React 组件的 useEffect + cleanup


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化定时任务，关闭时清理资源。"""
    # === 启动阶段 ===
    logger.info("GitCode Issue RAG 服务启动中...")

    scheduler = create_scheduler()
    scheduler.start()
    logger.info("定时任务调度器已启动")

    yield  # 应用运行中

    # === 关闭阶段 ===
    scheduler.shutdown(wait=False)
    logger.info("服务已关闭")


# ---- FastAPI 实例 ----
app = FastAPI(
    title="GitCode Issue 查重服务",
    description=(
        "基于 RAG 的 Issue 查重系统。\n\n"
        "核心接口：POST /api/check-duplicate — 检查新 issue 是否已有相同问题"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# 注册路由
app.include_router(router)


# ---- 直接运行入口 ----
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,  # 开发模式，文件变更自动重启
    )
