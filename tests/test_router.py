"""Is a doubtful message meant for the pet (router.py), and the rule-based end of activities in the pipeline.
The model is faked here; the real one is measured by evals/replay_eval.py --router."""

import numpy as np

from curiosity_pet import call_parent, pipeline
from curiosity_pet.pipeline import Pet, still_about_her_riddle
from curiosity_pet.router import Router, activity_of, doubtful

CALL_SET = {"call_parent": {"telegram": {"bot_token": "t", "chat_ids": {"dad": "d", "mom": "m"}}}}


def test_only_doubtful_messages_are_checked():
    assert doubtful("十。", "chat") and doubtful("他刚才在笑,他想让你听。", "chat")
    assert doubtful("Two hundred feet. Turn left onto it.", "chat")
    assert not doubtful("为什么天空是蓝色的呀,我一直想知道", "chat")
    assert not doubtful("十。", "pet_question")  # the pet asked: a short reply is expected
    assert not doubtful("要。", "call_confirm")


def test_classify_is_conservative():
    assert Router(judge=lambda t: " side").classify("x") == "side"
    assert Router(judge=lambda t: "Garbled.").classify("x") == "garbled"
    assert Router(judge=lambda t: "maybe").classify("x") == "chat"

    def boom(t):
        raise OSError("ollama down")

    assert Router(judge=boom).classify("x") == "chat"  # a failure never drops a real question


class TTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class Player:
    def play(self, audio, text=None, on_start=None):
        pass


def make(monkeypatch, labels, reply="好的。"):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter([reply]))
    asked = []

    def judge(text):
        asked.append(text)
        return labels.get(text, "chat")

    tts = TTS()
    pet = Pet(asr=None, tts=tts, player=Player(), router=Router(judge=judge))
    pet.calls = call_parent.CallParent("ipad", None, send=lambda o, c, t: True, limit=call_parent.RateLimit(),
                                       settings=lambda: CALL_SET, judge=None)
    return pet, tts, asked


def test_side_talk_is_ignored_and_garble_is_asked_again(monkeypatch):
    pet, tts, asked = make(monkeypatch, {"他刚才在笑,他想让你听。": "side", "好,开丑。": "garbled"})
    turn = pet.answer("他刚才在笑,他想让你听。")
    assert turn.ignored and turn.route == "ignore" and tts.spoken == []
    turn = pet.answer("好,开丑。")
    assert turn.route == "clarify" and "没听清" in "".join(tts.spoken)
    pet.answer("为什么天空是蓝色的呀,我一直想知道")
    assert asked == ["他刚才在笑,他想让你听。", "好,开丑。"]  # a clear question is not checked at all


def test_a_riddle_ends_when_she_asks_for_daddy_or_says_goodbye(monkeypatch):
    pet, tts, _ = make(monkeypatch, {}, reply="我猜是钟。我猜对了吗?")
    pet.answer("我考考你,什么东西有很多牙齿却不会咬人?")
    assert activity_of(pet) == "child_riddle_guessed"
    tts.spoken.clear()
    turn = pet.answer("你可以帮我叫一下爸爸吗?")
    assert turn.route == "call" and pet.riddles.child_stage is None
    assert "".join(pet.answer("要。").sentences) == "好的,我已经告诉爸爸了。"
    pet.answer("我考考你,什么东西越洗越脏?")
    assert pet.answer("好,谢谢,拜拜。").route == "goodbye"


def test_what_still_counts_as_a_reply_to_the_pets_guess():
    for reply in ["对了!", "不对,是小猫", "Yes!", "不是"]:
        assert still_about_her_riddle(reply), reply
    for other in ["你可以帮我叫一下爸爸吗?", "好,谢谢,拜拜。", "Which one is the biggest ocean in this world?", "讲个故事吧"]:
        assert not still_about_her_riddle(other), other


def test_laughter_is_never_an_answer_but_a_lone_yes_is(monkeypatch):
    pet, tts, asked = make(monkeypatch, {})
    pet.followup.pending_question = True
    turn = pet.answer("Ha ha ha!")
    assert turn.ignored and asked == []
    assert pet.answer("ふふふ。").ignored
    pet.answer("我要找妈妈。")
    assert "".join(pet.answer("嗯。").sentences) == "好的,我已经告诉妈妈了。"
