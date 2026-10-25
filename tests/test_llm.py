"""Raise PetUnavailable when the local model is unavailable; never fall back to any external service."""

import pytest

from curiosity_pet.llm import PetUnavailable, stream_chat


def test_unreachable_ollama_raises_pet_unavailable():
    msgs = [{"role": "user", "content": "你好"}]
    with pytest.raises(PetUnavailable):
        # Nothing listens on port 9 (discard) locally, so the connection is refused
        list(stream_chat(msgs, base_url="http://127.0.0.1:9", timeout=2))


def test_only_localhost_is_allowed():
    msgs = [{"role": "user", "content": "你好"}]
    with pytest.raises(ValueError):
        list(stream_chat(msgs, base_url="https://api.example.com"))
