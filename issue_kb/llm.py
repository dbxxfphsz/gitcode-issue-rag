"""LLM 调用封装 - OpenAI 兼容 chat completions API。

FAQ 生成等需要 LLM 的场景统一走这里，与 similarity.py 的 embedding 调用对称。
调用失败（未配置 Key、网络错误、返回异常、非法 JSON）时返回 None，由调用方降级
处理，保证主流程不中断。
"""

import json
import re

import httpx
from loguru import logger

from issue_kb.config import settings


def chat_completion(
    messages: list[dict],
    temperature: float = 0.3,
    timeout: int = 90,
) -> str | None:
    """调用 chat completions API，返回助手回复文本；失败返回 None。"""
    if not settings.openai_api_key:
        logger.warning("未配置 OPENAI_API_KEY，LLM 功能降级")
        return None
    try:
        resp = httpx.post(
            f"{settings.openai_api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "messages": messages,
                "temperature": temperature,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return None


def chat_json(messages: list[dict], temperature: float = 0.3) -> dict | None:
    """调用 LLM 并解析 JSON 回复；失败或非法 JSON 返回 None。"""
    content = chat_completion(messages, temperature=temperature)
    if not content:
        return None
    return parse_json_loose(content)


def parse_json_loose(text: str) -> dict | None:
    """从 LLM 回复中健壮地提取 JSON 对象。

    容忍 ```json 代码块围栏与前后噪声文本；无法解析时返回 None。
    """
    text = text.strip()
    # 去掉 Markdown 代码块围栏
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 回退：截取第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    logger.warning("LLM 回复无法解析为 JSON，降级处理")
    return None
