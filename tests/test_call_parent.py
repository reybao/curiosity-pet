"""Call a parent: detection (fixed phrases plus the local-model judge), dad / mom / both routing, confirmation,
rate limit, fixed message, child's words only when allowed."""

import json
import sqlite3

import httpx
import pytest

from curiosity_pet import call_parent
from curiosity_pet.call_parent import (
    CallLog, CallParent, RateLimit, answer_kind, chats_for, detect, mentions_parent, message_text, report_lines,
)

T0 = 1_800_000_000
TG = {"bot_token": "test-token", "chat_id": "1", "chat_ids": {"dad": "1", "mom": "2"}}
CONFIGURED = {"call_parent": {"telegram": TG}}


class FakeStore:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class Judge:
    """Stands in for the local model: fixed verdicts per sentence, "none" otherwise; records every call."""

    def __init__(self, verdicts=None):
        self.verdicts = verdicts or {}
        self.asked = []

    def __call__(self, text, lang):
        self.asked.append(text)
        return self.verdicts.get(text, "none")


def make(settings=CONFIGURED, ok=True, client="ipad", judge=None):
    sent = []

    def send(opts, chat, text):
        sent.append((chat, text))
        return ok(chat) if callable(ok) else ok

    clock = Clock()
    store = FakeStore()
    calls = CallParent(client=client, store=store, send=send, limit=RateLimit(), settings=lambda: settings,
                       clock=clock, judge=judge if judge is not None else Judge())
    return calls, sent, clock, store


# ---------- fixed phrases ----------

@pytest.mark.parametrize(
    "text, parent",
    [
        ("叫爸爸来", "dad"),
        ("叫爸爸来。", "dad"),
        ("告诉妈妈我饿了", "mom"),
        ("你能不能叫妈妈过来?", "mom"),
        ("帮我告诉爸爸我做完作业了", "dad"),
        ("给妈妈打电话", "mom"),
        ("跟爸爸说我想他了", "dad"),
        ("让妈妈过来", "mom"),
        ("让妈妈来一下", "mom"),
        ("我要找妈妈", "mom"),
        ("我想找爸爸", "dad"),
        ("皮卡丘,叫爸爸来", "dad"),
        ("皮卡丘，叫爸爸来。", "dad"),
        ("妈妈,叫爸爸来", "dad"),
        ("叫爸爸妈妈过来", "both"),
        ("叫Daddy来", "dad"),
        ("叫爸妈来", "both"),
        ("叫爸爸和妈妈来", "both"),
        ("告诉大人们我做完了", "both"),
        ("tell daddy I'm done", "dad"),
        ("Tell Daddy I'm done.", "dad"),
        ("tell mommy I'm hungry", "mom"),
        ("Can you call mommy?", "mom"),
        ("Please get my dad", "dad"),
        ("Kitty, tell mom I'm hungry", "mom"),
        ("call mom and dad", "both"),
        ("call daddy and mommy", "both"),
        ("tell my parents I'm done", "both"),
        ("can you call mom and dad", "both"),
        ("我想找 daddy", "dad"),
        ("叫 mommy 来", "mom"),
        ("叫daddy和mommy来", "both"),
        ("告诉 mom 我饿了", "mom"),
    ],
)
def test_detects_requests(text, parent):
    req = detect(text)
    assert req is not None and req.parent == parent


@pytest.mark.parametrize(
    "text",
    [
        "为什么爸爸叫爸爸?",
        "妈妈叫我吃饭",
        "我想和妈妈一起去公园",
        "不要告诉妈妈",
        "别告诉爸爸",
        "Don't tell mom",
        "Why do we call daddy dad?",
        "My dad is tall",
        "爸爸,我饿了",
        "Tell me about dinosaurs",
        "恐龙的妈妈会下蛋吗?",
        "我爸爸是医生",
        "妈妈说我可以看电视",
        "爸爸的生日是几号?",
        "Tell me a moment",
        "my dad is a doctor",
        "mom said I can watch TV",
        "what's daddy's birthday?",
        "我的 daddy 是医生",
    ],
)
def test_fixed_phrases_ignore_other_sentences(text):
    assert detect(text) is None


@pytest.mark.parametrize(
    "text, hit",
    [("爸爸在哪儿", True), ("我要妈妈", True), ("你们快来", True), ("I want my mom and dad", True),
     ("where's daddy", True), ("I want my daddy", True), ("我想 mommy 了", True), ("为什么天空是蓝色的?", False),
     ("我爸爸是医生", False), ("妈妈说我可以看电视", False), ("my dad is a doctor", False), ("爸爸的生日是几号?", False), ("Wait a moment", False), ("Tell me a story", False)],
)
def test_prefilter(text, hit):
    assert mentions_parent(text) is hit


@pytest.mark.parametrize(
    "text, kind",
    [("要", "yes"), ("嗯。", "yes"), ("好的!", "yes"), ("Yes please", "yes"), ("OK.", "yes"),
     ("不要", "no"), ("算了", "no"), ("No.", "no"), ("never mind", "no"),
     ("恐龙有多大?", None), ("why?", None)],
)
def test_answer_kind(text, kind):
    assert answer_kind(text) == kind


# ---------- the model judge ----------

def test_judge_handles_meaning_and_still_asks_first():
    judge = Judge({"爸爸在哪儿": "dad", "我想爸爸了": "dad", "我要妈妈": "mom", "I want my mom and dad": "both"})
    calls, sent, _, _ = make(judge=judge)
    assert calls.handle("爸爸在哪儿", "zh") == "要我告诉爸爸你在找他吗?"
    assert sent == []
    calls.reset()
    assert calls.handle("我要妈妈", "zh") == "要我告诉妈妈你在找她吗?"
    calls.reset()
    assert calls.handle("I want my mom and dad", "en") == "Should I tell Mommy and Daddy you're looking for them?"


def test_english_and_mixed_flow():
    judge = Judge({"I want my daddy": "dad", "where's mommy": "mom", "我想 mommy 了": "mom"})
    calls, sent, clock, _ = make(judge=judge)
    assert calls.handle("I want my daddy", "en") == "Should I tell Daddy you're looking for him?"
    assert calls.handle("好", "en") == "Okay, I told Daddy."  # a Chinese yes counts too
    calls.limit.last_sent = None
    assert calls.handle("where's mommy", "en") == "Should I tell Mommy you're looking for her?"
    assert calls.handle("nope", "en") == "Okay, I won't send it."
    assert calls.handle("我想 mommy 了", "zh") == "要我告诉妈妈你在找她吗?"
    assert calls.handle("yes", "zh") == "好的,我已经告诉妈妈了。"  # an English yes in a Chinese turn
    assert [c for c, _ in sent] == ["1", "2"]
    for text in ("my dad is a doctor", "mom said I can watch TV", "what's daddy's birthday?"):
        assert calls.handle(text, "en") is None


def test_judge_none_means_normal_answer():
    judge = Judge()
    calls, sent, _, _ = make(judge=judge)
    for text in ("我想知道爸爸几岁", "小蝌蚪找妈妈是什么故事?", "不要告诉妈妈"):
        assert calls.handle(text, "zh") is None
    assert judge.asked == ["我想知道爸爸几岁", "小蝌蚪找妈妈是什么故事?", "不要告诉妈妈"]
    assert calls.pending is None and sent == []


def test_judge_not_asked_without_parent_word_or_in_games():
    judge = Judge({"讲一个熊爸爸的故事": "dad"})
    calls, _, _, _ = make(judge=judge)
    assert calls.handle("为什么天空是蓝色的?", "zh") is None
    assert calls.handle("讲一个熊爸爸的故事", "zh", judge_ok=False) is None  # a riddle or story is going on
    assert judge.asked == []
    assert calls.handle("叫爸爸来", "zh", judge_ok=False) is not None  # a clear request still works


def test_judge_not_asked_when_feature_off():
    judge = Judge({"我要妈妈": "mom"})
    off = {"call_parent": {"telegram": TG, "enabled": False}}
    for settings in (off, {}):
        calls, _, _, _ = make(settings=settings, judge=judge)
        assert calls.handle("我要妈妈", "zh") is None
    assert judge.asked == []


def test_judge_failure_is_not_a_request():
    def broken(text, lang):
        raise RuntimeError("model down")

    calls, sent, _, _ = make(judge=broken)
    assert calls.handle("我要妈妈", "zh") is None and sent == []


def _ollama(reply):
    return httpx.MockTransport(lambda r: httpx.Response(200, json={"message": {"content": reply}}))


@pytest.mark.parametrize(
    "reply, call",
    [('{"call": "mom"}', "mom"), ('{"call": "both"}', "both"), ('{"call": "none"}', "none"),
     ('{"call": "grandma"}', "none"), ('{"call": ["dad"]}', "none"), ("not json", "none"), ('["dad"]', "none")],
)
def test_judge_with_model_parses_strictly(monkeypatch, reply, call):
    seen = {}

    def post(url, json, timeout):
        seen["body"] = json
        return httpx.Client(transport=_ollama(reply)).post(url, json=json)

    monkeypatch.setattr(call_parent.httpx, "post", post)
    assert call_parent.judge_with_model("我要妈妈", "zh", model="m", base_url="http://127.0.0.1:11434") == call
    assert seen["body"]["think"] is False and seen["body"]["options"]["temperature"] == 0
    assert "我要妈妈" in seen["body"]["messages"][0]["content"]


def test_judge_with_model_is_local_only(monkeypatch):
    monkeypatch.setattr(call_parent.httpx, "post", lambda *a, **k: pytest.fail("must not call a remote model"))
    assert call_parent.judge_with_model("我要妈妈", "zh", model="m", base_url="https://example.com") == "none"


def test_judge_with_model_network_error_is_none(monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(call_parent.httpx, "post", down)
    assert call_parent.judge_with_model("我要妈妈", "zh", model="m", base_url="http://127.0.0.1:11434") == "none"


# ---------- confirmation ----------

def test_asks_first_then_sends_on_yes():
    calls, sent, clock, _ = make()
    assert calls.handle("叫爸爸来", "zh") == "要我告诉爸爸你在找他吗?"
    assert sent == []
    clock.t += 5
    assert calls.handle("要", "zh") == "好的,我已经告诉爸爸了。"
    assert [c for c, _ in sent] == ["1"]


def test_no_sends_nothing():
    calls, sent, clock, store = make()
    calls.handle("tell mommy I'm done", "en")
    assert calls.handle("no", "en") == "Okay, I won't send it."
    assert sent == []
    assert [r["status"] for r in CallLog(store.db).recent(now=clock.t)] == ["declined"]


def test_other_answer_drops_the_question():
    calls, sent, clock, _ = make()
    calls.handle("叫妈妈来", "zh")
    assert calls.handle("恐龙有多大?", "zh") is None  # answered normally by the pipeline
    assert calls.handle("要", "zh") is None  # the question is gone
    assert sent == []


def test_confirmation_lapses():
    calls, sent, clock, _ = make()
    calls.handle("叫妈妈来", "zh")
    clock.t += call_parent.CONFIRM_TIMEOUT_S + 1
    assert calls.handle("好", "zh") is None
    assert sent == []


# ---------- routing: dad, mom, both ----------

def test_dad_mom_both_routing():
    for text, chats in (("叫爸爸来", ["1"]), ("叫妈妈来", ["2"]), ("叫爸爸妈妈过来", ["1", "2"])):
        calls, sent, _, _ = make()
        calls.handle(text, "zh")
        calls.handle("好", "zh")
        assert [c for c, _ in sent] == chats, text


def test_both_says_both_and_counts_as_one_message():
    calls, sent, clock, _ = make()
    assert calls.handle("叫爸爸妈妈过来", "zh") == "要我告诉爸爸妈妈你在找他们吗?"
    assert calls.handle("好", "zh") == "好的,我已经告诉爸爸妈妈了。"
    assert all("宝宝想找爸爸妈妈" in t for _, t in sent)
    clock.t += 10
    assert calls.handle("叫爸爸来", "zh") == "刚才已经给爸爸发过一条消息了,过两分钟才能再发。"


def test_both_with_one_chat_sends_once():
    single = {"call_parent": {"telegram": {"bot_token": "t", "chat_id": "1"}}}
    calls, sent, _, _ = make(settings=single)
    calls.handle("叫爸爸妈妈过来", "zh")
    calls.handle("好", "zh")
    assert [c for c, _ in sent] == ["1"]


def test_both_partial_failure_names_who_got_it():
    calls, sent, clock, store = make(ok=lambda chat: chat == "2")
    calls.handle("叫爸爸妈妈过来", "zh")
    assert calls.handle("好", "zh") == "好的,我已经告诉妈妈了。"
    assert [r["status"] for r in CallLog(store.db).recent(now=clock.t)] == ["partial"]


def test_per_parent_chat_fallback():
    opts = {"telegram": {"bot_token": "t", "chat_id": "1", "chat_ids": {"mom": "2"}}}
    assert call_parent.chat_for(opts, "mom") == "2"
    assert call_parent.chat_for(opts, "dad") == "1"
    assert chats_for(opts, "both") == ["1", "2"]


# ---------- what is sent ----------

def test_default_message_is_fixed_without_child_words():
    calls, sent, clock, _ = make()
    calls.handle("告诉妈妈我饿了", "zh")
    calls.handle("好", "zh")
    text = sent[0][1]
    assert text.startswith("宝宝想找妈妈") and "Your daughter is asking for Mommy" in text
    assert "iPad" in text
    assert "饿" not in text and "我" not in text


def test_judged_request_sends_fixed_message_too():
    calls, sent, _, _ = make(judge=Judge({"我想爸爸了": "dad"}))
    calls.handle("我想爸爸了", "zh")
    calls.handle("嗯", "zh")
    assert "想爸爸了" not in sent[0][1] and "宝宝想找爸爸" in sent[0][1]


def test_child_words_only_when_parent_allows():
    allowed = {"call_parent": {"telegram": TG, "include_words": True}}
    calls, sent, _, _ = make(settings=allowed)
    assert calls.handle("告诉妈妈我饿了", "zh") == "要我把你的话发给妈妈吗?"
    calls.handle("要", "zh")
    assert "告诉妈妈我饿了" in sent[0][1]


@pytest.mark.parametrize("value", ["yes", 1, "true", None])
def test_include_words_needs_literal_true(value):
    opts = {"telegram": TG, "include_words": value}
    text = message_text(detect("tell daddy I'm hungry"), "watch", opts, now=T0)
    assert "hungry" not in text and "watch" in text


# ---------- rate limit, switch, log ----------

def test_rate_limit_shared_and_released_on_failure():
    limit = RateLimit()
    sent = []
    clock = Clock()

    def pet(client):
        return CallParent(client, FakeStore(), lambda o, c, t: sent.append(t) or True, limit, lambda: CONFIGURED,
                          clock, judge=None)

    ipad, watch = pet("ipad"), pet("watch")
    ipad.handle("叫爸爸来", "zh")
    ipad.handle("好", "zh")
    clock.t += 30
    assert watch.handle("call daddy", "en") == "I already sent Daddy a message a moment ago. I can send another one in a couple of minutes."
    assert watch.pending is None
    clock.t += call_parent.DEFAULT_INTERVAL_S
    assert watch.handle("call daddy", "en").startswith("Should I tell Daddy")
    watch.handle("yes", "en")
    assert len(sent) == 2

    failing, _, fclock, _ = make(ok=False)
    failing.handle("叫爸爸来", "zh")
    assert failing.handle("好", "zh") == "哎呀,消息没发出去。你直接去找爸爸吧。"
    fclock.t += 1
    failing.handle("叫爸爸来", "zh")
    assert failing.pending is not None  # a failed send does not use up the slot


def test_switch_off_and_unconfigured():
    off = {"call_parent": {"telegram": TG, "enabled": False}}
    for settings in (off, {}, {"call_parent": {"telegram": {"chat_id": "42"}}}):
        calls, sent, _, _ = make(settings=settings)
        assert calls.handle("叫爸爸来", "zh") == "我现在不能给爸爸发消息,你直接去找他吧。"
        assert calls.pending is None and sent == []


def test_switched_off_between_question_and_yes():
    settings = {"call_parent": {"telegram": TG}}
    calls, sent, _, _ = make(settings=settings)
    calls.handle("叫爸爸来", "zh")
    settings["call_parent"]["enabled"] = False
    assert "不能" in calls.handle("好", "zh")
    assert sent == []


def test_every_attempt_logged_and_text_purged_after_7_days():
    calls, sent, clock, store = make()
    calls.handle("叫爸爸妈妈过来", "zh")
    calls.handle("好", "zh")
    clock.t += 10
    calls.handle("叫爸爸来", "zh")  # rate limited
    rows = CallLog(store.db).recent(now=clock.t)
    assert [(r["parent"], r["status"]) for r in rows] == [("both", "sent"), ("dad", "limited")]
    assert rows[0]["text"] == sent[0][1]
    lines = report_lines(store.db, days=36500)
    assert any("爸爸妈妈" in line and "已发送" in line for line in lines)
    later = CallLog(store.db).recent(days=30, now=clock.t + 8 * 24 * 3600)
    assert all(r["text"] is None for r in later) and len(later) == 2


def test_telegram_send_posts_only_send_message():
    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    opts = {"telegram": TG}
    assert call_parent.telegram_send(opts, "2", "hello", client=client)
    assert seen == [("https://api.telegram.org/bottest-token/sendMessage", {"chat_id": "2", "text": "hello"})]

    failing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"ok": False})))
    assert not call_parent.telegram_send(opts, "2", "hello", client=failing)



# ---------- 2026-10-24 evening, the parent's test: Mommy right after Daddy ----------

def test_each_parent_has_their_own_limit_and_the_reply_is_honest():
    calls, sent, clock, store = make()
    calls.handle("我要找爸爸。", "zh")
    assert calls.handle("好呀。", "zh") == "好的,我已经告诉爸爸了。"
    clock.t += 15  # asking for Mommy 15 seconds later used to be blocked, with "我刚刚已经告诉过妈妈了"
    assert calls.handle("我要找妈妈。", "zh") == "要我告诉妈妈你在找她吗?"
    assert calls.handle("好", "zh") == "好的,我已经告诉妈妈了。"
    assert [c for c, _ in sent] == ["1", "2"]
    clock.t += 10
    assert calls.handle("我要找妈妈。", "zh") == "刚才已经给妈妈发过一条消息了,过两分钟才能再发。"
    clock.t += 10
    assert calls.handle("叫爸爸妈妈过来", "zh") == "刚才已经给爸爸妈妈发过一条消息了,过两分钟才能再发。"


def test_both_sends_to_the_parent_whose_slot_is_free():
    calls, sent, clock, _ = make()
    calls.handle("叫爸爸来", "zh")
    calls.handle("好", "zh")
    clock.t += 10
    assert calls.handle("叫爸爸妈妈过来", "zh") == "要我告诉爸爸妈妈你在找他们吗?"
    assert calls.handle("好", "zh") == "好的,我已经告诉妈妈了。"
    assert [c for c, _ in sent] == ["1", "2"]


def test_several_yes_words_count_as_yes():
    from curiosity_pet.call_parent import answer_kind

    for yes in ["好，是。", "好的好的", "嗯嗯,要", "是的,可以", "Yes, okay!"]:
        assert answer_kind(yes) == "yes", yes
    for other in ["什么?", "不要", "好像不是", "要不要吃饭"]:
        assert answer_kind(other) != "yes", other


# ---------- 20:09 to 20:13, the parent's second test: confirmations that were missed ----------

def test_real_confirmations_and_repeats_send_the_message():
    for reply in ["叫。", "好吧。", "要的。", "好,是。", "要啊"]:
        calls, sent, clock, _ = make()
        calls.handle("我要找妈妈。", "zh")
        assert calls.handle(reply, "zh") == "好的,我已经告诉妈妈了。", reply
    calls, sent, clock, _ = make()
    calls.handle("我要找妈妈。", "zh")
    assert calls.handle("我要找妈妈。", "zh") == "好的,我已经告诉妈妈了。"  # saying it again means yes


def test_now_is_not_no_and_garbled_replies_are_asked_again_once():
    calls, sent, clock, _ = make()
    calls.handle("我要找妈妈。", "zh")
    assert calls.handle("Now.", "zh").startswith("我没听清。要我告诉妈妈")
    assert calls.handle("好", "zh") == "好的,我已经告诉妈妈了。"
    calls, sent, clock, _ = make()
    calls.handle("我要找妈妈。", "zh")
    calls.handle("我的。", "zh")
    assert calls.handle("ふふ", "zh") is None and sent == []  # asked once already: the question lapses


def test_did_you_tell_daddy_is_answered_from_what_was_sent():
    calls, sent, clock, _ = make()
    assert calls.handle("你帮我叫爸爸了吗?", "zh") == "我还没有给爸爸发消息。要我告诉爸爸你在找他吗?"
    assert calls.handle("要", "zh") == "好的,我已经告诉爸爸了。"
    clock.t += 30
    assert calls.handle("你告诉爸爸了吗?", "zh") == "刚才已经给爸爸发过消息了。"


@pytest.mark.parametrize("text", ["不好", "不是", "不要叫", "别叫了", "嗯不要", "不发了", "nah", "not yet", "没有"])
def test_short_refusals_are_no(text):
    assert answer_kind(text) == "no"


@pytest.mark.parametrize("text", ["好不好?", "要不要", "不要吗?", "叫什么名字?", "不知道爸爸在哪"])
def test_questions_and_other_sentences_are_not_no(text):
    assert answer_kind(text) is None
