# GitCode Issue RAG

基于 LangChain + ChromaDB 的 GitCode Issue 查重系统。自动爬取 GitCode 仓库的 issue 建立 RAG 知识库，提供 API 接口判断新 issue 是否已有相同答案。

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -e .

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 4. 首次全量入库（约 1-2 分钟）
python -m scripts.init_ingest

# 5. 启动服务
python -m main
```

服务启动后访问 http://localhost:8000/docs 查看 API 文档。

## 核心接口

```bash
# 检查 issue 是否重复
curl -X POST http://localhost:8000/api/check-duplicate \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Timeline 不支持 MODEL_EXECUTE 跳转",
    "body": "在多子图场景下，无法定位关联 Stream..."
  }'
```

返回示例：
```json
{
  "is_duplicate": true,
  "duplicate_url": "https://gitcode.com/Ascend/msinsight/issues/500",
  "similarity": 0.9234,
  "matched_title": "[Feature]: Timeline 支持 MODEL_EXECUTE 跳转并高亮对应 Stream 泳道"
}
```

## 项目结构

```
app/
├── config.py              # 全局配置（读取 .env）
├── crawler/
│   ├── gitcode.py         # GitCode API 爬虫
│   └── scheduler.py       # 每日定时任务
├── ingestion/
│   ├── __init__.py        # 入库流水线（分块 + embedding + 写入）
│   └── dedup.py           # 查重逻辑
├── api/
│   └── routes.py          # FastAPI 路由
└── shared/
    ├── models.py          # embedding + 向量库工厂
    └── schemas.py         # Issue 数据模型
scripts/
└── init_ingest.py         # 全量入库脚本
main.py                    # 启动入口
```
