# 设计文档：Issue 相似性分析 Skill

## 1. 概述

本系统是一个**可被 Agent 直接调用的 Issue 相似性分析 Skill**，以标准 Skill 目录交付（说明文件 + 执行脚本 + 配置模板），无需部署独立服务。核心能力：

- 历史 Issue 知识库构建（文件型存储，不依赖外部数据库）
- 指定 Issue 相似性扫描与报告生成
- GitCode Issue 自动评论（带防重复标记）
- 知识库增量维护（游标追踪、断点续跑）
- 定时检测新 Issue
- 基于 Issue 数据生成 FAQ 文档（聚类合并、分类输出、草稿模式）

Agent 通过自然语言指令识别意图，映射到对应的执行脚本，支持理解 Issue 编号、Issue 链接和"当前 Issue"等上下文，不依赖固定指令格式。

## 2. 总体架构

### 2.1 架构图

```
Agent / 用户（自然语言指令）
    │  意图识别 → 指令映射（见 SKILL.md）
    ▼
┌──────────────────────────────────────────────────────┐
│                    scripts/（执行层）                  │
│  build_kb   scan_issue   add_issue   comment_issue   │
│  scan_new   generate_faq   kb_manage                 │
└───────────────────────┬──────────────────────────────┘
                        │ 调用
┌───────────────────────▼──────────────────────────────┐
│                    issue_kb/（核心层）                 │
│  config         全局配置（.env 驱动）                  │
│  gitcode_client GitCode v5 API 客户端                 │
│  knowledge      文件型知识库（CRUD + 游标 + 增量）      │
│  similarity     Embedding 缓存 + 余弦相似度搜索        │
│  report         Markdown 扫描报告生成                  │
│  commenter      GitCode 评论发布与去重                 │
│  faq            FAQ 聚类合并与文档生成                  │
└───────────────────────┬──────────────────────────────┘
                        │ 读写
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ GitCode API  │  │ issue-       │  │ docs/faq/    │
│ (Issue 读取/ │  │ knowledge-   │  │ (FAQ 文档)   │
│  评论发布)   │  │ base/ (数据) │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
```

### 2.2 分层职责

| 层次   | 职责                | 说明                                              |
| ------ | ------------------- | ------------------------------------------------- |
| 指令层 | 自然语言 → 脚本命令 | 由 SKILL.md 定义映射规则，Agent 负责解析          |
| 执行层 | 参数解析 + 流程编排 | 每个脚本对应一类用户意图，可独立运行              |
| 核心层 | 业务逻辑            | 纯 Python 模块，可被脚本或 Agent 直接调用         |
| 存储层 | 本地文件 + 远端 API | 数据全部落在本地目录，仅 Issue 读写走 GitCode API |

## 3. 核心模块设计

### 3.1 配置管理（config.py）

- 基于 `pydantic-settings`，字段与 `.env.example` 一一对应
- 模块级全局单例 `settings`，各模块统一引用
- 派生属性：`owner` / `repo_name`（拆分仓库地址）、`ignored_label_set`（解析忽略标签）、`api_prefix`（拼接 API 前缀）

关键配置项：

| 配置                              | 默认值                 | 说明                                                    |
| --------------------------------- | ---------------------- | ------------------------------------------------------- |
| `GITCODE_TOKEN`                   | 空                     | GitCode Token，评论功能必需；通过环境变量配置，不入仓库 |
| `GITCODE_REPO`                    | Ascend/msinsight       | 目标仓库                                                |
| `KB_DIR`                          | ./issue-knowledge-base | 知识库目录，所有中间数据与索引均在此                    |
| `FAQ_DIR`                         | ./docs/faq             | FAQ 输出目录                                            |
| `SIMILARITY_THRESHOLD`            | 0.75                   | 相似度阈值                                              |
| `SCAN_TOP_K`                      | 5                      | 扫描返回数量                                            |
| `SCAN_MODE`                       | report                 | 运行模式：`report` 仅生成报告 / `comment` 报告并评论    |
| `INCLUDE_CLOSED`                  | true                   | 是否检索已关闭 Issue                                    |
| `INCLUDE_COMMENTS`                | true                   | 是否包含评论内容参与匹配                                |
| `IGNORE_LABELS`                   | 空                     | 忽略的标签（逗号分隔），命中的 Issue 不参与扫描         |
| `EMBEDDING_MODEL` / `LLM_MODEL`   | -                      | Embedding 与 LLM 模型                                   |
| `CRAWL_PAGE_SIZE` / `CRAWL_DELAY` | 30 / 1.0               | 分页大小与请求间隔                                      |

### 3.2 GitCode 客户端（gitcode_client.py）

同步 `httpx` 封装，支持上下文管理器（`with GitCodeClient() as client`）：

| 方法                             | 功能                                                                      |
| -------------------------------- | ------------------------------------------------------------------------- |
| `fetch_all_issues(state, since)` | 分页拉取 Issue；`since` 为 ISO 时间戳，只返回此后更新的 Issue（增量基础） |
| `fetch_issue(number)`            | 获取单条 Issue 详情                                                       |
| `fetch_comments(number)`         | 分页获取 Issue 下所有评论                                                 |
| `post_comment(number, body)`     | 在 Issue 下发布评论                                                       |

- Token 通过 URL 参数 `access_token` 传递（GitCode v5 API 约定）
- 分页终止条件：返回空列表或单页不满 `CRAWL_PAGE_SIZE`
- 每页之间 sleep `CRAWL_DELAY`，避免触发限流

### 3.3 知识库管理（knowledge.py）

**数据标准化（IssueData）**：从 GitCode API 原始响应提取统一字段：

```
number / title / body / state / url / labels / author
created_at / updated_at / closed_at
comments_data       # 评论列表
kb_added_at / kb_updated_at   # 知识库时间戳
solution            # 自动提取的解决方案
```

**解决方案提取（启发式）**：

1. 优先在正文中查找"解决方案 / 解决方法 / solution / workaround / 已修复"等关键词，截取相关段落
2. 正文无命中时，从评论中倒序查找含"解决 / fix / close"等关键词的评论
3. 均无命中则 `solution` 为空字符串

**KnowledgeBase 管理器**：

| 能力       | 方法                                                        |
| ---------- | ----------------------------------------------------------- |
| Issue CRUD | `get_issue` / `save_issue` / `delete_issue` / `list_issues` |
| 批量写入   | `save_issues_batch`（返回新增/更新计数）                    |
| 游标管理   | `get_cursor` / `set_cursor`                                 |
| 已处理追踪 | `get_processed_ids` / `mark_processed`                      |
| 统计       | `get_stats`（总数、状态分布、标签、游标、时间）             |
| 全量重建   | `rebuild`（清空 issues/ 与 embeddings.json）                |

保存逻辑：更新时保留原 `kb_added_at` 并刷新 `kb_updated_at`；新增时同时写入两者。

### 3.4 相似性引擎（similarity.py）

**查询文本构建（\_build_issue_text）**：匹配依据覆盖标题（重复一次提高权重）、问题描述、标签、解决方案、前 3 条评论摘要，以换行拼接后送 Embedding。

**索引管理（SimilarityEngine）**：

- Embedding 以 `{issue_number: vector}` 形式缓存在 `embeddings.json`
- `ensure_index`：增量构建，已有向量的 issue 直接跳过（成功部分不重复构建），返回新增/跳过/失败统计；`build_kb` 使用此方法，并对内容更新的 issue 先移除旧向量再重算，避免用旧向量检索；`kb_manage reindex` 使用 `rebuild_index` 全量重建
- `update_embedding`：单条增量更新（添加/更新 Issue 时使用）
- `search`：对查询文本计算向量，与索引中所有向量计算余弦相似度，按分数降序返回；`exclude_number` 参数排除当前 Issue，避免自匹配

**Embedding 构建的容错设计**：

- 按批调用 API（默认 10 条/批），单批失败不中断整体流程，继续处理后续批次，并记录失败批次包含的 issue 编号
- 全部批次处理完后，对失败项在最后统一重试一轮；仍失败的编号输出到日志，重新运行构建命令即可自动补齐（因为它们不在索引中，会被 `ensure_index` 识别为待处理）
- 每批成功后立即落盘 `embeddings.json`，中断后重新运行只需补齐未完成部分，成功部分不重复构建

**相似度计算**：`numpy` 余弦相似度（点积 / 模长之积，加 `1e-10` 防除零）。知识库规模在千级，全量遍历无性能压力。

### 3.5 报告生成（report.py）

`generate_scan_report` 输出 Markdown 报告，内容包含：

- 目标 Issue 信息（编号、标题、状态、链接、标签）
- 相似 Issue 列表：相似度（百分比）、状态（带标记图标）、链接、标签、历史解决方案摘要
- 无相似结果时明确提示"可能是一个新问题"
- 结尾声明：**结果仅作为相似问题参考，不直接判定 Issue 重复**

评论防重复机制：

- `generate_comment_body`：评论内容头部注入固定标记 `<!-- issue-skill-scan-report:v1:issue-{number} -->`（HTML 注释，不影响可读性）
- `has_existing_comment`：发布前扫描已有评论中是否存在该标记，存在则跳过

### 3.6 评论管理（commenter.py）

`IssueCommenter.post_scan_report(issue_number, report, force)`：

1. 未配置 `GITCODE_TOKEN` 时警告并跳过（只读场景可无 Token）
2. 非 force 模式下，先检查是否已存在带标记的评论，存在则跳过（避免重复发布相同评论）
3. 包装评论内容（加防重复标记）后发布
4. 发布失败捕获异常，仅记录错误

### 3.7 FAQ 生成（faq.py）

**处理流程**：

```
知识库全部 Issue
    │ 筛选：state == closed 且 solution 非空
    ▼
按分类分组（标签推断：安装/导入/Timeline/NUMA/性能等，未知归"其他"）
    │ 可按 --category 只处理指定分类
    ▼
组内相似聚类（贪心：逐条用 embedding 搜索，相似度 ≥ 0.85 归入同簇）
    │ 避免同类问题重复生成多条 FAQ
    ▼
渲染 Markdown（问题现象 / 适用版本 / 可能原因 / 解决方法 / 关联 Issue 链接）
    │
    ▼
写入 docs/faq/{分类}.md
```

**关键特性**：

- 每条 FAQ 保留全部关联 Issue 编号与链接，可追溯
- 默认生成**待审核草稿**（文件名带 `_draft` 后缀），`--no-draft` 生成正式版
- 支持三种模式：全量生成 / 增量更新（`--incremental`）/ 指定 Issue 生成（`--issue`）
- Issue 解决方案变化后重新生成会覆盖同名文件，不产生重复条目

## 4. 脚本接口（执行层）

| 脚本               | 功能             | 关键参数                                                                                |
| ------------------ | ---------------- | --------------------------------------------------------------------------------------- |
| `build_kb.py`      | 构建知识库       | `--fresh` 清空重建；`--incremental` 增量更新（默认全量）                                |
| `scan_issue.py`    | 扫描指定 Issue   | `--issue` 编号/#编号/URL；`--title/--body` 手动输入；`--top-k`；`--mode report/comment` |
| `add_issue.py`     | 添加 Issue       | `--issue` 从 GitCode 拉取；`--with-comments`；`--manual --title --body --labels`        |
| `comment_issue.py` | 扫描并评论       | `--issue`（必填）；`--force` 忽略已有评论                                               |
| `scan_new.py`      | 增量扫描新 Issue | `--mode report/comment`；`--status` 查看运行状态                                        |
| `generate_faq.py`  | 生成 FAQ         | `--category`；`--issue`；`--incremental`；`--no-draft`                                  |
| `kb_manage.py`     | 知识库管理       | `status` / `delete <编号>` / `reindex` / `rebuild`                                      |

所有脚本通过 `sys.path.insert` 保证从任意工作目录可正确导入 `issue_kb` 包。

## 5. 数据存储设计

所有中间数据和索引保存在知识库目录中，不依赖外部数据库服务：

```
issue-knowledge-base/
├── issues/                  # 每条 Issue 一个 JSON 文件（标准化数据）
│   ├── 123.json
│   └── 456.json
├── embeddings.json          # Embedding 索引：{issue_number: vector}
├── metadata.json            # 游标、已处理列表、统计、更新时间
└── reports/                 # 扫描报告
    └── scan_123.md

docs/faq/                    # FAQ 输出（草稿/正式版）
├── 安装_draft.md
└── Timeline_draft.md
```

`metadata.json` 结构：

```json
{
  "scan_cursor": "2026-08-27T03:00:00+00:00",
  "last_scan_at": "2026-08-27T03:00:00+00:00",
  "last_kb_build_at": null,
  "processed_issues": [123, 456],
  "total_issues": 2
}
```

## 6. 核心流程设计

### 6.1 知识库构建流程（build_kb）

```
[首次] fetch_all_issues(全量) ──┐
[增量] 读取游标 → since 过滤 ───┤
                                ▼
        过滤含忽略标签的 Issue
                                ▼
        IssueData 标准化（含解决方案提取）
                                ▼
        批量保存（新增/更新区分）→ 更新游标；更新的 issue 移除旧向量
                                ▼
        增量构建 embedding 索引（跳过已索引，失败批次记录并在最后重试）
```

- 首次运行读取仓库全部 Issue（含已关闭）；增量模式仅拉取游标之后更新的
- 已存在的 Issue 自动更新标题、正文、状态、评论和解决方案

### 6.2 相似性扫描流程（scan_issue）

```
解析 Issue 引用（编号 / #编号 / URL）
    ▼
获取目标 Issue：优先本地知识库，未命中则从 GitCode 拉取
    ▼
构建查询文本 → 计算查询向量
    ▼
余弦相似度搜索（排除自身，按分数排序取 top-k）
    ▼
补充相似 Issue 详情（状态、链接、解决方案）
    ▼
生成 Markdown 报告 → 输出到终端 + 保存到 reports/
    ▼
comment 模式：检查防重复标记 → 发布评论到 Issue
```

### 6.3 定时扫描新 Issue 流程（scan_new）

```
读取游标（无游标则以 7 天前为起点）
    ▼
fetch_all_issues(since=游标) → 过滤已处理集合
    ▼
逐条处理（单条失败记录错误，继续处理其他）：
    标准化 → 保存知识库 → 更新 embedding
    → 相似性搜索 → 生成报告 → 保存
    → [comment 模式] 发布评论
    → 标记已处理
    ▼
更新游标
```

**可靠性保证**：

- **断点续跑**：游标 + 已处理 Issue 集合双保险，中断后重启不重复处理
- **不重复评论**：评论带固定标记，发布前检查
- **故障隔离**：单条 Issue 处理异常只记录日志，不影响其余

定时调度由 Agent 或系统 cron 触发 `python -m scripts.scan_new --mode comment`（如 `crontab` 每日执行一次），暂停即移除定时任务，恢复即重新添加。

### 6.4 FAQ 生成流程（generate_faq）

见 3.7 节流程图。增量模式下仅处理知识库中近期新增/更新的已解决 Issue；解决方案变化时重新生成会覆盖对应分类文件。

## 7. 自然语言指令映射

| 用户指令示例                                 | 执行命令                                                     |
| -------------------------------------------- | ------------------------------------------------------------ |
| "基于历史 Issue 初始化知识库"                | `python -m scripts.build_kb`                                 |
| "同步最新 Issue 到知识库"                    | `python -m scripts.build_kb --incremental`                   |
| "重新构建 Issue 知识库"                      | `python -m scripts.build_kb --fresh`                         |
| "把这个 Issue 加入知识库"                    | `python -m scripts.add_issue --issue <编号>`                 |
| "扫描这个 Issue，看看是否有类似问题"         | `python -m scripts.scan_issue --issue <编号>`                |
| "查找与 Issue 123 最相似的 5 个历史问题"     | `python -m scripts.scan_issue --issue 123 --top-k 5`         |
| "扫描这个 Issue，但只生成报告，不发布评论"   | `python -m scripts.scan_issue --issue <编号> --mode report`  |
| "扫描完成后，把报告评论到当前 Issue"         | `python -m scripts.comment_issue --issue <编号>`             |
| "每天扫描新提交的 Issue，并自动评论相似问题" | 创建定时任务执行 `python -m scripts.scan_new --mode comment` |
| "查看定时扫描任务的运行状态"                 | `python -m scripts.scan_new --status`                        |
| "暂停/恢复新 Issue 定时扫描任务"             | 移除/添加对应的定时任务                                      |
| "基于历史 Issue 生成 FAQ 文档"               | `python -m scripts.generate_faq`                             |
| "把这个 Issue 整理成一条 FAQ"                | `python -m scripts.generate_faq --issue <编号>`              |
| "根据最近解决的 Issue 增量更新 FAQ"          | `python -m scripts.generate_faq --incremental`               |
| "更新 Timeline 分类的 FAQ"                   | `python -m scripts.generate_faq --category Timeline`         |
| "查看知识库状态"                             | `python -m scripts.kb_manage status`                         |

上下文理解规则：

- **Issue 编号**：纯数字（`123`）、带井号（`#123`）均可识别
- **Issue 链接**：从 `.../issues/{number}` 形式的 URL 中提取编号
- **当前 Issue**：由 Agent 结合对话上下文（正在讨论的 Issue）解析出编号后传入

## 8. 关键设计决策

| 决策点     | 选择                            | 理由                                       |
| ---------- | ------------------------------- | ------------------------------------------ |
| 交付形态   | Skill 目录 + 脚本               | Agent 可直接调用，无需部署和维护独立服务   |
| 存储方案   | 文件型 JSON（每 Issue 一文件）  | 无外部数据库依赖；便于查看、备份、版本管理 |
| Embedding  | 直调 OpenAI 兼容 API + 本地缓存 | 索引构建一次、多次复用，避免重复计费       |
| 相似度计算 | numpy 余弦相似度全量遍历        | 千级数据规模下简单可靠，无额外索引依赖     |
| 增量机制   | 时间游标 + 已处理 ID 集合       | 双保险支持断点续跑，防止重复扫描和评论     |
| 评论防重复 | HTML 注释固定标记               | 对用户不可见，检查成本低，跨运行稳定       |
| 匹配依据   | 标题加权 + 正文 + 标签 + 评论   | 多维度拼接后整体向量化，兼顾语义与关键词   |
| FAQ 模式   | 默认草稿 + 聚类合并             | 人工审核后再发布，聚类避免同类问题重复成条 |
| 故障处理   | 单条失败记录并跳过              | 保证批量任务不因个别 Issue 中断            |
| Token 管理 | 环境变量（.env）                | 不入代码仓库，只读扫描场景可缺省           |

## 9. 项目目录结构

```
gitcode-issue-rag/
├── issue_kb/                    # 核心模块
│   ├── __init__.py
│   ├── config.py                # 配置管理（.env）
│   ├── gitcode_client.py        # GitCode API 客户端
│   ├── knowledge.py             # 文件型知识库管理
│   ├── similarity.py            # Embedding + 余弦相似度
│   ├── report.py                # Markdown 报告生成
│   ├── commenter.py             # GitCode 评论管理
│   └── faq.py                   # FAQ 文档生成
├── scripts/                     # 可执行脚本
│   ├── build_kb.py              # 构建知识库
│   ├── scan_issue.py            # 扫描 Issue
│   ├── add_issue.py             # 添加 Issue
│   ├── comment_issue.py         # 评论 Issue
│   ├── scan_new.py              # 增量扫描新 Issue
│   ├── generate_faq.py          # 生成 FAQ
│   └── kb_manage.py             # 知识库管理
├── issue-knowledge-base/        # 知识库数据（运行后生成，不入 Git）
├── docs/faq/                    # FAQ 输出（运行后生成，不入 Git）
├── SKILL.md                     # Agent Skill 说明（触发条件与操作指南）
├── DESIGN.md                    # 本文档
├── README.md                    # 快速开始
├── .env.example                 # 配置模板
└── pyproject.toml               # 依赖与打包配置
```
