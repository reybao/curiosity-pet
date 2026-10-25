"""Main model call: native Ollama /api/chat, streaming text, think=false.

Only local addresses are allowed. If the local model is unreachable, raise PetUnavailable so the caller shows and reads aloud a fixed notice,
and never falls back to any external service (hard constraint 1).
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
        raise ValueError(f"Only a local model service is allowed: {base_url}")
    body = {"model": model, "messages": messages, "stream": True, "think": False}
    try:
        with httpx.stream("POST", f"{base_url}/api/chat", json=body, timeout=timeout) as resp:
            if resp.status_code != 200:
                raise PetUnavailable(f"Ollama returned {resp.status_code}")
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
