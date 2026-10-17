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

    # --- 模板清洗（LLM 语义判定）---
    # 录入/扫描时剔除 Issue body 中的无意义模板噪声（客套话/提交须知/安全提醒等），
    # 保留有助阅读的结构标题与用户内容。频率仅用于预筛候选行，remove/keep 由 LLM 判定。
    clean_template: bool = True
    # 频率预筛阈值：一行出现在 >= 该数量 Issue 中才作为 LLM 候选（只针对重复噪声，
    # 只出现一次的独特内容直接保留、不调 LLM，以控制成本）
    template_min_support: int = 3
    # 规范化后最小行长度：短于此的行不判定、直接保留（避免"无""1."等浪费 LLM 调用）
    template_min_line_len: int = 4
    # 每次 LLM 调用判定的行数（分批送审）
    template_llm_batch: int = 40

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
    def template_cache_file(self) -> Path:
        return self.kb_path / "llm_template_cache.json"

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


# --------------- 多仓库支持 ---------------

def resolve_kb_dir(repo: str | None = None) -> Path:
    """根据仓库名解析知识库目录。

    - 未指定 repo 或与 .env 默认值相同：返回 settings.kb_path（向后兼容）
    - 指定了不同仓库：返回 settings.kb_path 同级目录下的 {kb_dir_name}-{owner}_{repo}/

    示例：
        resolve_kb_dir(None)              → ./issue-knowledge-base/
        resolve_kb_dir("Ascend/msinsight") → ./issue-knowledge-base/  (默认仓库)
        resolve_kb_dir("Ascend/CANN")      → ./issue-knowledge-base-Ascend_CANN/
    """
    if repo is None or repo == settings.gitcode_repo:
        return settings.kb_path
    # 非默认仓库：在同级目录下创建独立的知识库
    suffix = repo.replace("/", "_")
    base = settings.kb_path
    return base.parent / f"{base.name}-{suffix}"


def apply_repo_override(repo: str | None):
    """运行时覆盖 settings 中的仓库和知识库目录。

    所有脚本在解析 --repo 参数后调用此函数，后续模块自动使用新配置。
    """
    if repo is None:
        return
    settings.gitcode_repo = repo
    settings.kb_dir = str(resolve_kb_dir(repo))
