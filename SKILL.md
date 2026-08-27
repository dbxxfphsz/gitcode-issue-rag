# Issue 相似性分析 Skill

提供 Issue 知识库管理、相似问题检索、扫描报告生成、GitCode 评论发布和 FAQ 文档生成能力。Agent 通过自然语言指令直接调用。

## 触发条件

- "扫描这个 Issue，看看是否有类似问题"
- "把这个 Issue 加入知识库"
- "每天定时扫描新 Issue，并评论相似问题"
- "基于历史 Issue 生成 FAQ 文档"
- "查看知识库状态"

## 前置条件

1. `.env` 已配置（API Key、GitCode Token）
2. 依赖已安装：`pip install -e .`
3. 知识库已构建：`python -m scripts.build_kb`

## 操作指南

### 1. 知识库管理

**初始化/重建知识库：**

```bash
python -m scripts.build_kb              # 全量构建
python -m scripts.build_kb --fresh       # 清空后重建
python -m scripts.build_kb --incremental # 增量更新
```

**同步最新 Issue：**

```bash
python -m scripts.build_kb --incremental
```

**查看状态：**

```bash
python -m scripts.kb_manage status
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

FAQ 以 Markdown 格式保存到 `docs/faq/` 目录。默认生成草稿（文件名含 `_draft`），维护者确认后去掉 `_draft` 后缀发布。

## 配置项

所有配置通过 `.env` 文件管理：

| 配置                   | 默认值                 | 说明                       |
| ---------------------- | ---------------------- | -------------------------- |
| `GITCODE_TOKEN`        | (空)                   | GitCode API Token          |
| `GITCODE_REPO`         | Ascend/msinsight       | 仓库地址                   |
| `SIMILARITY_THRESHOLD` | 0.75                   | 相似度阈值                 |
| `SCAN_TOP_K`           | 5                      | 返回相似 Issue 数量        |
| `SCAN_MODE`            | report                 | 默认模式: report / comment |
| `INCLUDE_CLOSED`       | true                   | 是否检索已关闭 Issue       |
| `INCLUDE_COMMENTS`     | true                   | 是否包含评论内容           |
| `IGNORE_LABELS`        | (空)                   | 忽略的标签，逗号分隔       |
| `KB_DIR`               | ./issue-knowledge-base | 知识库目录                 |
| `FAQ_DIR`              | ./docs/faq             | FAQ 输出目录               |

## 数据存储

所有数据保存在本地目录，不依赖外部数据库：

```
issue-knowledge-base/
├── issues/              # 每条 Issue 一个 JSON 文件
├── embeddings.json      # Embedding 索引
├── metadata.json        # 游标、统计、更新时间
└── reports/             # 扫描报告

docs/faq/                # FAQ 文档
```

## 注意事项

- 扫描结果仅作为相似问题参考，不直接判定 Issue 重复
- 评论包含固定标记 `<!-- issue-skill-scan-report:v1 -->`，避免重复发布
- GitCode Token 通过环境变量配置，不写入代码仓库
- 单个 Issue 处理失败时记录错误，不影响其他 Issue
