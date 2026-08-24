"""知识提取 - 用 LLM 从 Issue 中提取结构化知识条目。

将原始 Issue（标题 + 正文）转化为结构化的「问题-解决方案」知识条目，
存入向量库后可被语义搜索。

类比前端：类似从用户反馈中提取 FAQ 条目，方便后续搜索匹配。
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import BaseModel, Field

from app.config import settings
from app.shared.schemas import Issue


class KnowledgeEntry(BaseModel):
    """从 Issue 中提取的结构化知识条目。"""

    title: str = Field(description="知识条目标题，简明概括问题")
    category: str = Field(description="分类: bug / usage / feature / other")
    problem: str = Field(description="问题描述")
    solution: str = Field(description="解决方案或变通方法，没有则为空字符串")
    related_issue_ids: list[str] = Field(
        default_factory=list, description="关联的 issue ID 列表"
    )
    tags: list[str] = Field(default_factory=list, description="关键词标签")

    def to_document_text(self) -> str:
        """将知识条目拼成适合 embedding 的文本。

        标题重复出现以提高权重，类似 SEO 做法。
        """
        parts = [
            f"标题: {self.title}",
            f"标题: {self.title}",  # 重复以提高权重
            f"分类: {self.category}",
            f"问题: {self.problem}",
        ]
        if self.solution:
            parts.append(f"解决方案: {self.solution}")
        if self.tags:
            parts.append(f"标签: {', '.join(self.tags)}")
        return "\n".join(parts)


# ---- LLM 提取 Prompt ----

_EXTRACTION_PROMPT = ChatPromptTemplate.from_template(
    """你是一个技术知识库管理员。请从以下 Issue 中提取一条结构化知识条目。

Issue 标题: {title}
Issue 正文:
{body}

请提取：
1. title: 简明概括这个知识点的标题
2. category: 分类（bug / usage / feature / other）
3. problem: 问题的详细描述
4. solution: 解决方案或变通方法（如果 Issue 中有提到的话，没有则留空字符串）
5. tags: 3-5 个关键词标签
""",
)


def extract_knowledge(issue: Issue) -> KnowledgeEntry | None:
    """从一条 Issue 中提取结构化知识。

    使用 LLM 解析 issue 内容，提取出「问题-解决方案」对。
    如果 issue 不包含有价值的知识（如纯闲聊），返回 None。

    Args:
        issue: 要提取的 Issue

    Returns:
        提取的知识条目，或 None（无法提取时）
    """
    llm = ChatOpenAI(
        model=settings.llm_model,
        openai_api_key=settings.openai_api_key,
        openai_api_base=settings.openai_api_base,
        temperature=0,
    )

    structured_llm = llm.with_structured_output(KnowledgeEntry)

    try:
        entry = structured_llm.invoke(
            _EXTRACTION_PROMPT.format(
                title=issue.title,
                body=issue.body[:2000],  # 截断过长正文，避免超 token
            )
        )
        # 关联原始 issue ID
        entry.related_issue_ids = [issue.issue_id]
        return entry
    except Exception as e:
        logger.warning(f"从 {issue.issue_id} 提取知识失败: {e}")
        return None
