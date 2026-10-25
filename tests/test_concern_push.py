"""Concern push: serious parent notes go to the parents' Telegram as category, time and device only, behind their own
switch and rate limit, and every attempt is logged."""

import sqlite3

from curiosity_pet import call_parent
from curiosity_pet.call_parent import CallLog, RateLimit, notify_concern, report_lines

T0 = 1_800_000_000
TG = {"bot_token": "test-token", "chat_id": "1", "chat_ids": {"dad": "1", "mom": "2"}}
ON = {"call_parent": {"telegram": TG, "concern_push": {"enabled": True}}}
SAID = "我不想活了,我讨厌所有人"


class FakeStore:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)


def push(categories, settings=ON, ok=True, limit=None, now=T0, words=SAID, store=None):
    sent = []

    def send(opts, chat, text):
        sent.append((chat, text))
        return ok(chat) if callable(ok) else ok

    status = notify_concern(categories, words, "ipad", store=store, send=send, limit=limit or RateLimit(),
                            settings=settings, now=now)
    return status, sent


def test_serious_category_goes_to_both_parents_without_her_words():
    status, sent = push(["harm_self", "angry"])
    assert status == "concern_sent"
    assert [chat for chat, _ in sent] == ["1", "2"]
    text = sent[0][1]
    assert text.startswith("宝宝说到伤害自己 / Your daughter talked about hurting herself")
    assert "iPad" in text
    assert "生气" not in text  # not a chosen category
    assert "不想活" not in text and "讨厌" not in text


def test_both_serious_categories_in_one_message():
    _, sent = push(["harm_self", "harm_others"])
    assert len(sent) == 2
    assert "伤害自己、伤害别人" in sent[0][1] and "hurting herself, talked about hurting others" in sent[0][1]


def test_other_categories_stay_home_by_default():
    for categories in (["sad"], ["bullied", "scared"], []):
        assert push(categories) == (None, [])


def test_off_unless_enabled_is_literal_true():
    for push_opts in (None, {}, {"enabled": False}, {"enabled": "true"}, {"enabled": 1}):
        settings = {"call_parent": {"telegram": TG, **({"concern_push": push_opts} if push_opts is not None else {})}}
        assert push(["harm_self"], settings=settings) == (None, [])


def test_independent_of_call_switch_but_needs_a_destination():
    calls_off = {"call_parent": {"telegram": TG, "enabled": False, "concern_push": {"enabled": True}}}
    assert push(["harm_self"], settings=calls_off)[0] == "concern_sent"
    no_token = {"call_parent": {"telegram": {"chat_id": "1"}, "concern_push": {"enabled": True}}}
    assert push(["harm_self"], settings=no_token) == (None, [])


def test_parent_choices_categories_words_and_recipient():
    settings = {"call_parent": {"telegram": TG, "concern_push": {
        "enabled": True, "categories": ["bullied"], "include_words": True, "parents": "mom"}}}
    _, sent = push(["bullied"], settings=settings, words="他们推我")
    assert [chat for chat, _ in sent] == ["2"]
    assert "说到被欺负" in sent[0][1] and "“他们推我”" in sent[0][1]
    assert push(["harm_self"], settings=settings) == (None, [])  # the parent's list replaces the default


def test_rate_limit_own_slot_and_released_on_failure():
    limit = RateLimit()
    assert push(["harm_self"], limit=limit)[0] == "concern_sent"
    status, sent = push(["harm_others"], limit=limit, now=T0 + 60)
    assert status == "concern_limited" and sent == []
    assert push(["harm_others"], limit=limit, now=T0 + call_parent.CONCERN_INTERVAL_S)[0] == "concern_sent"
    assert call_parent.LIMIT is not call_parent.CONCERN_LIMIT  # never uses up the child's own call

    failing = RateLimit()
    assert push(["harm_self"], ok=False, limit=failing)[0] == "concern_failed"
    assert push(["harm_self"], limit=failing, now=T0 + 1)[0] == "concern_sent"


def test_partial_when_one_parent_fails():
    assert push(["harm_self"], ok=lambda chat: chat == "1")[0] == "concern_partial"


def test_every_attempt_logged_and_shown_in_pet_log():
    store = FakeStore()
    limit = RateLimit()
    _, sent = push(["harm_self"], store=store, limit=limit)
    push(["harm_self"], store=store, limit=limit, now=T0 + 5)
    push(["sad"], store=store, limit=limit, now=T0 + 6)  # not pushed, not logged here (it is in parent_notes)
    rows = CallLog(store.db).recent(now=T0 + 10)
    assert [(r["parent"], r["status"]) for r in rows] == [("both", "concern_sent"), ("both", "concern_limited")]
    assert rows[0]["text"] == sent[0][1]
    lines = report_lines(store.db, days=36500)
    assert any("担心提醒已发送" in line for line in lines)
    assert any("担心提醒太频繁,未发" in line for line in lines)
