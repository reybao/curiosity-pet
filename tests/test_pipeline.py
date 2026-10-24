"""流程层:道别用固定结束语,不调用模型;模型不可用时朗读固定提示。"""

import numpy as np

from curiosity_pet import pipeline
from curiosity_pet.llm import PetUnavailable
from curiosity_pet.pipeline import FAREWELL, Pet, is_goodbye


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append((lang, text))
        return np.zeros(10, dtype=np.float32)


class FakePlayer:
    def play(self, audio, text=None, on_start=None):
        if on_start:
            on_start()


def make_pet():
    return Pet(asr=None, tts=FakeTTS(), player=FakePlayer())


def test_is_goodbye():
    assert is_goodbye("再见")
    assert is_goodbye("再见!")
    assert is_goodbye("Bye.")
    assert not is_goodbye("再见是什么意思?")


def test_goodbye_uses_fixed_farewell_without_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("道别不应调用模型")

    monkeypatch.setattr(pipeline, "stream_chat", boom)
    pet = make_pet()
    turn = pet.answer("再见")
    assert turn.answer == FAREWELL["zh"]
    assert pet.tts.spoken == [("zh", FAREWELL["zh"])]


def test_unavailable_model_speaks_fixed_message(monkeypatch):
    def down(*a, **k):
        raise PetUnavailable("down")
        yield  # noqa: unreachable,使其成为生成器

    monkeypatch.setattr(pipeline, "stream_chat", down)
    pet = make_pet()
    turn = pet.answer("Why is the sky blue?")
    assert turn.unavailable
    assert pet.tts.spoken[0][0] == "en"
    assert pet.history == []


def test_answer_streams_sentences_and_keeps_history_in_memory(monkeypatch):
    monkeypatch.setattr(
        pipeline, "stream_chat", lambda msgs: iter(["月亮不会自己发光，", "它反射太阳光。"])
    )
    pet = make_pet()
    turn = pet.answer("月亮为什么亮?")
    assert turn.sentences == ["月亮不会自己发光，", "它反射太阳光。"]
    assert len(pet.history) == 2
    pet.end_session()
    assert pet.history == []
