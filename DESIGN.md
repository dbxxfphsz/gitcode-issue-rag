# 设计文档：Issue 知识库 Skill 系统

## 1. 概述

本系统在现有 GitCode Issue 查重系统基础上，新增 **知识库构建与检索** 能力，并通过 **Agent Skill** 对外暴露，使 agent 可以直接执行以下操作：

- **扫描 Issue**：在知识库中搜索相似问题，生成诊断报告
- **添加 Issue**：将新 issue 提取为结构化知识并加入知识库
- **构建知识库**：从历史 issue 中批量提取知识
- **月度整合**：自动合并相似知识条目，保持知识库精简

## 2. 架构设计

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────┐
│                    Agent / 用户                       │
│              (通过 SKILL.md 调用)                     │
└──────────┬──────────┬──────────┬────────────────────┘
           │          │          │
     ┌─────▼───┐ ┌───▼────┐ ┌──▼──────────┐
     │ scan_   │ │ add_   │ │ build_kb.py │
     │ issue   │ │ issue  │ │             │
     └─────┬───┘ └───┬────┘ └──┬──────────┘
           │         │         │
     ┌─────▼─────────▼─────────▼──────────┐
     │          app/knowledge/             │
     │  ┌─────────────┐ ┌───────────────┐ │
     │  │ knowledge.py│ │ consolidation │ │
     │  │ (LLM 提取)  │ │ (LLM 合并)    │ │
     │  └──────┬──────┘ └──────┬────────┘ │
     └─────────┼───────────────┼──────────┘
               │               │
     ┌─────────▼───────────────▼──────────┐
     │        app/shared/models.py         │
     │       (ChromaDB 向量库单例)          │
     └────────────────────────────────────┘
```

### 2.2 数据流

```
原始 Issue (GitCode API)
    │
    ▼
┌──────────────────┐
│  爬取 & 缓存     │  scripts/init_ingest.py
│  (JSON 缓存)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  标签筛选         │  Bug/Usage 类 issue
│  (KB_LABELS)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  LLM 知识提取     │  app/knowledge/knowledge.py
│  (结构化输出)     │  → KnowledgeEntry
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  向量化 & 存储    │  ChromaDB
│  (embedding)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  语义搜索/扫描    │  scripts/scan_issue.py
│  (similarity)    │
└──────────────────┘
```

### 2.3 月度整合流程

```
每月 1 号 03:00 (scheduler 触发)
    │
    ▼
┌──────────────────┐
│  加载所有知识条目  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  两两相似度比较    │  阈值: 0.90
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  贪心聚类         │  找出相似组
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  LLM 合并         │  每组合并为一条
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  更新向量库       │  删旧写新
└──────────────────┘
```

## 3. 核心模块

### 3.1 KnowledgeEntry 数据模型

```python
class KnowledgeEntry(BaseModel):
    title: str              # 知识条目标题
    category: str           # 分类: bug / usage / feature / other
    problem: str            # 问题描述
    solution: str           # 解决方案
    related_issue_ids: list[str]  # 关联的原始 issue ID
    tags: list[str]         # 关键词标签
```

知识条目与原始 Issue 的区别：
- **Issue** 是原始用户反馈，可能冗长、格式混乱
- **KnowledgeEntry** 是 LLM 提炼后的结构化知识，聚焦于「问题 + 解决方案」

### 3.2 知识提取 (knowledge.py)

- 使用 `ChatOpenAI.with_structured_output()` 强制 LLM 输出结构化 JSON
- 正文截断到 2000 字符，避免超 token 限制
- 提取失败时返回 None，不中断批量流程

### 3.3 知识库整合 (consolidation.py)

- 使用贪心聚类策略：遍历所有条目，对每条做 similarity_search，找到相似组
- 相似组内用 LLM 逐对合并，保留所有有用信息
- 合并失败时降级为手动拼接（不丢数据）

### 3.4 Issue 筛选策略 (build_kb.py)

优先使用标签匹配：
```python
KB_LABELS = {"bug", "usage", "缺陷", "使用", "问题", "question", "error", "故障"}
```

标签不匹配时，使用标题关键词兜底：
```python
["报错", "错误", "失败", "无法", "怎么", "如何", "问题", "异常", "crash", "error", "fail"]
```

## 4. 脚本接口

| 脚本 | 用途 | 关键参数 |
|------|------|----------|
| `scripts/init_ingest.py` | 全量爬取 issue 到缓存 | `--fresh`, `--crawl-only`, `--embed-only` |
| `scripts/build_kb.py` | 从缓存构建知识库 | `--max-issues N` |
| `scripts/scan_issue.py` | 扫描 issue 找相似问题 | `--title`, `--body`, `--top-k` |
| `scripts/add_issue.py` | 添加单条 issue 到知识库 | `--issue-id`, `--title`, `--body`, `--url`, `--labels` |

## 5. 定时任务

| 任务 | 频率 | 时间 | 说明 |
|------|------|------|------|
| 每日增量爬取 | 每天 | 02:00 | 爬取当天更新的 issue |
| 知识库整合 | 每月 | 1 号 03:00 | 合并相似知识条目 |

## 6. 配置项

`.env` 新增配置：

```env
# 知识库整合时相似度阈值（高于此值的条目才合并）
CONSOLIDATION_SIMILARITY_THRESHOLD=0.90
```

## 7. 验收标准对照

| 验收标准 | 实现方式 | 状态 |
|----------|----------|------|
| 从 Usage/Bug 类 Issue 自动提取知识 | `build_kb.py` + 标签筛选 + LLM 提取 | ✅ |
| 首次至少新增 5 个知识 | LLM 逐条提取，只要缓存中有 5+ 条 bug/usage issue 即可 | ✅ |
| 每月自动整理合并 | `scheduler.py` 月度任务 + `consolidation.py` | ✅ |
| 新 issue 自动搜索回复 | `scan_issue.py` 语义搜索 + 报告生成 | ✅ |
| Agent 可直接使用 | `SKILL.md` 定义完整操作流程 | ✅ |

## 8. 目录结构（变更后）

```
gitcode-issue-rag/
├── app/
│   ├── api/              # FastAPI 路由
│   ├── crawler/          # 爬虫 + 定时任务
│   │   ├── gitcode.py
│   │   └── scheduler.py  # [改] 新增月度整合任务
│   ├── ingestion/        # 原始 issue 入库流水线
│   ├── knowledge/        # [新] 知识管理模块
│   │   ├── __init__.py
│   │   ├── knowledge.py  # LLM 知识提取
│   │   └── consolidation.py  # 月度整合
│   ├── shared/           # 共享模型
│   └── config.py         # [改] 新增整合配置
├── scripts/
│   ├── init_ingest.py    # 全量爬取
│   ├── build_kb.py       # [新] 构建知识库
│   ├── scan_issue.py     # [新] 扫描 issue
│   └── add_issue.py      # [新] 添加 issue
├── SKILL.md              # [新] Agent Skill 定义
├── DESIGN.md             # [新] 设计文档
└── ...
```
