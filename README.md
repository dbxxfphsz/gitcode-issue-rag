# Issue 相似性分析 Skill

基于 GitCode Issue 历史数据的相似性分析工具。无需部署独立服务，通过脚本直接运行。

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -e .

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 和 GITCODE_TOKEN

# 4. 构建知识库
python -m scripts.build_kb

# 5. 扫描 Issue
python -m scripts.scan_issue --issue 123
```

## 核心功能

| 功能         | 命令                                          | 说明                             |
| ------------ | --------------------------------------------- | -------------------------------- |
| 构建知识库   | `python -m scripts.build_kb`                  | 从 GitCode 拉取 Issue 并构建索引 |
| 扫描 Issue   | `python -m scripts.scan_issue --issue 123`    | 查找相似历史问题                 |
| 添加到知识库 | `python -m scripts.add_issue --issue 123`     | 保存 Issue 并更新索引            |
| 评论到 Issue | `python -m scripts.comment_issue --issue 123` | 将报告发布为评论                 |
| 增量扫描     | `python -m scripts.scan_new`                  | 扫描新增 Issue                   |
| 生成 FAQ     | `python -m scripts.generate_faq`              | 从已解决 Issue 生成中英双语 FAQ  |
| 调试 FAQ     | `python -m scripts.generate_faq --limit 2`    | 仅处理前 2 条（降低 LLM 开销）   |
| 管理知识库   | `python -m scripts.kb_manage status`          | 查看状态/删除/重建索引           |
| 模板清洗审计 | `python -m scripts.clean_templates --preview` | LLM 判定模板噪声行（不改 body）  |
| 归档并重建   | `python -m scripts.kb_manage archive`         | 归档旧库后 build_kb --fresh 重拉 |

## 项目结构

```
issue_kb/                    # 核心模块
├── config.py                # 配置管理
├── gitcode_client.py        # GitCode API 客户端
├── llm.py                   # LLM 调用（chat / json）
├── knowledge.py             # 文件型知识库管理
├── similarity.py            # Embedding + 余弦相似度搜索
├── template_classifier.py   # 模板噪声清洗（频率预筛 + LLM 判定）
├── report.py                # Markdown 报告生成
├── commenter.py             # GitCode 评论管理
└── faq.py                   # FAQ 文档生成
scripts/                     # 可执行脚本
├── build_kb.py              # 构建知识库
├── scan_issue.py            # 扫描 Issue
├── add_issue.py             # 添加 Issue
├── comment_issue.py         # 评论 Issue
├── scan_new.py              # 增量扫描新 Issue
├── generate_faq.py          # 生成 FAQ
├── kb_manage.py             # 知识库管理
└── clean_templates.py       # 模板噪声清洗（审计 / 回填）
SKILL.md                     # Agent Skill 详细说明
DESIGN.md                    # 技术设计文档
issue-knowledge-base/        # 知识库数据目录（运行后生成）
archive/                     # 归档的旧知识库（kb_manage archive 生成）
docs/faq/                    # FAQ 输出目录（zh/ 中文、en/ 英文）
```

## 文档

- [SKILL.md](SKILL.md) - Agent Skill 使用说明
- [DESIGN.md](DESIGN.md) - 技术设计文档
