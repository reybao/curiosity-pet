"""Riddles: from the local bank, no repeats, answer withheld until the child answers or gives up."""

import random

import numpy as np

from curiosity_pet import pipeline
from curiosity_pet.pipeline import Pet
from curiosity_pet.riddles import Riddle, RiddleGame, normalize, wants_riddle
from curiosity_pet.store import Store

BANK = {
    "zh": [
        Riddle("zh-1", "什么东西越洗越脏?", "水", ["水", "洗澡水"], "想想你洗手的时候,什么变脏了?", "zh"),
        Riddle("zh-2", "什么车没有轮子?", "风车", ["风车"], "它在风里转。", "zh"),
    ],
    "en": [
        Riddle("en-1", "What has hands but cannot clap?", "a clock", ["clock", "a clock", "watch"], "It tells the time.", "en"),
        Riddle("en-2", "What gets wetter the more it dries?", "a towel", ["towel", "a towel"], "You use it after a bath.", "en"),
    ],
}


def game(store=None, judge=None, seed=1):
    return RiddleGame(bank=BANK, store=store, judge=judge, rng=random.Random(seed))


def test_detects_requests():
    assert wants_riddle("给我出个脑筋急转弯") and wants_riddle("考考我") and wants_riddle("Tell me a riddle")
    assert not wants_riddle("为什么天空是蓝色的?")


def test_question_is_spoken_without_the_answer():
    g = game()
    said = g.next("zh")
    assert said.startswith("来一个脑筋急转弯:") and "水" not in said and "风车" not in said
    assert g.pending is not None


def test_correct_answer_including_phrasing_variants():
    g = game()
    g.next("en")
    target = g.pending
    for text in [target.a, f"Is it {target.a}?", target.accept[0].capitalize() + "!"]:
        g.pending = target
        out = g.answer(text)
        assert out.correct and out.resolved and target.a in out.text
    assert normalize("是不是水?") == "水" and normalize("It's a clock.") == "clock"


def test_wrong_answer_gets_one_hint_then_the_answer():
    g = game()
    g.next("zh")
    r = g.pending
    first = g.answer("是鞋子")
    assert not first.resolved and r.hint in first.text and r.a not in first.text
    second = g.answer("是袜子")
    assert second.resolved and not second.correct and r.a in second.text


def test_giving_up_reveals_and_changing_subject_drops():
    g = game()
    g.next("zh")
    r = g.pending
    out = g.answer("不知道,告诉我吧")
    assert out.resolved and r.a in out.text and g.pending is None
    g.next("zh")
    out = g.answer("为什么天空是蓝色的?")
    assert out.dropped and out.text == "" and g.pending is None


def test_no_repeats_until_the_bank_is_exhausted(tmp_path):
    s = Store(tmp_path / "pet.db")
    seen = []
    for _ in range(2):
        g = game(store=s)  # a new session each time still avoids repeats
        g.next("zh")
        seen.append(g.pending.id)
    assert sorted(seen) == ["zh-1", "zh-2"]
    g = game(store=s)
    g.next("zh")
    assert g.pending.id in ("zh-1", "zh-2")  # bank exhausted: starts over instead of giving nothing


def test_model_judge_is_used_for_near_misses():
    calls = []

    def judge(r, text):
        calls.append(text)
        return text == "一种你可以喝的液体"

    g = game(judge=judge)
    g.next("zh")
    out = g.answer("一种你可以喝的液体")
    assert out.correct and calls == ["一种你可以喝的液体"]


# ---------- natural conversation through the pipeline ----------


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class FakePlayer:
    def play(self, audio, text=None, on_start=None):
        pass


def make_pet(monkeypatch, **kw):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["好的。"]))
    tts = FakeTTS()
    return Pet(asr=None, tts=tts, player=FakePlayer(), riddles=game(**kw)), tts


def test_pet_asks_waits_and_judges(monkeypatch):
    pet, tts = make_pet(monkeypatch)
    pet.answer("给我出个脑筋急转弯")
    assert tts.spoken[-1].startswith("来一个脑筋急转弯:") and tts.spoken[-1].endswith("?")
    riddle = pet.riddles.pending
    tts.spoken.clear()
    pet.answer("是鞋子吧")
    assert riddle.hint in "".join(tts.spoken) and pet.riddles.pending is riddle
    tts.spoken.clear()
    turn = pet.answer(riddle.a)
    assert "答对了" in tts.spoken[-1] and pet.riddles.pending is None
    assert turn.topic == "riddle"


def test_another_one_gives_a_different_riddle(monkeypatch):
    pet, tts = make_pet(monkeypatch)
    pet.answer("Tell me a riddle")
    first = pet.riddles.pending
    pet.answer(first.a)
    pet.answer("Another one!")
    assert pet.riddles.pending is not None and pet.riddles.pending.id != first.id


def test_changing_subject_mid_riddle_answers_the_new_question(monkeypatch):
    pet, tts = make_pet(monkeypatch)
    pet.answer("考考我")
    tts.spoken.clear()
    pet.answer("为什么天空是蓝色的?")
    assert tts.spoken == ["好的。"] and pet.riddles.pending is None


# ---------- the child poses a riddle (real messages from the child's use) ----------

import pytest  # noqa: E402

from curiosity_pet.riddles import child_poses, has_riddle_content  # noqa: E402


def test_riddle_glued_to_chinese_is_a_request():
    # "说一个Riddle" went to the model, which made up a riddle and gave the answer away at once
    assert wants_riddle("你说一个Riddle。") and wants_riddle("小朋友,你能不能说一个Riddle?")


@pytest.mark.parametrize("text, content", [
    ("我能不能给你问一个Riddle?", False),
    ("我给你出个脑筋急转弯", False),
    ("I have a riddle for you.", False),
    ("My riddle is: What.", False),
    ("嘿嘿,我给你出一个脑筋急转弯。我不是人,你说我是谁?", True),
    ("I have a riddle, can you answer my riddle? I am not a person, so who am I?", True),
    ("我考考你,什么东西越洗越脏?", True),
])
def test_child_posing_a_riddle(text, content):
    assert child_poses(text) and not wants_riddle(text)
    assert has_riddle_content(text) is content


def test_requests_are_not_mistaken_for_posing():
    for text in ["给我出个脑筋急转弯", "你说一个Riddle。", "Tell me a riddle", "考考我"]:
        assert not child_poses(text), text


def capture_pet(monkeypatch, reply):
    sent = []

    def fake_stream(msgs):
        sent.append(msgs[-1]["content"])
        return iter([reply])

    monkeypatch.setattr(pipeline, "stream_chat", fake_stream)
    tts = FakeTTS()
    return Pet(asr=None, tts=tts, player=FakePlayer(), riddles=game()), tts, sent


def test_pet_says_go_ahead_then_guesses_and_never_poses_back(monkeypatch):
    pet, tts, sent = capture_pet(monkeypatch, "我猜是影子,对不对?")
    turn = pet.answer("我能不能给你问一个Riddle?")
    assert tts.spoken == ["好呀,你出吧,我来猜!"] and not sent and turn.topic == "riddle"
    tts.spoken.clear()
    pet.answer("我不是人,我是谁?")
    assert "孩子在给你出谜语" in sent[-1]
    assert tts.spoken == ["我猜是影子,对不对?"]  # the question is kept: it belongs to guessing
    assert pet.riddles.pending is None  # no riddle of its own
    tts.spoken.clear()
    pet.answer("不对,我是小猫")
    assert "孩子在说你刚才猜得对不对" in sent[-1]


def test_riddle_with_content_is_guessed_at_once_without_lookup(monkeypatch):
    pet, tts, sent = capture_pet(monkeypatch, "My guess is a ghost. Am I right?")

    class Boom:
        def decide(self, *a):
            raise AssertionError("a child's riddle must not be looked up")

    pet.researcher = Boom()
    pet.answer("Could you answer my riddle? I am not a human being, so who am I?")
    assert "The child is giving you a riddle" in sent[-1]
    assert " ".join(tts.spoken) == "My guess is a ghost. Am I right?"  # the question is kept
    assert pet.riddles.pending is None


def test_asking_for_a_riddle_after_guessing_gets_one_from_the_bank(monkeypatch):
    pet, tts, sent = capture_pet(monkeypatch, "我猜是水。")
    pet.answer("我考考你,什么东西越洗越脏?")
    tts.spoken.clear()
    pet.answer("你说一个Riddle。")
    assert tts.spoken[-1].startswith("来一个脑筋急转弯:") and pet.riddles.pending is not None


def test_only_one_question_when_guessing(monkeypatch):
    # "越长越短" is not in the bank, so the model guesses (a bank riddle is answered by the program, see below)
    pet, tts, sent = capture_pet(monkeypatch, "我猜是蜡烛,因为点着它就变短。我猜对了吗?今天你吃了什么好吃的呀?")
    pet.answer("我考考你,什么东西越长越短?")
    assert "".join(tts.spoken) == "我猜是蜡烛,因为点着它就变短。我猜对了吗?"


def test_reply_to_her_answer_follows_the_usual_question_limit(monkeypatch):
    pet, tts, sent = capture_pet(monkeypatch, "我猜是影子。我猜对了吗?")
    pet.answer("我考考你,我不是人,我是谁?")
    pet.followup.off = True  # e.g. she said "stop asking" earlier
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["原来是小猫,这个谜语真有意思!你最喜欢吃什么呢?"]))
    tts.spoken.clear()
    pet.answer("不对,我是小猫。")
    assert "".join(tts.spoken) == "原来是小猫,这个谜语真有意思!"


def test_guessing_stops_at_the_question(monkeypatch):
    pet, tts, sent = capture_pet(monkeypatch, "我猜是梳子。我猜对了吗?因为我们的毛摸起来像蓝色的云朵。")
    pet.answer("我考考你,什么东西有很多牙齿却不会咬人?")
    assert "".join(tts.spoken) == "我猜是梳子。我猜对了吗?"


# ---------- The child tells a classic the pet knows, with or without announcing it ----------

from curiosity_pet.riddles import load_bank, looks_like_riddle  # noqa: E402

def test_bank_riddle_is_recognized_in_other_words():
    game = RiddleGame(bank=load_bank())
    assert game.recognize("What has hands but cannot grab things?", "en").a == "a clock"  # from real use
    assert game.recognize("我考考你,什么东西越洗越脏呀?", "zh").a == "水"
    assert game.recognize("一口咬掉牛尾巴是什么字?", "zh").a == "告"
    assert game.recognize("什么东西越长越短?", "zh") is None  # only the shared "什么东西...越" is alike
    assert game.recognize("What has stripes and lives in the zoo?", "en") is None


def test_riddle_forms_without_an_announcement():
    for text in ["What has hands but cannot grab things?", "什么东西越长越短?", "一口咬掉牛尾巴,打一个字。",
                 "I have four legs and I bark. What am I?", "什么东西有脚却不会走路?"]:
        assert looks_like_riddle(text), text
    for text in ["什么东西会飞?", "What has stripes?", "为什么天空是蓝色的?", "What is a black hole?", "Who is Pikachu?"]:
        assert not looks_like_riddle(text), text


def test_pet_answers_a_known_riddle_without_the_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a riddle from the bank is answered by the program")

    monkeypatch.setattr(pipeline, "stream_chat", boom)
    pet, tts, sent = capture_pet(monkeypatch, "")
    monkeypatch.setattr(pipeline, "stream_chat", boom)
    turn = pet.answer("What has hands but cannot grab things?")
    assert " ".join(tts.spoken) == "I know this one! Is it a clock? Am I right?" and turn.topic == "riddle"
    assert pet.riddles.child_stage == "guessing"  # her "yes!" or "no" is taken as the reply to the guess


def test_unknown_unannounced_riddle_is_guessed_not_looked_up(monkeypatch):
    pet, tts, sent = capture_pet(monkeypatch, "我猜是蜡烛。我猜对了吗?")
    pet.researcher = type("R", (), {"decide": lambda *a: (_ for _ in ()).throw(AssertionError("no lookup for a riddle"))})()
    pet.answer("什么东西越长越短?")
    assert "".join(tts.spoken) == "我猜是蜡烛。我猜对了吗?"


def test_announced_riddle_with_its_text_is_answered_at_once(monkeypatch):
    # Live run: "我考考你,一口咬掉牛尾巴,打一个字。" got "好呀,你出吧" because the riddle had no question word
    assert has_riddle_content("我考考你,一口咬掉牛尾巴,打一个字。")
    pet, tts, sent = capture_pet(monkeypatch, "")
    pet.riddles = RiddleGame(bank=load_bank())  # the real bank holds this character riddle
    pet.answer("我考考你,一口咬掉牛尾巴,打一个字。")
    assert "".join(tts.spoken) == "这个我知道!是告!我猜对了吗?"


# ---------- false triggers seen in the parent's test session (18:11 to 18:22) ----------

from curiosity_pet.riddles import could_be_told_riddle, wants_another  # noqa: E402


def test_mentioning_riddles_without_wanting_one():
    for text in ["But what I didn't talk some um riddle with you, I just said, yes",
                 "What I didn't ask you a riddle. Okay, bro.", "我没有跟你说谜语", "我不想猜谜语了"]:
        assert not wants_riddle(text) and not child_poses(text), text
    assert wants_riddle("你说一个Riddle。") and wants_riddle("Tell me a riddle")


def test_another_question_is_not_another_riddle():
    assert not wants_another("Okay, I feel sad, and but I have another question.")
    assert wants_another("Another one!") and wants_another("再来一个")


def test_a_long_remark_is_not_a_bank_riddle(monkeypatch):
    remark = ("See a picture. Because if I say I want to see a picture of a big green apple, you cannot show me. "
              "Right, you can just speak with me.")
    assert not could_be_told_riddle(remark)
    assert could_be_told_riddle("What has an eye but cannot see?")


def test_a_long_remark_during_a_riddle_is_not_a_wrong_answer(monkeypatch):
    pet, tts = make_pet(monkeypatch)
    pet.answer("给我出个脑筋急转弯")
    riddle = pet.riddles.pending
    tts.spoken.clear()
    pet.answer("You know a lot of things, but if you keep getting answers wrong, how can kids learn from you "
               "and trust you as a good friend")
    assert riddle.a not in "".join(tts.spoken) and pet.riddles.pending is None
