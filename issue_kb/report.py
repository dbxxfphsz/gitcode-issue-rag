"""扫描报告生成 - 将相似性搜索结果格式化为 Markdown 报告。"""

from datetime import datetime, timezone


def generate_scan_report(
    target_issue: dict,
    similar_issues: list[dict],
    kb_issues: dict[int, dict] | None = None,
) -> str:
    """生成 Issue 相似性扫描报告。

    Args:
        target_issue: 被扫描的 issue 数据
        similar_issues: 相似 issue 列表 [{"number", "score", "issue"}, ...]
        kb_issues: 知识库 issue 字典 {number: data}，用于补充详情

    Returns:
        Markdown 格式的报告字符串
    """
    kb = kb_issues or {}
    lines = [
        "# Issue 相似性扫描报告",
        "",
        f"> 生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 目标 Issue",
        "",
        f"- **编号**: #{target_issue.get('number', '?')}",
        f"- **标题**: {target_issue.get('title', '')}",
        f"- **状态**: {target_issue.get('state', '')}",
        f"- **链接**: {target_issue.get('url', '')}",
        f"- **标签**: {', '.join(target_issue.get('labels', [])) or '无'}",
        "",
    ]

    if not similar_issues:
        lines += [
            "## 扫描结果",
            "",
            "未找到相似的历史 Issue。这可能是一个新问题。",
            "",
            "> ⚠️ 本结果仅基于知识库中已有数据的相似性分析，不代表不存在类似问题。",
        ]
        return "\n".join(lines)

    lines += [
        "## 扫描结果",
        "",
        f"找到 **{len(similar_issues)}** 个相似 Issue：",
        "",
    ]

    for i, item in enumerate(similar_issues, 1):
        num = item["number"]
        score = item["score"]
        # 编号归一化为 str 后再查字典，兼容 int/str 混合存储
        issue = item.get("issue") or {}
        if not issue:
            for k in (num, str(num)):
                issue = kb.get(k, {})
                if issue:
                    break

        title = issue.get("title", "未知")[:100]
        state = issue.get("state", "未知")
        url = issue.get("url", "")
        labels = issue.get("labels", [])
        solution = issue.get("solution", "")

        state_emoji = {"closed": "🟢", "open": "🔵"}.get(state, "⚪")

        lines += [
            f"### {i}. #{num} {title}",
            "",
            f"| 属性 | 值 |",
            f"|------|------|",
            f"| 相似度 | **{score:.2%}** |",
            f"| 状态 | {state_emoji} {state} |",
            f"| 链接 | [{url}]({url}) |",
            f"| 标签 | {', '.join(labels) or '无'} |",
        ]

        if solution:
            lines += [
                "",
                f"**历史解决方案摘要**:",
                f"> {solution[:300]}",
            ]

        lines.append("")

    lines += [
        "---",
        "",
        "> ⚠️ **声明**: 以上结果仅作为相似问题参考，不直接判定 Issue 重复。",
        "> 请结合实际情况判断是否为同一问题或相关变体。",
    ]

    return "\n".join(lines)


def generate_comment_body(report: str, issue_number: int) -> str:
    """为 GitCode 评论包装报告内容，添加防重复标记。"""
    marker = f"<!-- issue-skill-scan-report:v1:issue-{issue_number} -->"
    return f"{marker}\n\n{report}"


def has_existing_comment(comments: list[dict], issue_number: int) -> bool:
    """检查 issue 下是否已有本 Skill 发布的扫描报告评论。"""
    marker = f"issue-skill-scan-report:v1:issue-{issue_number}"
    for c in comments:
        body = c.get("body", "")
        if marker in body:
            return True
    return False
