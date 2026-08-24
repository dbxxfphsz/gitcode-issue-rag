# Issue Knowledge Base Skill

Scan issues for similar historical problems, manage a searchable knowledge base built from GitCode issues, and generate diagnostic reports.

## When to Use

- User says "扫描这个 issue"、"检查是否有类似问题"、"查一下有没有类似的"
- User says "把这个 issue 加入知识库"、"记录这个问题"
- User says "构建知识库"、"初始化知识库"
- User provides an issue title/body and asks to find similar issues

## Prerequisites

This skill requires the project to be set up:

1. `.env` configured with valid `OPENAI_API_KEY` and `OPENAI_API_BASE`
2. Dependencies installed: `pip install -e .`
3. Issue data cached: `python -m scripts.init_ingest` (first time only)

## Operations

### 1. Scan Issue (扫描 Issue)

When the user wants to check if an issue has similar historical problems:

**Step 1**: Get the issue title and body from the user.

**Step 2**: Run the scan script:
```bash
cd /Users/zhumingzhu/work/gitcode-issue-rag
python -m scripts.scan_issue --title "ISSUE_TITLE" --body "ISSUE_BODY" --top-k 5
```

**Step 3**: Read the output report and present it to the user. The report contains:
- Similar knowledge entries ranked by similarity score
- Each entry includes: title, category, problem description, solution, related issue URLs

**Step 4**: If similar issues are found (score > 0.8), summarize the known solutions and reference the original issue URLs. If no similar issues found, tell the user this appears to be a new problem.

### 2. Add Issue to Knowledge Base (加入知识库)

When the user wants to add an issue to the knowledge base:

**Step 1**: Collect issue details from the user:
- Issue ID (e.g., "#123")
- Title
- Body (optional but recommended)
- URL (optional)
- Labels (optional, comma-separated)

**Step 2**: Run the add script:
```bash
cd /Users/zhumingzhu/work/gitcode-issue-rag
python -m scripts.add_issue \
    --issue-id "#123" \
    --title "ISSUE_TITLE" \
    --body "ISSUE_BODY" \
    --url "ISSUE_URL" \
    --labels "bug,usage"
```

**Step 3**: Confirm to the user that the issue has been added and knowledge has been extracted.

### 3. Build Knowledge Base (构建知识库)

When the user wants to build the knowledge base from all cached issues (first-time setup):

**Step 1**: Ensure issue data is cached:
```bash
cd /Users/zhumingzhu/work/gitcode-issue-rag
python -m scripts.init_ingest
```

**Step 2**: Build the knowledge base (extracts knowledge from Bug/Usage issues):
```bash
python -m scripts.build_kb
```

Or limit the number of issues to process:
```bash
python -m scripts.build_kb --max-issues 20
```

**Step 3**: Report the number of knowledge entries created and the total knowledge base size.

### 4. Check Knowledge Base Stats (查看统计)

To check the current knowledge base size, start the API server and query:
```bash
curl http://localhost:8000/api/stats
```

## Automated Maintenance

The system includes automated maintenance when the FastAPI server is running (`python -m main`):

- **Daily (02:00)**: Crawls new issues and adds them to the raw data store
- **Monthly (1st of month, 03:00)**: Consolidates the knowledge base by merging similar entries using LLM

## Output Format

When presenting scan results to the user, use this format:

```
## 扫描结果

**Issue**: {title}
**匹配数**: {count}

### 相似问题 1: {matched_title}
- **相似度**: {score}
- **分类**: {category}
- **问题**: {problem_description}
- **解决方案**: {solution}
- **参考 Issue**: {url}
```

## Notes

- Knowledge entries are extracted by LLM from raw issues, so quality depends on the LLM model
- The knowledge base uses a separate ChromaDB collection from the raw issue store
- Monthly consolidation merges entries with similarity > 0.90 (configurable in .env)
- Bug and Usage labeled issues are prioritized for knowledge extraction
- Title keywords (报错, 错误, 失败, etc.) are also used as fallback for filtering
