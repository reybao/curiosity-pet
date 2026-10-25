"""Follow-up questions are rationed by the program; the "tell a parent" line only appears on distress."""

import numpy as np

from curiosity_pet import pipeline
from curiosity_pet.followup import FollowUpPolicy, ends_with_question, looks_like_new_question
from curiosity_pet.pipeline import Pet
from curiosity_pet.prompts import build_messages, system_prompt


def warmed(p):
    """Past the first turns of an exploration, so a question is allowed."""
    for _ in range(p.min_gap):
        p.after_turn(asked=False)
    return p


def test_no_question_on_the_first_turn():
    p = FollowUpPolicy()
    assert not p.allow("恐龙为什么灭绝?")
    p.after_turn(asked=False)
    assert not p.allow("火山呢?")


def test_limit_survives_stop_and_start_but_not_a_long_pause():
    now = [0.0]
    p = warmed(FollowUpPolicy(clock=lambda: now[0]))
    p.new_turn()
    assert p.allow("恐龙为什么灭绝?")
    p.after_turn(asked=True)
    now[0] += 60  # stop, start again a minute later: still no question right away
    p.new_turn()
    assert not p.allow("火山为什么会喷发?")
    p.after_turn(asked=False)
    assert not p.allow("别问我了")
    now[0] += 31 * 60  # half an hour later it is a new exploration
    p.new_turn()
    assert not p.off and p.turns_since_question == 0


def test_at_most_one_question_every_three_turns():
    p = warmed(FollowUpPolicy())
    assert p.allow("恐龙为什么灭绝?")
    p.after_turn(asked=True)
    # The child answers the question: no new question on the answer turn, then three turns must pass
    assert not p.allow("因为陨石撞了地球")
    p.answered()
    p.after_turn(asked=False)
    assert not p.allow("火山呢?")
    p.after_turn(asked=False)
    assert not p.allow("它们吃什么?")
    p.after_turn(asked=False)
    assert p.allow("它有多重?")


def test_ignored_question_delays_the_next_one():
    p = warmed(FollowUpPolicy())
    assert p.allow("恐龙为什么灭绝?")
    p.after_turn(asked=True)
    # The child asks something else instead of answering: the question was ignored
    assert not p.allow("火山为什么会喷发?")
    p.after_turn(asked=False)
    assert not p.allow("彩虹是怎么来的?")
    p.after_turn(asked=False)
    assert not p.allow("星星为什么眨眼?")
    p.after_turn(asked=False)
    assert p.allow("为什么会下雨?")


def test_ignored_twice_means_no_more_questions():
    p = warmed(FollowUpPolicy(min_gap=1))
    assert p.allow("A?")
    p.after_turn(asked=True)
    assert not p.allow("B?")  # ignored once
    p.after_turn(asked=False)
    assert p.allow("C?")
    p.after_turn(asked=True)
    assert not p.allow("D?")  # ignored twice
    p.after_turn(asked=False)
    p.after_turn(asked=False)
    p.after_turn(asked=False)
    assert not p.allow("E?")


def test_stop_asking_turns_questions_off_for_the_exploration():
    p = FollowUpPolicy()
    assert not p.allow("别问我了")
    p.after_turn(asked=False)
    for _ in range(5):
        p.after_turn(asked=False)
    assert not p.allow("恐龙为什么灭绝?")
    p.reset()
    assert warmed(p).allow("恐龙为什么灭绝?")


def test_no_question_on_follow_up_turns():
    p = FollowUpPolicy()
    assert not p.allow("再简单一点")
    assert not p.allow("举个例子")
    assert not p.allow("Can you make it simpler?")


def test_helpers():
    assert ends_with_question("你知道为什么吗?") and ends_with_question("Do you know why?")
    assert not ends_with_question("恐龙很大。")
    assert looks_like_new_question("火山为什么会喷发?") and looks_like_new_question("What is a volcano?")
    assert not looks_like_new_question("因为陨石撞了地球")


# ---------- prompts ----------


def test_question_rule_is_per_turn_not_in_the_system_prompt():
    zh = system_prompt("zh")
    assert "小问题" not in zh and "question" not in system_prompt("en")
    allowed = build_messages("恐龙为什么灭绝?", "zh", [], ask=True)[-1]["content"]
    denied = build_messages("恐龙为什么灭绝?", "zh", [], ask=False)[-1]["content"]
    assert "可以问" in allowed and "不要提问" in denied
    assert "may end with one" in build_messages("Why?", "en", [], ask=True)[-1]["content"]
    assert "Do not ask" in build_messages("Why?", "en", [], ask=False)[-1]["content"]


def test_tell_a_parent_only_when_the_child_is_upset():
    for lang in ("zh", "en"):
        assert "爸妈" not in system_prompt(lang) and "parent" not in system_prompt(lang)
    plain = build_messages("恐龙为什么灭绝?", "zh", [])[-1]["content"]
    upset = build_messages("我今天好难过", "zh", [], care=True)[-1]["content"]
    assert "爸爸妈妈" not in plain and "难过" not in plain
    assert "爸爸妈妈" in upset
    assert "parent" in build_messages("I feel sad", "en", [], care=True)[-1]["content"]


# ---------- pipeline: dropped question sentences, distress detection ----------


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class FakePlayer:
    def play(self, audio, text=None, on_start=None):
        pass


def test_trailing_question_is_dropped_when_not_allowed(monkeypatch):
    seen = []

    def stream(msgs):
        seen.append(msgs[-1]["content"])
        return iter(["恐龙是被陨石撞灭绝的。", "你觉得恐龙还会回来吗？"])

    monkeypatch.setattr(pipeline, "stream_chat", stream)
    tts = FakeTTS()
    pet = Pet(asr=None, tts=tts, player=FakePlayer())
    warmed(pet.followup)
    # Turn 1: a question is allowed and spoken
    pet.answer("恐龙为什么灭绝?")
    assert tts.spoken == ["恐龙是被陨石撞灭绝的。", "你觉得恐龙还会回来吗？"]
    assert "可以问" in seen[-1]
    # Turn 2: the child ignored it and asked something new: no question, and the model's question is dropped
    tts.spoken.clear()
    pet.answer("火山为什么会喷发?")
    assert tts.spoken == ["恐龙是被陨石撞灭绝的。"]
    assert "不要提问" in seen[-1]


def test_distress_gets_the_care_note_and_no_question(monkeypatch):
    seen = []

    def stream(msgs):
        seen.append(msgs[-1]["content"])
        return iter(["听起来你很难过。"])

    monkeypatch.setattr(pipeline, "stream_chat", stream)
    pet = Pet(asr=None, tts=FakeTTS(), player=FakePlayer())
    pet.answer("我今天在学校被欺负了,好难过")
    assert "爸爸妈妈" in seen[-1] and "不要提问" in seen[-1]
    pet.answer("恐龙为什么灭绝?")
    assert "爸爸妈妈" not in seen[-1]



def test_noise_is_not_answered_and_a_lone_word_is_asked_again(monkeypatch):
    def boom(msgs):
        raise AssertionError("noise must not reach the model")

    monkeypatch.setattr(pipeline, "stream_chat", boom)
    tts = FakeTTS()
    pet = Pet(asr=None, tts=tts, player=FakePlayer())
    for noise in ["Ha ha ha!", "嗯。", "Um.", "Laughing.", "呃。"]:
        turn = pet.answer(noise)
        assert turn.ignored and not tts.spoken and not pet.history
    turn = pet.answer("Incluso.")
    assert tts.spoken == ["Hmm, I didn't catch that.", "Can you say it again?"]


def test_short_answer_counts_when_the_pet_asked(monkeypatch):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["对啦,每人十块!"]))
    tts = FakeTTS()
    pet = Pet(asr=None, tts=tts, player=FakePlayer())
    pet.followup.pending_question = True  # the pet asked "每人能分到几块?"
    pet.answer("十。")
    assert tts.spoken == ["对啦,每人十块!"]


def test_program_disclaimer_only_when_asked(monkeypatch):
    reply = ["你说得对!", "不过皮卡丘没有感情,不会觉得开心哦。"]
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(reply))
    tts = FakeTTS()
    pet = Pet(asr=None, tts=tts, player=FakePlayer())
    pet.answer("我算对了吧,二加二等于四")
    assert tts.spoken == ["你说得对!"]
    tts.spoken.clear()
    reply[:] = ["我是程序,不是真的皮卡丘。"]
    pet.answer("你是真的皮卡丘吗?")
    assert tts.spoken == ["我是程序,不是真的皮卡丘。"]
