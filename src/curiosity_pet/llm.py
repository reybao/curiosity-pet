"""主模型调用:Ollama 原生 /api/chat,流式文本,think=false。

只允许本机地址。连不上本地模型时抛 PetUnavailable,由上层显示并朗读固定提示,
不回退到任何外部服务(硬性约束第 1 条)。
"""

import json
from collections.abc import Iterator
from urllib.parse import urlparse

import httpx

from curiosity_pet import config

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

UNAVAILABLE_TEXT = {
    "zh": "我现在有点累,等一下再问我吧。",
    "en": "I need a little rest. Please ask me again in a bit.",
}


class PetUnavailable(Exception):
    pass


def stream_chat(
    messages: list[dict],
    model: str = config.CHAT_MODEL,
    base_url: str = config.OLLAMA_URL,
    timeout: float = 60,
) -> Iterator[str]:
    if urlparse(base_url).hostname not in LOCAL_HOSTS:
        raise ValueError(f"只允许本机模型服务: {base_url}")
    body = {"model": model, "messages": messages, "stream": True, "think": False}
    try:
        with httpx.stream("POST", f"{base_url}/api/chat", json=body, timeout=timeout) as resp:
            if resp.status_code != 200:
                raise PetUnavailable(f"Ollama 返回 {resp.status_code}")
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise PetUnavailable(chunk["error"])
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if chunk.get("done"):
                    return
    except httpx.HTTPError as e:
        raise PetUnavailable(str(e)) from e
