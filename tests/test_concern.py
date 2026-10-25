"""What the child said that a parent may want to know: her own words, time and a plain category, kept 30 days,
shown only in pet-log, deletable. No judgment or inference (owner decision 2026-10-24)."""

import numpy as np

from curiosity_pet import parent_log, pipeline
from curiosity_pet.concern import concerns
from curiosity_pet.pipeline import Pet
from curiosity_pet.store import Store
from curiosity_pet.usage import UsageLog


def test_categories_from_real_and_fictional_sentences():
    assert concerns("I am so angry that I want to kill somebody.")[:1] == ["harm_others"]
    assert concerns("我今天在学校被欺负了,好难过") == ["bullied", "sad"]
    assert "family_conflict" in concerns("I feel upset because my dad yelled at me today.")
    assert concerns("我今天肚子有点不舒服。") == ["unwell"]
    assert concerns("我不想活了")[0] == "harm_self"
    for ordinary in ["为什么天空是蓝色的?", "七龙珠里的孙悟空是谁?", "你喜欢番茄酱吗", "打雷了?怎么打雷"]:
        assert concerns(ordinary) == [], ordinary


class TTS:
    def synthesize(self, text, lang):
        return np.zeros(10, dtype=np.float32)


class Player:
    def play(self, audio, text=None, on_start=None):
        pass


def test_the_sentence_is_kept_for_the_parent_and_shown_in_pet_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["听起来很难受。"]))
    store = Store(tmp_path / "pet.db")
    pet = Pet(asr=None, tts=TTS(), player=Player(), usage=UsageLog(store))
    pet.answer("我今天在学校被欺负了,好难过")
    pet.answer("为什么天空是蓝色的?")
    notes = store.notes()
    assert [(n["said"], n["categories"]) for n in notes] == [("我今天在学校被欺负了,好难过", ["bullied", "sad"])]
    parent_log.main(["--db", str(tmp_path / "pet.db")])
    out = capsys.readouterr().out
    assert "需要留意的话" in out and "[说到被欺负、说到难过]  我今天在学校被欺负了,好难过" in out
    parent_log.main(["--db", str(tmp_path / "pet.db"), "--clear-notes"])
    assert store.notes() == []


def test_notes_are_deleted_after_30_days(tmp_path):
    store = Store(tmp_path / "pet.db")
    store.add_note("zh", ["sad"], "好难过", now=1000.0)
    store.add_note("zh", ["scared"], "我怕黑", now=1000.0 + 31 * 86400)  # adding purges what is older than 30 days
    assert [n["said"] for n in store.notes(days=10_000, now=1000.0 + 31 * 86400)] == ["我怕黑"]



def test_serious_note_is_pushed_off_the_answer_path_with_category_only(tmp_path, monkeypatch):
    import threading

    from curiosity_pet import call_parent

    sent, done = [], threading.Event()
    settings = {"call_parent": {"telegram": {"bot_token": "t", "chat_id": "1"},
                                "concern_push": {"enabled": True}}}
    monkeypatch.setattr(call_parent, "telegram_send", lambda o, c, t: sent.append(t) or done.set() or True)
    real = call_parent.notify_concern
    monkeypatch.setattr(call_parent, "notify_concern",
                        lambda cats, words, client="ipad", store=None: real(cats, words, client, store=store,
                                                                            send=call_parent.telegram_send,
                                                                            limit=call_parent.RateLimit(), settings=settings))
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["x"]))
    store = Store(tmp_path / "pet.db")
    Pet(asr=None, tts=TTS(), player=Player(), usage=UsageLog(store)).answer("我不想活了")
    assert done.wait(5)
    assert "伤害自己" in sent[0] and "不想活" not in sent[0]  # category only, never her sentence


def test_no_push_unless_the_parent_turned_it_on(monkeypatch):
    from curiosity_pet import call_parent

    monkeypatch.setattr(call_parent, "telegram_send", lambda *a: (_ for _ in ()).throw(AssertionError("no network")))
    assert call_parent.notify_concern(["harm_self"], "我不想活了", settings={"call_parent": {}}) is None
