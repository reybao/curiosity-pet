"""联网查询的决策、记录,以及接入回答流程。

最关键的一条:发到网络上的只有通过检查的话题词,孩子原话里的个人信息一个字都出不去。
"""

import httpx
import numpy as np
import pytest

from curiosity_pet import lookup, pipeline, wiki
from curiosity_pet.lookup import FILLER, Researcher
from curiosity_pet.pipeline import Pet
from curiosity_pet.store import LOG_RETENTION_S, Store


def fake_rewrite(result):
    calls = []

    def rewrite(question, lang):
        calls.append(question)
        return result

    rewrite.calls = calls
    return rewrite


def researcher(rewrite, **kw):
    kw.setdefault("search", lambda q, lang, contact=None: None)
    return Researcher(store=None, enabled=True, contact="pet@example.org", rewrite=rewrite, **kw)


# ---------- 决策 ----------


def test_knowledge_question_goes_online_with_rewritten_query():
    r = researcher(fake_rewrite({"kind": "knowledge", "topic": "cartoons_stories", "query": "七龙珠 孙悟空"}))
    d = r.decide("我想知道七龙珠里的孙悟空是谁?", "zh")
    assert d.go and d.query == "七龙珠 孙悟空" and d.topic == "cartoons_stories"


def test_model_leak_is_caught_by_rules():
    # 最坏情况:模型把个人信息留在了搜索词里。原话里有"弟弟"时由规则拦下
    r = researcher(fake_rewrite({"kind": "knowledge", "topic": "cartoons_stories", "query": "弟弟 七龙珠"}))
    d = r.decide("给弟弟讲讲七龙珠是什么?", "zh")
    assert not d.go
    assert "弟弟" not in d.query


def test_model_invented_words_are_dropped():
    # 模型加了原话里没有的词("弟弟"):落地检查删掉,发出去的只剩原话里的话题词
    r = researcher(fake_rewrite({"kind": "knowledge", "topic": "cartoons_stories", "query": "弟弟 七龙珠"}))
    d = r.decide("七龙珠里的孙悟空是谁?", "zh")
    assert d.go and d.query == "七龙珠"


@pytest.mark.parametrize("kind", ["personal", "feelings", "sensitive", "chat"])
def test_non_knowledge_kinds_stay_offline(kind):
    r = researcher(fake_rewrite({"kind": kind, "topic": "other", "query": "恐龙"}))
    assert not r.decide("恐龙是怎么灭绝的?", "zh").go


@pytest.mark.parametrize("text", ["我今天好难过", "我讨厌弟弟", "别告诉妈妈好吗", "讲个故事吧"])
def test_personal_sentences_never_reach_the_model_or_network(text):
    rw = fake_rewrite({"kind": "knowledge", "topic": "other", "query": "x"})
    assert not researcher(rw).decide(text, "zh").go
    assert rw.calls == []  # 粗筛就拦下了,连改写都没做


def test_sensitive_original_stays_offline_without_calling_model():
    rw = fake_rewrite({"kind": "knowledge", "topic": "other", "query": "死亡"})
    assert not researcher(rw).decide("人死了会去哪里?", "zh").go
    assert rw.calls == []


def test_switch_off_or_no_contact_stays_offline():
    rw = fake_rewrite({"kind": "knowledge", "topic": "space", "query": "黑洞"})
    off = Researcher(enabled=False, contact="pet@example.org", rewrite=rw)
    no_contact = Researcher(enabled=True, contact="", rewrite=rw)
    assert not off.decide("黑洞是什么?", "zh").go
    assert not no_contact.decide("黑洞是什么?", "zh").go
    assert rw.calls == []


def test_family_names_from_settings_block_lookup():
    rw = fake_rewrite({"kind": "knowledge", "topic": "other", "query": "小米 恐龙"})
    d = researcher(rw, family_terms=["小米"]).decide("小米问恐龙吃什么?", "zh")
    assert not d.go and rw.calls == []  # 原话含家人名字,粗筛就拦下


# ---------- 端到端:网络上只出现话题词 ----------


def test_only_the_topic_query_reaches_the_network():
    sent = []

    def handler(req):
        sent.append(str(req.url))
        return httpx.Response(
            200,
            json={"query": {"pages": [{"title": "孙悟空", "extract": "孙悟空是主角。", "fullurl": "u", "index": 1}]}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = Researcher(
        enabled=True,
        contact="pet@example.org",
        rewrite=fake_rewrite({"kind": "knowledge", "topic": "cartoons_stories", "query": "七龙珠 孙悟空"}),
        search=lambda q, lang, contact=None: wiki.search_all(q, lang, client=client),
    )
    question = "我想知道七龙珠里的孙悟空是谁?"
    d = r.decide(question, "zh")
    r.fetch(d, "zh")
    # 两个请求:全文搜索 + 按条目名取;自由文本只有话题词
    params = [httpx.URL(u).params for u in sent]
    assert [p.get("gsrsearch") or p.get("titles") for p in params] == ["七龙珠 孙悟空", "七龙珠|孙悟空"]
    for u in sent:
        assert "我想知道" not in httpx.URL(u).params.get("gsrsearch", "") + httpx.URL(u).params.get("titles", "")


# ---------- 记录:7 天删原文,主题计数保留 ----------


def test_lookup_log_is_purged_after_7_days_but_topic_counts_stay(tmp_path):
    s = Store(tmp_path / "pet.db")
    t0 = 1_800_000_000
    s.record_lookup("zh", "七龙珠 孙悟空", "cartoons_stories", "孙悟空", True, now=t0)
    assert [x["query"] for x in s.recent_lookups()] == ["七龙珠 孙悟空"]
    s.record_lookup("zh", "黑洞", "space", "黑洞", True, now=t0 + LOG_RETENTION_S + 60)
    assert [x["query"] for x in s.recent_lookups()] == ["黑洞"]
    topics = {(c["topic"], c["n"]) for c in s.topic_counts()}
    assert ("cartoons_stories", 1) in topics and ("space", 1) in topics


def test_fetch_records_query_and_saves_pending(tmp_path):
    s = Store(tmp_path / "pet.db")
    result = wiki.WikiResult(
        title="孙悟空 (七龙珠)", text="孙悟空是《七龙珠》的主角。", url="https://zh.wikipedia.org/wiki/x", host="zh"
    )
    r = Researcher(
        store=s, enabled=True, contact="c", rewrite=fake_rewrite({}), search=lambda q, lang, contact=None: result
    )
    r.fetch(lookup.Decision(True, "", "七龙珠 孙悟空", "cartoons_stories"), "zh")
    assert s.recent_lookups()[0]["query"] == "七龙珠 孙悟空"
    assert s.db.execute("SELECT title FROM kb_pending").fetchall() == [("孙悟空 (七龙珠)",)]


# ---------- 接入回答流程 ----------


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class FakePlayer:
    def play(self, audio, text=None, on_start=None):
        pass


def test_pet_says_filler_then_answers_from_reference(monkeypatch):
    seen = {}

    def fake_stream(msgs):
        seen["msgs"] = msgs
        return iter(["我在维基百科上查到,孙悟空是七龙珠的主角。"])

    monkeypatch.setattr(pipeline, "stream_chat", fake_stream)
    result = wiki.WikiResult(title="孙悟空 (七龙珠)", text="孙悟空是《七龙珠》的主角。", url="u", host="zh")
    r = researcher(
        fake_rewrite({"kind": "knowledge", "topic": "cartoons_stories", "query": "七龙珠 孙悟空"}),
        search=lambda q, lang, contact=None: result,
    )
    tts = FakeTTS()
    pet = Pet(asr=None, tts=tts, player=FakePlayer(), researcher=r)
    turn = pet.answer("七龙珠里的孙悟空是谁?")
    assert tts.spoken[0] == FILLER["zh"]
    assert turn.looked_up and turn.source == "孙悟空 (七龙珠)"
    user_msg = seen["msgs"][-1]["content"]
    assert "孙悟空是《七龙珠》的主角" in user_msg and "维基百科" in user_msg
    # 资料只用于这一轮,不进历史
    assert all("参考资料" not in m["content"] for m in pet.history)


def test_pet_answers_normally_when_not_looking_up(monkeypatch):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["好的。"]))
    tts = FakeTTS()
    pet = Pet(asr=None, tts=tts, player=FakePlayer(), researcher=researcher(fake_rewrite({})))
    turn = pet.answer("我今天好难过")
    assert FILLER["zh"] not in tts.spoken
    assert not turn.looked_up and turn.lookup_reason == "不像知识提问"


# ---------- 相关性检查 ----------


def wr(title, text):
    return wiki.WikiResult(title=title, text=text, url="u", host="h")


def test_irrelevant_result_is_dropped():
    # 实测例子:"天空蓝色成因" 搜到 "蓝色弹珠"(地球照片)
    assert not lookup.relevant("天空 成因", wr("蓝色弹珠", "蓝色弹珠是一张在1972年拍摄的地球照片。"))


def test_relevant_results_are_kept():
    assert lookup.relevant("七龙珠 孙悟空", wr("孙悟空 (七龙珠)", "孙悟空是《七龙珠》的主角。"))
    assert lookup.relevant("Goku Dragon Ball", wr("Goku", "Goku is the protagonist of Dragon Ball."))
    assert lookup.relevant("恐龙灭绝", wr("白垩纪—古近纪灭绝事件", "这次灭绝事件导致非鸟恐龙全部消失。"))


def test_fetch_drops_irrelevant_result_but_still_logs(tmp_path):
    s = Store(tmp_path / "pet.db")
    r = Researcher(
        store=s, enabled=True, contact="c", rewrite=fake_rewrite({}),
        search=lambda q, lang, contact=None: wr("蓝色弹珠", "一张地球照片。"),
    )
    assert r.fetch(lookup.Decision(True, "", "天空 成因", "nature"), "zh") is None
    assert s.recent_lookups()[0]["found"] == 0
    assert s.db.execute("SELECT COUNT(*) FROM kb_pending").fetchone()[0] == 0


def test_best_of_several_results_is_picked():
    # 实测:"天空 蓝色" 排第一的是一部电影,应选更相关的"天空"条目
    movie = wr("知道天空有多藍的人啊", "这是一部日本动画电影。")
    sky = wr("天空", "天空看起来是蓝色的,是因为空气分子散射阳光中的蓝光。")
    assert lookup.pick_best("天空 蓝色", [movie, sky]) is sky


def test_pick_best_keeps_wikipedia_order_on_tie():
    a = wr("恐龙", "恐龙灭绝于六千六百万年前。")
    b = wr("恐龙灭绝", "恐龙灭绝于六千六百万年前。")
    assert lookup.pick_best("恐龙 灭绝", [a, b]) in (a, b)
    assert lookup.pick_best("恐龙 灭绝", []) is None


def test_two_word_query_needs_both_words():
    # 实测:"猫 打呼噜" 搜到儿童作家杨红樱,只含"猫"
    assert not lookup.relevant("猫 打呼噜", wr("杨红樱", "杨红樱是儿童文学作家,代表作有《笑猫日记》。"))
    assert lookup.relevant("猫 打呼噜", wr("猫", "猫满足时会打呼噜。"))
