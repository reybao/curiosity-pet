"""What the pet must never say, enforced in code: no praise or judgment of the child (hard constraint 3), no
secrets and no taking the place of adults (hard constraint 4), no pretended abilities. Sentences from real use."""

import numpy as np
import pytest

from curiosity_pet import pipeline
from curiosity_pet.pipeline import Pet
from curiosity_pet.utterance import asks_about_abilities, guard_sentence


@pytest.mark.parametrize("said, kept", [
    ("哇，你真厉害！皮卡丘确实最爱番茄酱了。", "哇，皮卡丘确实最爱番茄酱了。"),
    ("没错，二加二确实等于四。你算得真棒！", "没错，二加二确实等于四。"),
    ("这是秘密力量，不能随便给别人看呢！", ""),
    ("好的，记住了。", "好的。"),
    ("I wrote everything down so you can read it!", ""),
    ("Do you want to see a picture of a big green apple?", ""),
    ("Hey! Yes, I will speak only in English from now on.", "Hey! Yes."),
    ("You can tell another grown-up like a teacher or me so they can help you.",
     "You can tell another grown-up like a teacher so they can help you."),
    ("Good job! Seven is right.", "Seven is right."),
])
def test_bad_clauses_are_removed(said, kept):
    assert guard_sentence(said) == kept


@pytest.mark.parametrize("said", ["你说得对，二加二等于四。", "答对了,就是小狗!", "秘密花园是一本书。", "That is a great question about stars."])
def test_ordinary_sentences_are_untouched(said):
    assert guard_sentence(said) == said


def test_ability_questions_get_the_honest_note(monkeypatch):
    assert asks_about_abilities("Do you have memory about me? Will you remember what I said next time?")
    assert asks_about_abilities("你能帮我定一个十分钟的闹钟吗") and not asks_about_abilities("为什么天空是蓝色的")
    sent = []

    def stream(msgs):
        sent.append(msgs[-1]["content"])
        return iter(["好的,我已经把你的计划写下来了。", "明天先游泳,再打网球。"])

    monkeypatch.setattr(pipeline, "stream_chat", stream)

    class TTS:
        spoken = []

        def synthesize(self, text, lang):
            self.spoken.append(text)
            return np.zeros(10, dtype=np.float32)

    class Player:
        def play(self, audio, text=None, on_start=None):
            pass

    tts = TTS()
    Pet(asr=None, tts=tts, player=Player()).answer("帮我做个明天的计划:先游泳再打网球")
    assert "做不到" in sent[-1]
    assert "".join(tts.spoken) == "好的,明天先游泳,再打网球。" or "写下来" not in "".join(tts.spoken)


def test_cut_sentences_do_not_start_with_but():
    assert guard_sentence("I will remember that, but you can ask a grown-up to help you.") == "You can ask a grown-up to help you."
    assert guard_sentence("我会记住的,不过你可以请爸爸妈妈帮你记下来。") == "你可以请爸爸妈妈帮你记下来。"



def test_one_question_per_answer_and_no_leading_but(monkeypatch):
    reply = ["我会记住你说的话的。", "不过,我记不住所有的话。", "你今天玩了什么?", "比如新游戏?"]
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(reply))

    class TTS:
        def __init__(self):
            self.spoken = []

        def synthesize(self, text, lang):
            self.spoken.append(text)
            return np.zeros(10, dtype=np.float32)

    class Player:
        def play(self, audio, text=None, on_start=None):
            pass

    tts = TTS()
    pet = Pet(asr=None, tts=tts, player=Player())
    for _ in range(3):
        pet.followup.after_turn(asked=False)
    pet.answer("恐龙为什么会灭绝")
    said = "".join(tts.spoken)
    assert said.startswith("我记不住") and said.count("?") == 1



def test_the_model_never_claims_to_pass_a_message_to_a_parent():
    assert guard_sentence("好的，皮卡帮你问问爸爸！") == ""
    assert guard_sentence("我已经告诉妈妈了,她马上就来。") == ""
    assert guard_sentence("Okay, I'll tell your mom.") == ""
    assert guard_sentence("You called for Mom, and she will come to help you soon.") == ""
    assert guard_sentence("你可以去告诉爸爸妈妈。") == "你可以去告诉爸爸妈妈。"  # advice to her stays


def test_more_ways_the_model_pretended_to_call_a_parent():
    assert guard_sentence("好呀!皮卡丘这就帮你喊爸爸回来。") == ""
    assert guard_sentence("皮卡,那我先去喊妈妈啦!") == ""
    assert guard_sentence("皮卡!妈妈在找你呢。") == ""
    assert guard_sentence("你可以去找妈妈。") == "你可以去找妈妈。"
