"""全局配置 - 从 .env 文件读取，提供类型安全的配置访问。"""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置，字段与 .env.example 一一对应。"""

    # --- LLM ---
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"

    # --- GitCode ---
    gitcode_repo: str = "Ascend/msinsight"
    gitcode_base_url: str = "https://gitcode.com"
    crawl_page_size: int = 20
    crawl_delay: float = 1.0

    # --- 向量库 ---
    chroma_persist_dir: str = "./data/chroma_db"
    chroma_collection_name: str = "gitcode_issues"

    # --- 查重 ---
    dedup_similarity_threshold: float = 0.85
    dedup_top_k: int = 3

    # --- 定时任务 ---
    cron_hour: int = 2
    cron_minute: int = 0

    # --- 服务 ---
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def repo_issues_url(self) -> str:
        """拼出 issue 列表的完整 URL。"""
        return f"{self.gitcode_base_url}/{self.gitcode_repo}/issues"

    @property
    def chroma_persist_path(self) -> Path:
        return Path(self.chroma_persist_dir)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# 全局单例，其他模块直接 from app.config import settings
settings = Settings()
