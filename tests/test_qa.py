"""Idiom stories and poems come from the library; the child Q&A library serves only parent-approved answers."""

import bz2
import json

import pytest

from curiosity_pet import qa as qa_mod
from curiosity_pet.library import Library, build, library_request
from curiosity_pet.lookup import Researcher
from curiosity_pet.qa import QAStore, similarity
from curiosity_pet.search import LibraryProvider

pytest.importorskip("opencc")


def cirrus(path, docs):
    with bz2.open(path, "wt", encoding="utf-8") as f:
        for i, d in enumerate(docs):
            f.write(json.dumps({"index": {"_id": i}}) + "\n")
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def wiki_doc(title, text, qid="", links=0):
    return {"namespace": 0, "page_type": "primary", "title": title, "opening_text": text, "text": text,
            "wikibase_item": qid, "incoming_links": links, "template": [], "category": [], "redirect": []}


IDIOMS = [
    {"word": "画蛇添足", "pinyin": "huà shé tiān zú", "explanation": "画蛇时给蛇添上脚。比喻做了多余的事,非但无益,反而不合适。",
     "derivation": "《战国策·齐策二》楚有祠者,赐其舍人卮酒……蛇固无足,子安能为之足?", "example": "", "abbreviation": ""},
    {"word": "守株待兔", "pinyin": "shǒu zhū dài tù", "explanation": "比喻死守狭隘经验,不知变通。",
     "derivation": "《韩非子·五蠹》宋国有一个农民,看见一只兔子撞在树根上死了,便在树根旁等待。", "example": "", "abbreviation": ""},
]
SCHOOL = [
    {"title": "江雪", "author": "柳宗元", "dynasty": "唐", "first": "千山鸟飞绝", "lines": ["千山鸟飞绝，万径人踪灭。", "孤舟蓑笠翁，独钓寒江雪。"],
     "book": "唐诗三百首", "url": "u", "variant": False},
    {"title": "春晓", "author": "孟浩然", "dynasty": "唐", "first": "春眠不觉晓", "lines": ["春眠不觉晓，处处闻啼鸟。", "夜来风雨声，花落知多少。"],
     "book": "唐诗三百首", "url": "u", "variant": False},
]
QA_ZH = [
    {"id": "zh-qa-001", "kind": "qa", "topic": "light", "q": "天空为什么是蓝色的?", "alt": ["天为什么是蓝的", "为啥天空是蓝色"],
     "a": "阳光里有很多颜色,蓝色的光最容易被空气撞得到处跑,所以满天都是蓝色。", "check": "Rayleigh scattering"},
    {"id": "zh-qa-002", "kind": "qa", "topic": "weather", "q": "为什么会打雷?", "alt": ["打雷是怎么回事"],
     "a": "云里的小冰块互相摩擦,积了很多电。电一下子放出来就是闪电,闪电让空气猛地变热膨胀,发出的响声就是雷。", "check": "lightning heats air"},
    {"id": "zh-note-001", "kind": "poem_note", "ref": "江雪", "q": "《江雪》讲的是什么?", "alt": ["江雪是什么意思"],
     "a": "下大雪的江上,鸟和行人都不见了,只有一位老渔翁坐在小船上安静地钓鱼。", "check": "textbook reading"},
    {"id": "zh-story-001", "kind": "idiom_story", "ref": "画蛇添足", "q": "画蛇添足的故事是什么?", "alt": [],
     "a": "几个人比赛画蛇,先画完的人得到一壶酒。有个人最先画好,却又给蛇添上脚,结果被别人说蛇没有脚,酒也输了。意思是做多余的事反而坏事。",
     "check": "Zhan Guo Ce"},
]
QA_EN = [
    {"id": "en-qa-001", "kind": "qa", "topic": "light", "q": "Why is the sky blue?", "alt": ["why's the sky blue", "what makes the sky blue"],
     "a": "Sunlight has many colors. Air scatters the blue light the most, so blue comes at us from all over the sky.", "check": "Rayleigh scattering"},
]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    src = tmp_path / "src"
    x = src / "extra"
    x.mkdir(parents=True)
    cirrus(src / "simplewiki_content-20261018-00000.json.bz2",
           [wiki_doc("Sky", "The sky is everything above the ground that we can see, like clouds and the Sun.", "Q1", 50)])
    (x / "idiom.json").write_text(json.dumps(IDIOMS, ensure_ascii=False), encoding="utf-8")
    (x / "school_poems.json").write_text(json.dumps(SCHOOL, ensure_ascii=False), encoding="utf-8")
    build(src, tmp_path / "library.db", workers=1, log=lambda *a: None)
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "qa_zh.json").write_text(json.dumps(QA_ZH, ensure_ascii=False), encoding="utf-8")
    (seed / "qa_en.json").write_text(json.dumps(QA_EN, ensure_ascii=False), encoding="utf-8")
    store = QAStore(seed, tmp_path / "qa_status.json")
    stories = tmp_path / "stories.json"
    stories.write_text(json.dumps({"idioms": ["画蛇添足", "守株待兔"]}, ensure_ascii=False), encoding="utf-8")
    from curiosity_pet import library

    monkeypatch.setattr(library, "IDIOM_STORY_LIST", stories)
    lib = Library(tmp_path / "library.db")
    r = Researcher(store=None, enabled=False, contact="", providers=[LibraryProvider(lib)], qa=store, guess=None, qa_judge=None,
                   rewrite=lambda q, lang: {"kind": "chat", "topic": "other", "query": ""})
    return r, store, lib


def ask(r, q, lang="zh"):
    d = r.decide(q, lang)
    return d, (r.fetch(d, lang) if d.go else None)


# ---------- requests recognized ----------

def test_requests_recognized():
    assert library_request("给我讲个成语故事", "zh") == ("idiom", "")
    assert library_request("背一首关于冬天的诗", "zh") == ("poem_theme", "冬")
    assert library_request("你会背多少首唐诗?", "zh") == ("poem_count", "")
    assert library_request("这首诗想表达什么", "zh") == ("poem_meaning", "")
    assert library_request("不是这个意思", "zh") == ("again", "")
    assert library_request("为什么天空是蓝色的?", "zh") is None
    assert library_request("Tell me a story", "en") is None


# ---------- idioms and poems from the library (real failures of the day) ----------

def test_idiom_story_is_the_library_entry_not_the_models_memory(world):
    r, store, lib = world
    d, res = ask(r, "给我讲个成语故事")
    assert d.go and not d.online and res.title in {"画蛇添足", "守株待兔"} and res.text.startswith("成语")
    _, again = ask(r, "再讲一个成语故事")
    assert again.title != res.title  # another one
    _, named = ask(r, "画蛇添足的故事")
    assert named.title == "画蛇添足" and "多余的事" in named.text  # "做事别多管闲事" was the wrong answer given
    _, same = ask(r, "不是这个意思")  # the child corrects the pet: the same entry again
    assert same.title == "画蛇添足"
    _, meaning = ask(r, "这个成语是什么意思")
    assert meaning.title == "画蛇添足"


def test_how_many_poems_does_not_look_up_an_idiom(world):
    r, store, lib = world
    _, res = ask(r, "你会背多少首唐诗?")  # once answered with the unrelated idiom 残膏剩馥
    assert res.title == "小图书馆里的古诗" and "2首" in res.text


def test_poem_by_theme_title_and_meaning(world):
    r, store, lib = world
    _, winter = ask(r, "背一首关于冬天的诗")
    assert winter.title == "江雪" and "独钓寒江雪" in winter.text
    _, meaning = ask(r, "这首诗想表达什么")  # once got 《江雪》 wrong
    assert meaning.title == "江雪" and "大意" not in meaning.text  # the note is still pending
    store.set_status(["zh-note-001"], "approved")
    _, meaning = ask(r, "江雪是什么意思")
    assert "大意:下大雪的江上" in meaning.text and "独钓寒江雪" in meaning.text
    _, poem = ask(r, "背一首诗")
    assert poem.title in {"江雪", "春晓"}


def test_approved_idiom_story_is_attached(world):
    r, store, lib = world
    store.set_status(["zh-story-001"], "approved")
    _, res = ask(r, "讲讲画蛇添足")
    assert res.text.startswith("故事:几个人比赛画蛇") and "比喻做了多余的事" in res.text


def test_ordinary_story_words_are_not_idiom_requests(world):
    r, store, lib = world
    d, _ = ask(r, "讲讲恐龙")
    assert d.intent != "library"


# ---------- the reviewed Q&A library ----------

def test_pending_and_rejected_answers_are_never_served(world):
    r, store, lib = world
    assert store.match("天空为什么是蓝色的?", "zh") is None  # pending
    store.set_status(["zh-qa-001"], "rejected")
    assert store.match("天空为什么是蓝色的?", "zh") is None


def test_approved_answers_rank_first_and_skip_the_rewrite(world):
    r, store, lib = world
    calls = []
    r.rewrite = lambda q, lang: calls.append(q) or {"kind": "knowledge", "topic": "nature", "query": "天空 蓝色"}
    store.set_status(["zh-qa-001", "en-qa-001"], "approved")
    d, res = ask(r, "为啥天空是蓝色的呀?")
    assert d.intent == "qa" and res.text.startswith("阳光里有很多颜色") and calls == []
    d, res = ask(r, "Why's the sky so blue?", "en")
    assert d.intent == "qa" and res.url == "qa:en-qa-001"
    d, res = ask(r, "为什么会下雨?")  # not in the approved set: the usual lookup
    assert d.intent != "qa" and calls == ["为什么会下雨?"]


def test_similarity_needs_the_content_words():
    assert similarity("为啥天空是蓝色的呀", "天空为什么是蓝色的?", "zh") == 1.0
    assert similarity("我想问你,为什么会打雷", "为什么打雷?", "zh") == 1.0  # one word is enough when both are that short
    assert similarity("海水为什么是蓝色的", "天空为什么是蓝色的?", "zh") < 0.75
    assert similarity("Why is the sea blue?", "Why is the sky blue?", "en") < 0.75
    assert similarity("Why's it so windy?", "Why is it windy?", "en") == 1.0


def test_close_questions_go_to_the_judge(world):
    r, store, lib = world
    store.set_status(["zh-qa-001", "zh-qa-002"], "approved")
    asked = []

    def judge(q, cands, lang):
        asked.append((q, cands))
        return 1 if "天空" in q else 0

    assert store.match("天空怎么是蓝色的,不是红色的", "zh") is None  # not exact, and no judge
    assert store.match("天空怎么是蓝色的,不是红色的", "zh", judge=judge).id == "zh-qa-001"
    assert store.match("鱼为什么会游泳", "zh", judge=judge) is None and len(asked) == 1  # no candidate: no model call
    # in the pet's flow the judge runs in fetch (after the filler), and the rewrite still happens
    r.qa_judge = judge
    r.rewrite = lambda q, lang: {"kind": "knowledge", "topic": "nature", "query": "天空 蓝色"}
    d = r.decide("天空怎么是蓝色的,不是红色的?", "zh")
    assert d.entry is None and d.qa_question
    assert r.fetch(d, "zh").url == "qa:zh-qa-001"


def test_status_file_changes_take_effect_without_restart(world, tmp_path):
    r, store, lib = world
    other = QAStore(store.seed_dir, store.status_path)  # e.g. the CLI in another process
    other.set_status(["zh-qa-002"], "approved")
    assert store.match("打雷是怎么回事呀", "zh").id == "zh-qa-002"


def test_review_cli(world, capsys, monkeypatch):
    r, store, lib = world
    monkeypatch.setattr(qa_mod, "SEED_DIR", store.seed_dir)
    monkeypatch.setattr(qa_mod, "STATUS_PATH", store.status_path)
    monkeypatch.setattr(qa_mod.QAStore.__init__, "__defaults__", (store.seed_dir, store.status_path))
    qa_mod.cli(["approve", "zh-qa-001", "nope"])
    assert "1 marked approved; not found: nope" in capsys.readouterr().out
    qa_mod.cli(["list", "--status", "approved"])
    assert "zh-qa-001" in capsys.readouterr().out
    qa_mod.cli(["stats"])
    out = capsys.readouterr().out
    assert "zh qa          approved  1" in out and "zh qa          pending   1" in out
    answers = iter(["a", "r", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    qa_mod.cli(["review", "--lang", "zh"])
    assert QAStore(store.seed_dir, store.status_path).status("zh-qa-002") == "approved"
