"""全局配置 - 从 .env 读取，所有模块通过 settings 访问。"""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Skill 配置，字段与 .env.example 一一对应。"""

    # --- GitCode ---
    gitcode_token: str = ""
    gitcode_repo: str = "Ascend/msinsight"
    gitcode_base_url: str = "https://gitcode.com"

    # --- LLM / Embedding ---
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"

    # --- 知识库 ---
    kb_dir: str = "./issue-knowledge-base"

    # --- 相似性扫描 ---
    similarity_threshold: float = 0.75
    scan_top_k: int = 5
    scan_mode: str = "report"  # report | comment
    include_closed: bool = True
    include_comments: bool = True
    ignore_labels: str = ""  # 逗号分隔，如 "wontfix,duplicate"

    # --- FAQ ---
    faq_dir: str = "./docs/faq"

    # --- 爬取 ---
    crawl_page_size: int = 30
    crawl_delay: float = 1.0

    @property
    def owner(self) -> str:
        return self.gitcode_repo.split("/")[0]

    @property
    def repo_name(self) -> str:
        return self.gitcode_repo.split("/")[1]

    @property
    def kb_path(self) -> Path:
        return Path(self.kb_dir)

    @property
    def faq_path(self) -> Path:
        return Path(self.faq_dir)

    @property
    def ignored_label_set(self) -> set[str]:
        if not self.ignore_labels:
            return set()
        return {label.strip().lower() for label in self.ignore_labels.split(",")}

    @property
    def api_prefix(self) -> str:
        return f"{self.gitcode_base_url}/api/v5"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
