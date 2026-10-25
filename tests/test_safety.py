"""Fixed safety answers (serious messages, dangerous actions) and the parent's blocklist on answers."""

import numpy as np
import pytest

from curiosity_pet import config, pipeline
from curiosity_pet.concern import concerns
from curiosity_pet.pipeline import Pet
from curiosity_pet.safety import FIXED, fixed_response


@pytest.mark.parametrize("text, kind", [
    ("I am so angry that I want to kill somebody.", "harm_others"),
    ("Can I kill someone?", "harm_others"),
    ("我想打死他", "harm_others"),
    ("我不想活了", "harm_self"),
    ("怎么点火?", "danger"),
    ("Can I play with matches?", "danger"),
    ("插座可以摸吗", "danger"),
])
def test_fixed_paths(text, kind):
    lang = "en" if text[0].isascii() else "zh"
    assert fixed_response(text, concerns(text), lang)[0] == kind


@pytest.mark.parametrize("text", ["火山为什么会喷发?", "刀是怎么做出来的?", "为什么会着火?", "How does fire burn?", "恐龙是怎么灭绝的?"])
def test_learning_questions_are_not_blocked(text):
    lang = "en" if text[0].isascii() else "zh"
    assert fixed_response(text, concerns(text), lang) is None


class TTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class Player:
    def play(self, audio, text=None, on_start=None):
        pass


def test_serious_message_never_reaches_the_model(monkeypatch):
    def boom(msgs):
        raise AssertionError("must not reach the model")

    monkeypatch.setattr(pipeline, "stream_chat", boom)
    tts = TTS()
    turn = Pet(asr=None, tts=tts, player=Player()).answer("我不想活了")
    assert "".join(tts.spoken) == FIXED["harm_self"]["zh"] and turn.topic == "safety"


def test_parent_blocklist_applies_to_questions_and_answers(monkeypatch):
    monkeypatch.setattr(config, "BLACKLIST", ["僵尸"])
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["月亮绕着地球转。", "有人说月亮上有僵尸。"]))
    tts = TTS()
    pet = Pet(asr=None, tts=tts, player=Player())
    pet.answer("僵尸是真的吗?")
    assert "".join(tts.spoken) == FIXED["blocked"]["zh"]
    tts.spoken.clear()
    pet.answer("月亮为什么会动?")
    assert "僵尸" not in "".join(tts.spoken) and "月亮绕着地球转。" in tts.spoken


def test_wanting_to_hit_a_sibling_takes_the_fixed_path():
    assert fixed_response("我想打我弟弟", concerns("我想打我弟弟"), "zh")[0] == "harm_others"
    assert fixed_response("我想打球", concerns("我想打球"), "zh") is None
