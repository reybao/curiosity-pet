"""Date and time come from the clock, not from the model (it said "Wednesday" on a Saturday)."""

import datetime as dt

import numpy as np

from curiosity_pet import clock, pipeline
from curiosity_pet.pipeline import Pet
from curiosity_pet.prompts import build_messages

SAT = dt.datetime(2026, 10, 24, 9, 50)


def test_weekday_and_date_questions():
    assert clock.answer("今天星期几?", "zh", SAT) == "今天是二零二六年十月二十四日,星期六。"
    assert clock.answer("明天是星期几", "zh", SAT) == "明天是二零二六年十月二十五日,星期日。"
    assert clock.answer("昨天几号?", "zh", SAT).startswith("昨天是二零二六年十月二十三日,星期五")
    assert clock.answer("What day is it today?", "en", SAT) == "Today is Saturday, October 24, 2026."
    assert clock.answer("What's the date tomorrow?", "en", SAT) == "Tomorrow is Sunday, October 25, 2026."


def test_time_questions():
    assert clock.answer("现在几点了?", "zh", SAT) == "现在是上午九点五十分。"
    assert clock.answer("What time is it?", "en", dt.datetime(2026, 10, 24, 15, 5)) == "It's 3:05 in the afternoon."
    assert clock.answer("现在几点", "zh", dt.datetime(2026, 10, 24, 20, 30)) == "现在是晚上八点半。"


def test_other_questions_are_not_dates():
    for q in ["星期六为什么不上学?", "为什么一个星期有七天?", "Why is the sky blue?", "恐龙什么时候灭绝的?"]:
        assert clock.answer(q, "zh", SAT) is None, q


def test_date_note_only_when_time_words_appear():
    assert clock.mentions_time("下个星期六是几号?") and clock.mentions_time("How many days until Christmas?")
    assert not clock.mentions_time("为什么天空是蓝色的?")
    msgs = build_messages("下个星期六是几号?", "zh", [], date_note=clock.date_note("zh", SAT))
    assert "(今天是2026年10月24日,星期六)" in msgs[-1]["content"]


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class FakePlayer:
    def play(self, audio, text=None, on_start=None):
        pass


def test_pet_answers_the_weekday_without_the_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("date questions must not reach the model")

    monkeypatch.setattr(pipeline, "stream_chat", boom)
    tts = FakeTTS()
    turn = Pet(asr=None, tts=tts, player=FakePlayer()).answer("今天星期几?")
    assert turn.topic == "time" and "星期" in "".join(tts.spoken)
