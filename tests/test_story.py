"""Story and bedtime modes: the child picks who and where, original stories, no lookup, bedtime slows down and ends."""

import numpy as np

from curiosity_pet import pipeline
from curiosity_pet.pipeline import Pet
from curiosity_pet.story import request


def test_requests():
    assert request("讲故事。") == ("story", "")
    assert request("讲一个小兔子在森林里的故事") == ("story", "小兔子在森林里")
    assert request("我想听睡前故事,主角是小猫") == ("bedtime", "小猫")
    assert request("Tell me a story about a dragon who loves math") == ("story", "a dragon who loves math")
    for not_story in ["给我讲个成语故事", "你说说克林还有武天老师的故事", "七龙珠里的故事是什么", "为什么会打雷?"]:
        assert request(not_story) is None, not_story


class TTS:
    def __init__(self):
        self.spoken, self.speed, self.speeds = [], 1.0, []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        self.speeds.append(self.speed)
        return np.zeros(10, dtype=np.float32)


class Player:
    def play(self, audio, text=None, on_start=None):
        pass


def test_asks_who_then_tells_an_original_story_without_lookup(monkeypatch):
    sent = []
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: sent.append(msgs[-1]["content"]) or iter(["从前有一只小兔子。"]))

    class Boom:
        def decide(self, *a):
            raise AssertionError("stories are never looked up")

    tts = TTS()
    pet = Pet(asr=None, tts=tts, player=Player(), researcher=Boom())
    pet.answer("给我讲个故事吧")
    assert "".join(tts.spoken) == "好呀!故事的主角是谁?在哪里发生呢?" and not sent
    pet.answer("小兔子,在森林里")
    assert "原创" in sent[-1] and "小兔子,在森林里" in sent[-1] and "不要提问" in sent[-1]
    assert tts.spoken[-1] == "从前有一只小兔子。" and pet.story_waiting is None


def test_bedtime_is_slower_says_goodnight_and_ends(monkeypatch):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["小猫在窗边看星星。最后它安心地睡着了。"]))
    tts = TTS()
    pet = Pet(asr=None, tts=tts, player=Player())
    turn = pet.answer("讲个睡前故事,主角是小猫")
    assert tts.spoken[-1] == "晚安,做个好梦。" and turn.ended
    assert set(tts.speeds) == {0.85} and tts.speed == 1.0
    assert pet.history == []


def test_dialogue_questions_stay_in_the_story(monkeypatch):
    monkeypatch.setattr(pipeline, "stream_chat",
                        lambda msgs: iter(["小猫小声问:“是谁在那里?”", "原来是萤火虫。", "你喜欢萤火虫吗?"]))
    tts = TTS()
    Pet(asr=None, tts=tts, player=Player()).answer("讲一个小猫在花园里的故事")
    said = "".join(tts.spoken)
    assert "是谁在那里" in said and "你喜欢萤火虫吗" not in said


def test_worries_and_commands_are_not_woven_into_stories():
    from curiosity_pet.pipeline import story_topic_ok

    assert story_topic_ok("恐龙为什么会灭绝?")
    for text in ["我想打我弟弟", "我今天好难过", "收藏这个", "我喜欢恐龙", "你会记住我说的话吗?", "开。", "Ha ha ha!"]:
        assert not story_topic_ok(text), text
