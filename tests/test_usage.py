"""Usage log: factual records of each exploration and each question; raw answers are deleted after 7 days; no evaluative fields."""

import pytest

from curiosity_pet.pipeline import Turn
from curiosity_pet.store import LOG_RETENTION_S, Store
from curiosity_pet.usage import UsageLog, classify_follow_up

T0 = 1_800_000_000
DAY = 24 * 3600


@pytest.mark.parametrize(
    "text, kind",
    [
        ("再简单一点", "simpler"),
        ("我听不懂", "simpler"),
        ("Can you make it simpler?", "simpler"),
        ("举个例子", "example"),
        ("Give me an example", "example"),
        ("你怎么知道的?", "how_know"),
        ("真的吗?", "how_know"),
        ("How do you know?", "how_know"),
        ("你说错了", "correction"),
        ("不对吧,恐龙不是这样的", "correction"),
        ("That's wrong", "correction"),
        ("再讲一点", "more"),
        ("还有呢?", "more"),
        ("Tell me more", "more"),
        ("为什么天空是蓝色的?", None),
        ("恐龙对不对?", None),  # "对不对" is not a correction
        ("Why is the sky blue?", None),
    ],
)
def test_follow_up_classification(text, kind):
    assert classify_follow_up(text) == kind


def make_turn(q, lang="zh", answer="回答。", **kw):
    t = Turn(question=q, lang=lang, answer=answer, sentences=[answer] if answer else [], total_s=2.0, first_audio_s=1.5, asr_s=0.1)
    for k, v in kw.items():
        setattr(t, k, v)
    return t


def test_session_starts_on_first_turn_and_records_facts(tmp_path):
    store = Store(tmp_path / "pet.db")
    log = UsageLog(store, tag_topic=lambda q, lang: "space", client="test")
    log.record(make_turn("黑洞是什么?"), now=T0)
    log.record(make_turn("再简单一点", answer="黑洞就是…"), now=T0 + 30)
    log.end("goodbye", now=T0 + 60)

    sessions = store.recent_sessions(days=7, now=T0 + 60)
    assert len(sessions) == 1
    s = sessions[0]
    assert s["turns"] == 2 and s["end_reason"] == "goodbye" and s["client"] == "test"
    assert s["end_ts"] - s["start_ts"] == 60
    first, second = s["turn_list"]
    assert first["question"] == "黑洞是什么?" and first["topic"] == "space" and first["follow_up"] is None
    assert second["follow_up"] == "simpler"
    assert second["answer"] == "黑洞就是…"
    assert first["first_audio_s"] == 1.5


def test_topic_from_lookup_is_kept_and_model_tagger_only_fills_gaps(tmp_path):
    calls = []

    def tagger(q, lang):
        calls.append(q)
        return "animals"

    log = UsageLog(Store(tmp_path / "pet.db"), tag_topic=tagger)
    log.record(make_turn("七龙珠里的孙悟空是谁?", topic="cartoons_stories"), now=T0)
    log.record(make_turn("猫为什么打呼噜?"), now=T0 + 1)
    turns = log.store.recent_sessions(days=7, now=T0 + 1)[0]["turn_list"]
    assert [t["topic"] for t in turns] == ["cartoons_stories", "animals"]
    assert calls == ["猫为什么打呼噜?"]


def test_tagger_failure_does_not_break_recording(tmp_path):
    def broken(q, lang):
        raise RuntimeError("ollama down")

    log = UsageLog(Store(tmp_path / "pet.db"), tag_topic=broken)
    log.record(make_turn("黑洞是什么?"), now=T0)
    assert log.store.recent_sessions(days=7, now=T0)[0]["turn_list"][0]["topic"] == "other"


def test_answers_are_deleted_after_7_days_but_questions_and_counts_stay(tmp_path):
    store = Store(tmp_path / "pet.db")
    log = UsageLog(store, tag_topic=lambda q, lang: "space")
    log.record(make_turn("黑洞是什么?", answer="黑洞是…"), now=T0)
    log.end("end_button", now=T0 + 10)
    log.record(make_turn("星星为什么眨眼?", answer="因为…"), now=T0 + LOG_RETENTION_S + DAY)

    sessions = store.recent_sessions(days=30, now=T0 + LOG_RETENTION_S + DAY)
    old = [s for s in sessions if s["start_ts"] == T0][0]
    assert old["turn_list"][0]["question"] == "黑洞是什么?"
    assert old["turn_list"][0]["answer"] is None
    assert sum(c["n"] for c in store.topic_counts() if c["topic"] == "space") == 2


def test_stats_are_counts_only(tmp_path):
    store = Store(tmp_path / "pet.db")
    log = UsageLog(store, tag_topic=lambda q, lang: "space")
    log.record(make_turn("黑洞是什么?"), now=T0)
    log.record(make_turn("再简单一点"), now=T0 + 20)
    log.record(make_turn("Why is the sky blue?", lang="en", looked_up=True, source="Sky blue"), now=T0 + 40)
    log.end("goodbye", now=T0 + 60)
    log.record(make_turn("你说错了"), now=T0 + DAY)
    log.end("disconnect", now=T0 + DAY + 5)

    st = store.stats(days=7, now=T0 + DAY + 10)
    assert st["sessions"] == 2 and st["questions"] == 4
    assert st["by_lang"] == {"zh": 3, "en": 1}
    assert st["follow_ups"] == {"simpler": 1, "correction": 1}
    assert st["looked_up"] == 1
    assert st["end_reasons"] == {"goodbye": 1, "disconnect": 1}
    assert st["median_first_audio_s"] == 1.5
    assert st["median_session_s"] == 32.5
    # No evaluative fields at all
    assert not {"score", "mood", "ability", "personality"} & set(st)


def test_follow_up_inherits_previous_topic(tmp_path):
    log = UsageLog(Store(tmp_path / "pet.db"), tag_topic=lambda q, lang: "other")
    log.record(make_turn("小猫为什么会打呼噜?", topic="animals"), now=T0)
    log.record(make_turn("再简单一点"), now=T0 + 10)
    log.end("goodbye", now=T0 + 20)
    log.record(make_turn("再简单一点"), now=T0 + 100)  # First sentence of a new exploration, no prior context to carry over
    sessions = log.store.recent_sessions(days=7, now=T0 + 100)
    assert [t["topic"] for t in sessions[0]["turn_list"]] == ["animals", "animals"]
    assert sessions[1]["turn_list"][0]["topic"] == "other"


def test_record_keeps_what_was_spoken_not_the_raw_model_text():
    from curiosity_pet.pipeline import Turn
    from curiosity_pet.usage import spoken_text

    turn = Turn(question="1+1", lang="zh", answer="你说得对!不过我是程序。你还想问什么?", sentences=["你说得对!"])
    assert spoken_text(turn) == "你说得对!"
    en = Turn(question="hi", lang="en", answer="raw", sentences=["Hello!", "Nice to meet you."])
    assert spoken_text(en) == "Hello! Nice to meet you."
    assert spoken_text(Turn(question="x", lang="zh", answer="原文")) == ""  # nothing was said: not the raw text
