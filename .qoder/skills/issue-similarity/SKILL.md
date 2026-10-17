---
name: issue-similarity
description: 当用户需要扫描 GitCode Issue 的相似历史问题、把 Issue 加入知识库、定时扫描并评论新 Issue、或基于历史 Issue 生成 FAQ 文档时使用。触发语如“扫描这个 Issue 看有没有类似问题”“把这个 Issue 加入知识库”“每天定时扫描新 Issue 并评论相似问题”“基于历史 Issue 生成 FAQ”“查看知识库状态”。支持任意 gitcode.com 仓库。
---

# Issue 相似性分析 Skill

提供 Issue 知识库管理、相似问题检索、扫描报告生成、GitCode 评论发布和 FAQ 文档生成能力。Agent 通过自然语言指令直接调用。

支持任意 `https://gitcode.com` 上的仓库，默认仓库为 `Ascend/msinsight`。

## 触发条件

- “扫描这个 Issue，看看是否有类似问题”
- “把这个 Issue 加入知识库”
- “每天定时扫描新 Issue，并评论相似问题”
- “基于历史 Issue 生成 FAQ 文档”
- “查看知识库状态”

## ❗ 重要：仓库确认（Agent 必须执行）

**当用户触发本 Skill 时，如果用户未明确指定仓库，Agent 必须先反问用户：**

> “请确认要操作哪个 GitCode 仓库？默认为 `Ascend/msinsight`，如果是其他仓库请提供 `owner/repo` 格式的地址（例如 `Ascend/CANN`、`openEuler/community`）。”

如果用户确认使用默认仓库或未回复，则不加 `--repo` 参数（向后兼容）。
如果用户指定了其他仓库，则所有命令加上 `--repo owner/repo`。

**示例：**
```bash
# 默认仓库（Ascend/msinsight）
python -m scripts.scan_issue --issue 123

# 指定其他仓库
python -m scripts.scan_issue --issue 456 --repo Ascend/CANN
python -m scripts.build_kb --repo openEuler/community
```

每个仓库拥有独立的知识库目录，互不干扰：
- 默认仓库：`issue-knowledge-base/`
- 其他仓库：`issue-knowledge-base-{owner}_{repo}/`（自动创建）

## 前置条件

1. `.env` 已配置（API Key、GitCode Token）
2. 依赖已安装：`pip install -e .`
3. 知识库已构建：`python -m scripts.build_kb`

## 操作指南

### 1. 知识库管理

**初始化/重建知识库：**

```bash
python -m scripts.build_kb                          # 全量构建（默认仓库）
python -m scripts.build_kb --fresh                   # 清空后重建
python -m scripts.build_kb --incremental             # 增量更新
python -m scripts.build_kb --repo Ascend/CANN        # 构建其他仓库的知识库
```

**同步最新 Issue：**

```bash
python -m scripts.build_kb --incremental
```

**查看状态：**

```bash
python -m scripts.kb_manage status
python -m scripts.kb_manage status --repo Ascend/CANN   # 查看其他仓库的知识库
```

**删除/重建索引：**

```bash
python -m scripts.kb_manage delete 123   # 删除指定 Issue
python -m scripts.kb_manage reindex      # 重建 embedding 索引
python -m scripts.kb_manage rebuild      # 清空知识库
```

### 2. 相似问题扫描

**扫描指定 Issue：**

```bash
python -m scripts.scan_issue --issue 123
python -m scripts.scan_issue --issue 123 --top-k 5
python -m scripts.scan_issue --issue 789 --repo Ascend/CANN   # 扫描其他仓库
```

**仅生成报告（不评论）：**

```bash
python -m scripts.scan_issue --issue 123 --mode report
```

**扫描并评论到 Issue：**

```bash
python -m scripts.scan_issue --issue 123 --mode comment
# 或使用专用脚本
python -m scripts.comment_issue --issue 123
```

**手动输入扫描：**

```bash
python -m scripts.scan_issue --title "xxx报错" --body "详细描述"
```

支持 Issue 编号（`123`）、带#编号（`#123`）和 URL（`https://gitcode.com/.../issues/123`）格式。

### 3. 添加 Issue 到知识库

**从 GitCode 拉取：**

```bash
python -m scripts.add_issue --issue 123
python -m scripts.add_issue --issue 123 --with-comments
```

**手动添加：**

```bash
python -m scripts.add_issue --manual --title "xxx" --body "xxx" --labels "bug,安装"
```

已存在的 Issue 会自动更新（标题、正文、状态、评论、解决方案）。

### 4. 定时扫描新 Issue

**执行增量扫描：**

```bash
python -m scripts.scan_new                  # 扫描新 Issue（仅报告）
python -m scripts.scan_new --mode comment   # 扫描并评论
python -m scripts.scan_new --status         # 查看运行状态
```

扫描游标和已处理 Issue 列表保存在知识库元数据中，支持断点续跑，不会重复评论。单个 Issue 处理失败不影响其他 Issue。

Agent 可通过系统 cron 或其他方式创建定时任务来定期执行此脚本。

### 5. FAQ 生成

FAQ 内容中英双语：中文写入 `docs/faq/zh/`、英文写入 `docs/faq/en/`。英文由 `LLM_MODEL` 生成；未配置 LLM（或调用失败）时自动降级为仅输出中文，不产生半成品英文文档。

**全量生成：**

```bash
python -m scripts.generate_faq
```

**按分类生成：**

```bash
python -m scripts.generate_faq --category 安装
python -m scripts.generate_faq --category Timeline
```

**为指定 Issue 生成单条 FAQ：**

```bash
python -m scripts.generate_faq --issue 123
```

**增量更新 / 正式版：**

```bash
python -m scripts.generate_faq --incremental
python -m scripts.generate_faq --no-draft    # 生成正式版（非草稿）
```

**调试（限制条数，降低 LLM 开销）：**

```bash
python -m scripts.generate_faq --limit 2     # 批量生成时仅处理前 2 条已解决 Issue（--issue 单条模式不适用）
```

FAQ 以 Markdown 格式分语言保存到 `docs/faq/zh/`（中文）与 `docs/faq/en/`（英文）。默认生成草稿（文件名含 `_draft`），维护者确认后去掉 `_draft` 后缀发布。

### 6. 模板噪声清洗

Issue 正文常含固定模板：既有**无意义噪声**（社区页脚客套话"欢迎加入社区…"、提交须知、安全信息提醒等），也有**有意义的结构骨架**（"### 🐛 问题描述""### 环境信息"等标题）。系统采用**频率预筛 + LLM 语义判定**的混合策略：频率只用于缩小候选范围（出现在 >= `TEMPLATE_MIN_SUPPORT` 条 Issue 的重复行才送审），remove/keep 最终由 LLM 逐行语义判定，因此能保留高频结构标题、剔除高频噪声。判定结果缓存到 `llm_template_cache.json`（人可读可编辑），跨扫描复用；LLM 失败时降级为保留、绝不误删。

**默认自动清洗**：`build_kb` 拉取后先跑"分类预pass"（LLM 判定候选行、写缓存），录入时 `body_raw` 保留原文、`body` 存清洗后文本；`scan_issue` 查询侧对称清洗，保证查询向量与知识库向量一致。

**审计判定（不改 body）：**

```bash
python -m scripts.clean_templates --preview   # 频率预筛 + LLM 判定 + 打印判定表（行/出现数/verdict/理由）+ 写缓存
```

**手改缓存后重落地 / 存量库就地清洗：**

```bash
python -m scripts.clean_templates --apply      # 按缓存回填 body + 重算 embedding（不请求 GitCode）
```

**归档旧知识库并全量重建：**

```bash
python -m scripts.kb_manage archive            # 整体移到 archive/kb-legacy-<时间戳>/ 并重置为空
python -m scripts.build_kb --fresh             # 从 GitCode 全量重拉 + LLM 清洗 + 重算 embedding
```

## 配置项

所有配置通过 `.env` 文件管理：

| 配置                    | 默认值                 | 说明                                         |
| ----------------------- | ---------------------- | -------------------------------------------- |
| `GITCODE_TOKEN`         | (空)                   | GitCode API Token                            |
| `GITCODE_REPO`          | Ascend/msinsight       | 默认仓库地址（可通过 `--repo` 运行时覆盖） |
| `SIMILARITY_THRESHOLD`  | 0.75                   | 相似度阈值                                   |
| `SCAN_TOP_K`            | 5                      | 返回相似 Issue 数量                          |
| `SCAN_MODE`             | report                 | 默认模式: report / comment                   |
| `INCLUDE_CLOSED`        | true                   | 是否检索已关闭 Issue                         |
| `INCLUDE_COMMENTS`      | true                   | 是否包含评论内容                             |
| `IGNORE_LABELS`         | (空)                   | 忽略的标签，逗号分隔                         |
| `KB_DIR`                | ./issue-knowledge-base | 知识库目录                                   |
| `FAQ_DIR`               | ./docs/faq             | FAQ 输出目录（zh/ 与 en/ 子目录）            |
| `LLM_MODEL`             | gpt-4o-mini            | FAQ 英文内容生成所用大模型                   |
| `CLEAN_TEMPLATE`        | true                   | 是否启用模板噪声清洗                         |
| `TEMPLATE_MIN_SUPPORT`  | 3                      | 频率预筛：出现在 >= N 条 Issue 才送 LLM 判定 |
| `TEMPLATE_MIN_LINE_LEN` | 4                      | 短于此的行不判定、直接保留                   |
| `TEMPLATE_LLM_BATCH`    | 40                     | 每次 LLM 调用判定的行数                      |

## 数据存储

所有数据保存在本地目录，不依赖外部数据库。每个仓库拥有独立的知识库目录：

```
issue-knowledge-base/                  # 默认仓库 (Ascend/msinsight)
├── issues/              # 每条 Issue 一个 JSON（body=清洗后 / body_raw=原文）
├── embeddings.json      # Embedding 索引
├── metadata.json        # 游标、统计、更新时间
├── llm_template_cache.json  # LLM 模板行判定缓存（人可读可编辑）
└── reports/             # 扫描报告

issue-knowledge-base-{owner}_{repo}/   # 其他仓库（自动创建）
├── issues/
├── embeddings.json
└── ...

docs/faq/
├── zh/                  # 中文 FAQ
└── en/                  # 英文 FAQ（由 LLM 生成）
```

## 注意事项

- 扫描结果仅作为相似问题参考，不直接判定 Issue 重复
- 评论包含固定标记 `<!-- issue-skill-scan-report:v1 -->`，避免重复发布
- GitCode Token 通过环境变量配置，不写入代码仓库
- 单个 Issue 处理失败时记录错误，不影响其他 Issue
- 验证阶段建议优先使用 `--mode report`，避免真实评论污染线上 Issue
