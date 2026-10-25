"""Arithmetic is computed by the program, never by the language model.

The parent's example: "九十一除以五" was heard as "九十一处以5" and the 4B model answered nonsense.
"""

import numpy as np
import pytest

from curiosity_pet import pipeline
from curiosity_pet.arith import explain, parse
from curiosity_pet.pipeline import Pet


@pytest.mark.parametrize(
    "text, value",
    [
        ("九十一除以五是多少?", 91 / 5),
        ("九十一处以5", 91 / 5),  # ASR homophone
        ("91除以5等于几", 91 / 5),
        ("三乘以七", 21),
        ("三成以七是多少", 21),  # ASR homophone
        ("一百减去二十五", 75),
        ("100减25", 75),
        ("9加10等于多少", 19),
        ("两千加三百", 2300),
        ("十二乘以十二", 144),
        ("3 加 4 乘 2", 11),  # precedence
        ("What is 91 divided by 5?", 91 / 5),
        ("what's seven times eight", 56),
        ("twelve plus thirty", 42),
        ("100 minus 1", 99),
        ("fifteen divided by three", 5),
        ("How much is 2 + 3?", 5),
        ("8 × 7", 56),
        ("20 ÷ 4", 5),
    ],
)
def test_parse_and_evaluate(text, value):
    expr = parse(text)
    assert expr is not None, text
    assert float(expr.value) == pytest.approx(value)


@pytest.mark.parametrize(
    "text, value",
    [
        # The child's real questions: "A除B" without 以 means B divided by A
        ("六除九十是几？", 15),
        ("六除九是几？", 9 / 6),
        ("九十除六", 15),  # everyday speech for 90 / 6: a plain 除 divides the larger number by the smaller
        ("我问你：六除以九十等于几？", 6 / 90),  # lead-in phrase; 除以 keeps its order
        ("嗯,没事的。你带着平板,去问老师:“六除九十。”", 15),  # relayed in quotes
        ("考考你,七乘八是多少", 56),
        ("你知道一百减一等于几吗", 99),
    ],
)
def test_real_division_questions(text, value):
    expr = parse(text)
    assert expr is not None, text
    assert float(expr.value) == pytest.approx(value)


def test_plain_chu_is_said_the_way_it_was_computed():
    assert explain(parse("六除九十是几？"), "zh").startswith("九十除以六等于十五。")


def test_smaller_by_larger_says_not_enough_then_the_other_way():
    zh = explain(parse("我问你：六除以九十等于几？"), "zh")
    assert zh.startswith("六除以九十,六比九十小,不够分,得数比一还小。")
    assert "反过来,九十除以六等于十五。" in zh and "还剩六" not in zh
    en = explain(parse("6 divided by 90"), "en")
    assert "not enough to share" in en and "90 divided by 6 is 15" in en
    assert "七除以五等于一,还剩二" in explain(parse("5除以7"), "zh")


@pytest.mark.parametrize(
    "text",
    ["为什么天空是蓝色的?", "恐龙有多少种?", "Why do cats purr?", "What is 5?", "我今年七岁", "第五个是谁", "2024年发生了什么",
     "除了三个苹果还有什么", "老师说：明天带三个苹果", "我有三个苹果"],
)
def test_non_arithmetic_is_ignored(text):
    assert parse(text) is None


def test_explanations_are_for_children():
    zh = explain(parse("九十一除以五"), "zh")
    assert "九十一除以五" in zh and "十八" in zh and "剩" in zh and "一" in zh
    en = explain(parse("91 divided by 5"), "en")
    assert "18" in en and "1 left over" in en
    assert explain(parse("20除以4"), "zh").startswith("二十除以四等于五")
    assert "cannot divide by zero" in explain(parse("5 divided by 0"), "en").lower()
    assert "负" in explain(parse("五减八"), "zh")
    assert "21" in explain(parse("3 times 7"), "en")


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class FakePlayer:
    def play(self, audio, text=None, on_start=None):
        pass


def test_pet_computes_without_calling_the_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("arithmetic must not reach the model")

    monkeypatch.setattr(pipeline, "stream_chat", boom)
    tts = FakeTTS()
    pet = Pet(asr=None, tts=tts, player=FakePlayer())
    turn = pet.answer("九十一处以5是多少?")
    assert turn.topic == "math" and turn.sentences
    assert "十八" in "".join(tts.spoken)
    assert pet.history[-1]["content"] == "".join(turn.sentences)


def test_english_single_sentence_answer_is_spoken(monkeypatch):
    # Regression: the final English sentence (no trailing space) was lost by a mismatched splitter flush
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter([]))
    tts = FakeTTS()
    Pet(asr=None, tts=tts, player=FakePlayer()).answer("twenty plus thirty")
    assert tts.spoken == ["20 plus 30 is 50."]


def test_child_stated_results_are_checked_by_the_program():
    from curiosity_pet.arith import explain_claim, parse_claim

    assert explain_claim(*parse_claim("我算对了吗?三加四等于七"), "zh") == "对,三加四等于七。"
    assert explain_claim(*parse_claim("Three plus four equals ten."), "en") == "Let's check: 3 plus 4 is 7, not 10."
    assert explain_claim(*parse_claim("九十除以六是十五对吗"), "zh") == "对,九十除以六等于十五。"
    for q in ["六除九十是几?", "一加一等于几?", "我今年七岁", "What is 2 plus 2?"]:
        assert parse_claim(q) is None, q
