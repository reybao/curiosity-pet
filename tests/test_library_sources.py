"""Extra library sources: each loader reads its file format, filters what a 7-year-old should not get, and the
entries are searchable alongside Wikipedia with a small bonus for child-level sources."""

import bz2
import json

import pytest

from curiosity_pet import library_sources as ls
from curiosity_pet.library import Library, build, too_grim

pytest.importorskip("opencc")


def cirrus(path, docs):
    with bz2.open(path, "wt", encoding="utf-8") as f:
        for i, d in enumerate(docs):
            f.write(json.dumps({"index": {"_id": i}}) + "\n")
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def wiki_doc(title, text, ns=0, qid="", links=0):
    return {"namespace": ns, "page_type": "primary", "title": title, "opening_text": text, "text": text,
            "wikibase_item": qid, "incoming_links": links, "template": [], "category": [], "redirect": []}


GUTENBERG_HTML = """<html><body>*** START OF THE PROJECT GUTENBERG EBOOK THE REAL MOTHER GOOSE ***
<h2>A LIST OF THE RHYMES</h2><p>Little Bo-peep, Hey diddle diddle and many more rhymes listed here for the reader.</p>
<div class="poem" id="a128"><div class="boldtitle">THE CAT AND THE FIDDLE</div><br>
Hey, diddle, diddle!<br>The cat and the fiddle,<br>The cow jumped over the moon;<br>
The little dog laughed<br>To see such sport,<br>And the dish ran away with the spoon.<br></div>
*** END OF THE PROJECT GUTENBERG EBOOK ***</body></html>"""


@pytest.fixture(scope="module")
def extra(tmp_path_factory):
    d = tmp_path_factory.mktemp("lib")
    src = d / "src"
    x = src / "extra"
    (x / "mengxue").mkdir(parents=True)
    (x / "gutenberg").mkdir()
    cirrus(src / "simplewiki_content-20261018-00000.json.bz2",
           [wiki_doc("Moon", "The Moon is the natural satellite of the Earth. It goes around the Earth once a month.", qid="Q1", links=900)])
    cirrus(x / "simplewiktionary_content-20261018-00000.json.bz2", [
        wiki_doc("purr", "IPA (key): /pɜː(r)/ Homophone: per A purr is the sound a cat makes when it is relaxed."),
        wiki_doc("purred", "The past tense of purr."),
    ])
    cirrus(x / "enwikibooks_content-20261018-00000.json.bz2", [
        wiki_doc("Wikijunior:Solar System/Mars", "Mars is the fourth planet from the Sun. " * 30, ns=110),
        wiki_doc("Cookbook:Bread", "Bread is made from flour and water. " * 20, ns=0),  # not Wikijunior
    ])
    (x / "idiom.json").write_text(json.dumps([
        {"word": "守株待兔", "pinyin": "shǒu zhū dài tù", "explanation": "比喻死守狭隘经验,不知变通。",
         "derivation": "《韩非子·五蠹》记载宋国有一个农民,看见一只兔子撞在树根上,便在树根旁等待。", "example": "无", "abbreviation": "szdt"},
    ], ensure_ascii=False), encoding="utf-8")
    (x / "xiehouyu.json").write_text(json.dumps([
        {"riddle": "海滩上的沙子", "answer": "多的是；有的是"},
        {"riddle": "瞎子点灯", "answer": "白费蜡"},  # makes fun of a disability: dropped
        {"riddle": "王八吃秤砣", "answer": "铁了心"},  # insult word: dropped
        {"riddle": "猴儿吃芥末（调味品。味辣）", "answer": "傻了眼；翻白眼"},  # kept, notes in brackets removed
    ], ensure_ascii=False), encoding="utf-8")
    (x / "mengxue" / "sanzijing-new.json").write_text(json.dumps(
        {"title": "三字經", "author": "王應麟", "paragraphs": ["人之初，性本善，性相近，習相遠。", "茍不教，性乃遷，教之道，貴以專。",
                                                         "昔孟母，擇鄰處，子不學，斷機杼。", "竇燕山，有義方，教五子，名俱揚。", "養不教，父之過。"]},
        ensure_ascii=False), encoding="utf-8")
    (x / "mengxue" / "tangshisanbaishou.json").write_text(json.dumps(
        {"title": "唐詩三百首", "content": [{"type": "五言絕句", "content": [
            {"chapter": "靜夜思", "author": "李白", "paragraphs": ["床前明月光，疑是地上霜。", "舉頭望明月，低頭思故鄉。"]}]}]},
        ensure_ascii=False), encoding="utf-8")
    (x / "gutenberg" / "pg10607.html").write_text(GUTENBERG_HTML, encoding="utf-8")
    stats = build(src, d / "library.db", workers=1, log=lambda *a: None)
    return Library(d / "library.db"), stats


def test_counts_per_source(extra):
    _, stats = extra
    assert stats["wiktionary"] == 1  # "past tense of purr" only names a form
    assert stats["wikijunior"] >= 1 and stats["idiom"] == 1 and stats["xiehouyu"] == 2
    assert stats["gutenberg"] == 1  # the list of rhymes is front matter
    assert stats["poetry"] >= 3  # two windows of 三字经 plus the poem


def test_idiom_with_its_story(extra):
    lib, _ = extra
    r = lib.search("守株待兔", "zh")[0]
    assert r.title == "守株待兔" and "出处" in r.text and "兔子" in r.text


def test_poem_found_by_its_line_in_simplified(extra):
    lib, _ = extra
    r = lib.search("床前明月光", "zh")[0]
    assert r.title == "静夜思" and "举头望明月" in r.text  # converted from traditional
    assert "性本善" in lib.search("人之初", "zh")[0].text


def test_xiehouyu_and_dictionary_and_stories(extra):
    lib, _ = extra
    assert "多的是" in lib.search("海滩上的沙子", "zh")[0].text
    assert lib.search("瞎子点灯", "zh") == [] and lib.search("王八吃秤砣", "zh") == []
    assert lib.search("猴儿吃芥末", "zh")[0].title == "猴儿吃芥末"
    assert lib.search("purr meaning", "en")[0].text.startswith("A purr is the sound")
    assert "spoon" in lib.search("cat fiddle", "en")[0].text
    assert lib.search("Mars", "en")[0].title.startswith("Mars")


def test_cleaning_helpers():
    assert ls.clean_wiktionary("hard + -en (US) IPA (key): /ˈhɑrdn̩/ Hyphenation: hard‧en If you harden something") == "If you harden something"
    assert ls.chunks("One. " * 400, size=100, limit=3) and len(ls.chunks("One. " * 400, size=100, limit=3)) == 3
    paras = ls._html_paragraphs('<div id="mw-content-text"><p>Zebras are striped animals that live in Africa.[1]</p><p>x</p></div>')
    assert paras == ["Zebras are striped animals that live in Africa."]
    assert ls.VIKIDIA_SKIP.search("SCP 096")


def test_grim_entries_are_dropped():
    assert too_grim("Jeffrey Dahmer", "Jeffrey Dahmer was an American serial killer.")
    assert too_grim("某某案", "某某案是一起强奸案。")
    assert too_grim("秋叶原杀人事件", "秋叶原杀人事件,又称秋叶原随机杀人事件,是日本发生的一起事件。")  # found in the built library
    assert not too_grim("Julius Caesar", "Julius Caesar was a Roman general. He was murdered in 44 BC.")


# ---------- School poems and the character dictionary ----------

def test_school_poems_resolved_from_local_collections(tmp_path, monkeypatch):
    x = tmp_path / "extra"
    (x / "mengxue").mkdir(parents=True)
    (x / "werneror-poetry").mkdir()
    (x / "mengxue" / "tangshisanbaishou.json").write_text(json.dumps(
        {"title": "唐詩三百首", "content": [{"type": "五言絕句", "content": [
            {"chapter": "靜夜思", "author": "李白", "paragraphs": ["床前明月光，疑是地上霜。", "舉頭望明月，低頭思故鄉。"]}]}]},
        ensure_ascii=False), encoding="utf-8")
    (x / "werneror-poetry" / "汉.csv").write_text(
        '"题目","朝代","作者","内容"\n"江南","汉","佚名","江南可采莲，莲叶何田田，鱼戏莲叶间。鱼戏莲叶东，鱼戏莲叶西。"\n'
        '"仿江南","宋","某人","江南可采莲，荷花开满塘。小舟随水去，歌声满夕阳。"\n', encoding="utf-8")
    wanted = tmp_path / "school.json"
    wanted.write_text(json.dumps({"poems": [
        {"title": "静夜思", "author": "李白", "dynasty": "唐", "first": "床前明月光"},
        {"title": "江南", "author": "汉乐府", "dynasty": "汉", "first": "江南可采莲"},
        {"title": "画", "author": "王维", "dynasty": "唐", "first": "远看山有色"},
    ]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ls, "SCHOOL_LIST", wanted)
    report = ls.resolve_school_poems(x, log=lambda *a: None)
    assert report["found"] == 2 and report["missing"] == ["画 (王维)"]
    out = {p["title"]: p for p in json.loads((x / "school_poems.json").read_text(encoding="utf-8"))}
    assert "".join(out["静夜思"]["lines"]) == "床前明月光，疑是地上霜。举头望明月，低头思故乡。" and out["静夜思"]["book"] == "唐诗三百首"
    assert "鱼戏莲叶间" in "".join(out["江南"]["lines"])  # the anonymous Han poem, not the Song imitation by a named poet
    entry = next(ls.load_school_poems(x))
    assert "小学古诗" in entry["lead"] and "床前明月光" in entry["redirects"]


def test_character_dictionary_keeps_modern_senses():
    e = {"word": "猫", "oldword": "貓", "strokes": "11", "pinyin": "māo", "radicals": "犭",
         "explanation": "猫 \n\n 家猫,久已被人类驯养 \n\n 迎猫,为其食田鼠也。--《礼记》\n\n 猫（貓）māo家畜。面部略圆，脚有利爪，善长捕鼠。\n\n 猫（貓）máo\n\n"}
    text = ls.zidian_text(e)
    assert text.startswith("汉字「猫」:拼音māo,部首犭,11画,繁体写作貓。意思:家畜。") and "礼记" not in text


def test_dictionary_only_wins_when_asked_about_a_character(tmp_path):
    src = tmp_path / "src"
    x = src / "extra"
    x.mkdir(parents=True)
    cirrus(src / "simplewiki_content-20261018-00000.json.bz2", [wiki_doc("Cat", "Cats are small furry animals that many people keep as pets in their homes.", qid="Q2", links=500)])
    cirrus(src / "zhwiki_content-20261018-00000.json.bz2", [wiki_doc("貓", "貓是一種小型的哺乳動物,很多人把牠當作寵物養在家裡,喜歡抓老鼠。", qid="Q2", links=500)])
    (x / "word.json").write_text(json.dumps([{"word": "猫", "oldword": "貓", "strokes": "11", "pinyin": "māo", "radicals": "犭",
                                              "explanation": "猫（貓）māo家畜。面部略圆，脚有利爪，善长捕鼠。"}], ensure_ascii=False), encoding="utf-8")
    build(src, tmp_path / "library.db", workers=1, log=lambda *a: None)
    lib = Library(tmp_path / "library.db")
    assert lib.search("猫", "zh")[0].text.startswith("猫是")  # encyclopedia for "tell me about cats"
    assert lib.search("猫", "zh", intent="definition")[0].text.startswith("汉字「猫」")  # "猫字怎么写?"
    from curiosity_pet.library import definition_intent
    assert definition_intent("猫字怎么写?", "zh") == "definition" and definition_intent("猫为什么爱抓老鼠?", "zh") is None
    assert definition_intent("What does purr mean?", "en") == "definition"


def test_poem_and_character_targets_come_from_the_childs_words():
    from curiosity_pet.library import local_target
    assert local_target("鹅鹅鹅后面是什么?", "zh") == ("poem", "鹅鹅鹅")  # the model rewrite turned this into "鹅"
    assert local_target("你会背咏鹅吗?", "zh") == ("poem", "咏鹅")  # the model called this small talk
    assert local_target("床前明月光的下一句是什么?", "zh") == ("poem", "床前明月光")
    assert local_target("小池这首诗怎么背?", "zh") == ("poem", "小池")
    assert local_target("森林的森是什么部首?", "zh") == ("definition", "森")
    assert local_target("猫字怎么写?", "zh") == ("definition", "猫")
    assert local_target("好是什么意思?", "zh") == ("definition", "好")
    for q in ["我们下面玩什么?", "妈妈后面是什么?", "这个字怎么读?", "为什么天空是蓝色的?", "接下来你想做什么?"]:
        assert local_target(q, "zh") is None, q


def test_poem_question_uses_the_library_without_the_model(extra):
    from curiosity_pet.lookup import Researcher
    from curiosity_pet.search import LibraryProvider

    lib, _ = extra
    calls = []
    r = Researcher(store=None, enabled=True, contact="pet@example.org", providers=[LibraryProvider(lib)],
                   rewrite=lambda q, lang: calls.append(q) or {"kind": "chat", "topic": "other", "query": ""})
    d = r.decide("床前明月光的下一句是什么?", "zh")
    assert d.go and not d.online and d.intent == "poem" and calls == []  # local only, no rewrite
    assert r.fetch(d, "zh").title == "静夜思"
    d2 = r.decide("春晓的下一句是什么?", "zh")  # not in this small library: the usual flow (the model) decides
    assert calls == ["春晓的下一句是什么?"] and not d2.go


# ---------- The model's answer name, checked against the library ----------

def test_answer_entry_needs_exact_title_and_a_question_word(tmp_path):
    src = tmp_path / "src"
    (src / "extra").mkdir(parents=True)
    cirrus(src / "simplewiki_content-20261018-00000.json.bz2", [
        wiki_doc("Blue whale", "The blue whale is the largest animal on Earth. It lives in the ocean and eats krill.", qid="Q1", links=300),
        wiki_doc("Methuselah", "Methuselah was the son of Enoch in the Bible, said to have lived 969 years long ago.", qid="Q2", links=200),
        wiki_doc("Whale", "Whales are very large animals that live in the sea. They breathe air through a blowhole.", qid="Q3", links=900),
    ])
    (src / "extra" / "word.json").write_text("[]", encoding="utf-8")
    build(src, tmp_path / "library.db", workers=1, log=lambda *a: None)
    lib = Library(tmp_path / "library.db")
    assert lib.answer_entry("Blue whale", "biggest animal", "en").title == "Blue whale"
    assert lib.answer_entry("blue whale", "biggest animal", "en").title == "Blue whale"  # case and spaces do not matter
    assert lib.answer_entry("Methuselah", "oldest tree", "en") is None  # a namesake: no word of the question
    assert lib.answer_entry("Blue", "biggest animal", "en") is None  # no entry with exactly this title
    assert lib.answer_entry("", "biggest animal", "en") is None


from curiosity_pet.lookup import Researcher  # noqa: E402
from curiosity_pet.wiki import WikiResult  # noqa: E402


class Online:
    name = "wikipedia"

    def __init__(self):
        self.calls = []

    def search(self, query, lang):
        self.calls.append(query)
        return []


class AnswerLibrary:
    name, local, ranked, accepts_intent = "library", True, True, True

    def __init__(self):
        self.answers = []

    def search_answer(self, answer, query, lang):
        self.answers.append(answer)
        return WikiResult("蓝鲸", "蓝鲸是地球上最大的动物。", "u", "library") if answer == "蓝鲸" else None

    def search(self, query, lang, intent=None):
        return [WikiResult("脊索动物", "脊索动物是一类动物。", "u", "library")]


def test_fetch_tries_the_answer_name_first_and_never_sends_it_online():
    lib, online = AnswerLibrary(), Online()
    asked = []
    r = Researcher(store=None, enabled=True, contact="pet@example.org", providers=[lib, online],
                   rewrite=lambda q, lang: {"kind": "knowledge", "topic": "animals", "query": "最大 动物"},
                   guess=lambda q, lang: asked.append(q) or "蓝鲸")
    d = r.decide("世界上最大的动物是什么?", "zh")
    assert asked == []  # the answer-name call waits for fetch, so the filler is not delayed
    assert r.fetch(d, "zh").title == "蓝鲸" and d.answer == "蓝鲸" and online.calls == []
    # not a superlative or "who invented" question: no extra model call
    d2 = r.decide("长颈鹿的脖子为什么那么长?", "zh")
    r.fetch(d2, "zh")
    assert d2.answer == "" and asked == ["世界上最大的动物是什么?"]
    # an answer the library cannot confirm: the usual lookup; online providers get the query, never the answer name
    on = Online()
    r3 = Researcher(store=None, enabled=True, contact="pet@example.org", providers=[AnswerLibrary(), on],
                    rewrite=lambda q, lang: {"kind": "knowledge", "topic": "animals", "query": "最高 山"},
                    guess=lambda q, lang: "珠穆朗玛峰")
    d3 = r3.decide("世界上最高的山是哪座?", "zh")
    r3.providers[0].search = lambda query, lang, intent=None: []
    r3.fetch(d3, "zh")
    assert on.calls == ["最高 山"]


def test_guess_answer_parses_the_model_reply(monkeypatch):
    import httpx

    from curiosity_pet import lookup

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": json.dumps({"answer": " 蓝鲸 "}, ensure_ascii=False)}}

    sent = []
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: sent.append(json) or Resp())
    assert lookup.guess_answer("世界上最大的动物是什么?", "zh", model="m", base_url="http://127.0.0.1:11434") == "蓝鲸"
    assert "世界上最大的动物是什么?" in sent[0]["messages"][0]["content"]
    assert lookup.ANSWER_ASK.search("What is the fastest animal?") and lookup.ANSWER_ASK.search("世界上最高的楼是哪个?")
    assert not lookup.ANSWER_ASK.search("长颈鹿的脖子为什么那么长?") and not lookup.ANSWER_ASK.search("Why do cats purr?")
