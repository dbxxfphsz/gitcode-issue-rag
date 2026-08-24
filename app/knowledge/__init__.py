"""知识管理模块 - 从 Issue 中提取结构化知识，构建可搜索知识库。

核心能力：
  - 从 Bug/Usage 类 Issue 中提取问题-解决方案对
  - 将提取的知识存入向量库
  - 月度整合：合并相似知识条目，保持知识库精简
"""

from app.knowledge.knowledge import (
    KnowledgeEntry,
    extract_knowledge,
)
from app.knowledge.consolidation import consolidate_knowledge_base

__all__ = [
    "KnowledgeEntry",
    "extract_knowledge",
    "consolidate_knowledge_base",
]
