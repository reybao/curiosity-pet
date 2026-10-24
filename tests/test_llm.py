"""本地模型不可用时抛 PetUnavailable,不回退到任何外部服务。"""

import pytest

from curiosity_pet.llm import PetUnavailable, stream_chat


def test_unreachable_ollama_raises_pet_unavailable():
    msgs = [{"role": "user", "content": "你好"}]
    with pytest.raises(PetUnavailable):
        # 9 号端口(discard)本机没有服务,连接会被拒绝
        list(stream_chat(msgs, base_url="http://127.0.0.1:9", timeout=2))


def test_only_localhost_is_allowed():
    msgs = [{"role": "user", "content": "你好"}]
    with pytest.raises(ValueError):
        list(stream_chat(msgs, base_url="https://api.example.com"))
