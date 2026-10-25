"""Safety guard (layer 2): verdict parsing, the settings switch, and its place in the pipeline (fake guard)."""

import numpy as np

from curiosity_pet import guard, pipeline
from curiosity_pet.guard import Verdict, parse
from curiosity_pet.pipeline import Pet
from curiosity_pet.safety import FIXED


def test_parse_verdicts_non_strict_by_default():
    assert parse("Safety: Safe\nCategories: None").safe
    assert not parse("Safety: Unsafe\nCategories: Violent").safe
    assert parse("Safety: Controversial\nCategories: None").safe  # strict mode silenced 10% of normal sentences
    assert not parse("Safety: Controversial\nCategories: None", strict=True).safe
    assert parse("garbage").safe and parse("garbage").label == "Unknown"


def test_mode_from_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "DEFAULT_PATH", tmp_path)
    assert guard.mode({}) == "off"
    assert guard.mode({"guard": "questions"}) == "questions"
    assert guard.mode({"guard": True}) == "all"
    monkeypatch.setattr(guard, "DEFAULT_PATH", tmp_path / "missing")
    assert guard.mode({"guard": "all"}) == "off"  # no model converted: stays off


class FakeGuard:
    def question(self, text):
        return Verdict("炸" not in text, "Unsafe" if "炸" in text else "Safe")

    def answer(self, question, sentence):
        return Verdict("危险" not in sentence, "Unsafe" if "危险" in sentence else "Safe")


class TTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class Player:
    def play(self, audio, text=None, on_start=None):
        pass


def test_guard_blocks_questions_and_sentences(monkeypatch):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["烟花很漂亮。", "这里有一句危险的话。"]))
    tts = TTS()
    pet = Pet(asr=None, tts=tts, player=Player(), guard=FakeGuard(), guard_answers=True)
    pet.answer("烟花为什么会炸开?")
    assert tts.spoken == [FIXED["blocked"]["zh"]]
    tts.spoken.clear()
    pet.answer("烟花为什么是彩色的?")
    assert "危险" not in "".join(tts.spoken)
