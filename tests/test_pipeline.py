"""Pipeline layer: goodbyes use a fixed closing line without calling the model; when the model is unavailable, a fixed notice is spoken."""

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
        raise AssertionError("goodbye must not call the model")

    monkeypatch.setattr(pipeline, "stream_chat", boom)
    pet = make_pet()
    turn = pet.answer("再见")
    assert turn.answer == FAREWELL["zh"]
    assert pet.tts.spoken == [("zh", FAREWELL["zh"])]


def test_unavailable_model_speaks_fixed_message(monkeypatch):
    def down(*a, **k):
        raise PetUnavailable("down")
        yield  # noqa: unreachable, makes this a generator

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


class FakeUsage:
    def __init__(self):
        self.turns = []
        self.ends = []

    def record(self, turn):
        self.turns.append(turn)

    def end(self, reason):
        self.ends.append(reason)


def test_turns_are_recorded_and_goodbye_ends_session(monkeypatch):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["好的\u3002"]))
    usage = FakeUsage()
    pet = Pet(asr=None, tts=FakeTTS(), player=FakePlayer(), usage=usage)
    pet.answer("黑洞是什么?")
    pet.answer("再见")
    assert [t.question for t in usage.turns] == ["黑洞是什么?", "再见"]
    assert usage.turns[1].topic == "chat"
    assert usage.ends == ["goodbye"]
    pet.answer("星星为什么眨眼?")
    pet.end_session("end_button")
    assert usage.ends == ["goodbye", "end_button"]


def test_unavailable_turn_is_still_recorded(monkeypatch):
    def down(*a, **k):
        raise PetUnavailable("down")
        yield

    monkeypatch.setattr(pipeline, "stream_chat", down)
    usage = FakeUsage()
    pet = Pet(asr=None, tts=FakeTTS(), player=FakePlayer(), usage=usage)
    pet.answer("黑洞是什么?")
    assert usage.turns[0].unavailable


def test_cancel_stops_generation_and_skips_recording(monkeypatch):
    import threading

    cancel = threading.Event()

    def stream(msgs):
        yield "第一句已经说完了没有问题\u3002"
        cancel.set()  # the child presses stop mid-answer
        yield "第二句不应该念出来\u3002"

    monkeypatch.setattr(pipeline, "stream_chat", stream)
    usage = FakeUsage()
    tts = FakeTTS()
    pet = Pet(asr=None, tts=tts, player=FakePlayer(), usage=usage)
    turn = pet.answer("黑洞是什么?", cancel=cancel)
    assert turn.cancelled
    assert tts.spoken == [("zh", "第一句已经说完了没有问题\u3002")]
    assert usage.turns == []



# ---------- calling a parent (call_parent.py), wired in pipeline ----------

from curiosity_pet.call_parent import CallParent, RateLimit  # noqa: E402

CALL_SET = {"call_parent": {"telegram": {"bot_token": "t", "chat_id": "1"}}}


def _call_pet():
    from curiosity_pet.pipeline import Pet as _Pet

    class _TTS:
        def synthesize(self, text, lang):
            return np.zeros(10, dtype=np.float32)

    class _Player:
        def play(self, audio, text=None, on_start=None):
            pass

    return _Pet(asr=None, tts=_TTS(), player=_Player())


def test_call_parent_asks_then_sends_without_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the model")

    monkeypatch.setattr(pipeline, "stream_chat", boom)
    sent = []
    pet = _call_pet()
    pet.calls = CallParent("ipad", None, send=lambda o, c, t: sent.append(t) or True, limit=RateLimit(),
                           settings=lambda: CALL_SET, judge=None)
    assert "".join(pet.answer("叫爸爸来。").sentences) == "要我告诉爸爸你在找他吗?"
    assert "".join(pet.answer("嗯。").sentences) == "好的,我已经告诉爸爸了。" and len(sent) == 1


def test_stop_drops_pending_call():
    pet = _call_pet()
    pet.calls = CallParent("ipad", None, send=lambda o, c, t: True, limit=RateLimit(), settings=lambda: CALL_SET,
                           judge=None)
    pet.answer("tell daddy I'm done")
    pet.end_session()
    assert pet.calls.pending is None
