"""The local library: built from CirrusSearch dump lines, searched offline before any web lookup."""

import bz2
import json

import pytest

from curiosity_pet import library, search
from curiosity_pet.library import Library, build, en_variants, zh_tokens
from curiosity_pet.lookup import Researcher
from curiosity_pet.search import LibraryProvider, from_settings, label
from curiosity_pet.wiki import WikiResult

pytest.importorskip("opencc")


def doc(title, lead, qid, links=10, redirects=(), templates=(), page_type="primary", categories=()):
    return {"namespace": 0, "page_type": page_type, "title": title, "opening_text": lead, "text": lead,
            "wikibase_item": qid, "incoming_links": links, "template": list(templates), "category": list(categories),
            "redirect": [{"namespace": 0, "title": r} for r in redirects]}


def write_shard(path, docs):
    with bz2.open(path, "wt", encoding="utf-8") as f:
        for i, d in enumerate(docs):
            f.write(json.dumps({"index": {"_id": i}}) + "\n")
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


EN = [
    doc("Zebra", "Zebras are African animals of the horse family. They have black and white stripes on their bodies.", "Q1", 800, ["Zebras"]),
    doc("Dragon Ball", "Dragon Ball is a Japanese manga series by Akira Toriyama about Goku and the seven Dragon Balls.", "Q9", 600),
    doc("Bee", "Bees are flying insects. They make honey and wax, and they help flowers by carrying pollen.", "Q2", 900),
    doc("Volcano", "A volcano is a mountain that has lava (hot, liquid rock) coming out from a magma chamber under the ground.", "Q3", 700),
    doc("Stripes (movie)", "Stripes is a 1981 American comedy movie about two friends who join the army, with no animals in it.", "Q4", 5),
    doc("Mercury", "Mercury may refer to the planet, the element or the Roman god, and other things with that name.", "Q5", 50,
        templates=["Template:Disambiguation"]),
    doc("Goku", "Goku is the main character of the Dragon Ball manga by Akira Toriyama. He is a strong and kind fighter.", "Q8", 300),
    doc("Zebras", "redirect", "", page_type="redirect"),
    doc("Tiny", "Too short.", "Q6"),
    doc("Adult thing", "This article is about an adult topic that a children's library does not need to keep at all.", "Q7",
        categories=["Pornography"]),
]
ZH = [
    doc("斑馬", "斑馬是生活在非洲草原上的動物,身上有黑白相間的條紋,屬於馬科,喜歡成群生活。", "Q1", 300, ["斑馬屬"]),
    doc("蜜蜂", "蜜蜂是一种会飞的昆虫,会采花蜜、酿蜂蜜,还会帮助花朵传粉,住在蜂巢里。", "Q2", 400),
    doc("七龍珠", "《七龍珠》是鳥山明創作的漫畫,講述孫悟空尋找七顆龍珠的冒險故事,非常受歡迎。", "Q9", 900),
    doc("孫悟空 (七龍珠)", "孫悟空是漫畫《七龍珠》的主角,是一個善良又很強的少年,喜歡和強者比武。", "Q8", 200),
    doc("某市长选举", "某市长选举是一次地方选举,有很多候选人参加,和动物一点关系都没有。", "Q999", 5000),
]


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    d = tmp_path_factory.mktemp("lib")
    src = d / "src"
    src.mkdir()
    write_shard(src / "simplewiki_content-20261018-00000.json.bz2", EN)
    write_shard(src / "zhwiki_content-20261018-00000.json.bz2", ZH)
    stats = build(src, d / "library.db", workers=1, log=lambda *a: None)
    assert stats["en"] == 6 and stats["zh"] == 4  # disambiguation, redirect, short and adult pages skipped; zh only matched QIDs
    return Library(d / "library.db")


def test_tokens_and_variants():
    assert zh_tokens("彩虹形成") == ["彩虹", "虹形", "形成"]
    assert zh_tokens("猫") == ["猫"] and zh_tokens("Goku 悟空") == ["goku", "悟空"]
    assert "zebra" in en_variants("zebras") and "bee" in en_variants("bees") and "butterfly" in en_variants("butterflies")
    assert "be" not in en_variants("bees") and "fox" in en_variants("foxes")


def test_chinese_is_simplified_and_keeps_the_real_url(lib):
    [r] = lib.search("斑马", "zh")[:1]
    assert r.title == "斑马" and "条纹" in r.text and r.host == "library"
    assert r.url.startswith("https://zh.wikipedia.org/zh-cn/") and "%E6%96%91%E9%A6%AC" in r.url  # original (traditional) title
    assert lib.search("斑马属", "zh")[0].title == "斑马"  # redirect titles are aliases
    assert lib.search("市长选举", "zh") == []  # unmatched articles are not in the library


def test_english_search_prefers_the_subject(lib):
    assert lib.search("zebras stripes", "en")[0].title == "Zebra"  # not "Stripes (movie)"
    assert lib.search("bees honey", "en")[0].title == "Bee"
    assert lib.search("volcano erupt", "en")[0].title == "Volcano"  # exact title, second word past the lead
    assert lib.search("mercury", "en") == []  # disambiguation page skipped
    assert lib.search("quantum chromodynamics", "en") == []


def test_qualified_title_wins_for_a_character_in_a_work(lib):
    assert lib.search("七龙珠 孙悟空", "zh")[0].title == "孙悟空 (七龙珠)"
    assert lib.search("Goku Dragon Ball", "en")[0].title == "Goku"


def test_leads_are_cleaned():
    assert library.clean_lead("32°49′48″N 34°58′17″E\ufeff / \ufeff32.83000°N 34.97139°E\ufeff / 32.83000; 34.97139 Saturn is a planet.") == "Saturn is a planet."
    assert library.clean_lead("注意：本条目所述主体由于各地翻译有所差异，您可依个人习惯选择。 《七龙珠》是漫画。") == "《七龙珠》是漫画。"
    assert library.clean_lead("Saturn is the sixth planet.") == "Saturn is the sixth planet."


def test_subject_word_must_appear(lib):
    assert lib.search("小斑马 条纹", "zh")[0].title == "斑马"  # "小" dropped for matching
    assert lib.search("星星 条纹", "zh") == []  # second word alone is not enough


def test_missing_database_returns_nothing(tmp_path):
    assert Library(tmp_path / "none.db").search("zebra", "en") == []


def researcher_with(providers, enabled=True, contact="pet@example.org"):
    return Researcher(store=None, enabled=enabled, contact=contact, providers=providers,
                      rewrite=lambda q, lang: {"kind": "knowledge", "topic": "animals", "query": "斑马 条纹"})


class Online:
    name = "wikipedia"

    def __init__(self):
        self.calls = []

    def search(self, query, lang):
        self.calls.append(query)
        return [WikiResult(query.split()[0], query + "。", "https://zh.wikipedia.org/wiki/x", "zh.wikipedia.org")]


def test_library_answers_first_without_going_online(lib):
    online = Online()
    r = researcher_with([LibraryProvider(lib), online])
    d = r.decide("斑马为什么有条纹?", "zh")
    assert d.go and d.online
    assert r.fetch(d, "zh").host == "library" and online.calls == []


def test_falls_through_to_online_when_the_library_has_nothing(lib):
    online = Online()
    r = Researcher(store=None, enabled=True, contact="pet@example.org", providers=[LibraryProvider(lib), online],
                   rewrite=lambda q, lang: {"kind": "knowledge", "topic": "animals", "query": "长颈鹿 脖子"})
    d = r.decide("长颈鹿的脖子为什么那么长?", "zh")
    assert r.fetch(d, "zh").host == "zh.wikipedia.org" and online.calls == ["长颈鹿 脖子"]


@pytest.mark.parametrize("enabled, contact", [(False, "pet@example.org"), (True, "")])
def test_offline_or_no_contact_still_uses_the_library_only(lib, enabled, contact):
    online = Online()
    r = researcher_with([LibraryProvider(lib), online], enabled=enabled, contact=contact)
    d = r.decide("斑马为什么有条纹?", "zh")
    assert d.go and not d.online
    assert r.fetch(d, "zh").host == "library" and online.calls == []
    # nothing in the library: still no web access
    r2 = Researcher(store=None, enabled=enabled, contact=contact, providers=[LibraryProvider(lib), online],
                    rewrite=lambda q, lang: {"kind": "knowledge", "topic": "space", "query": "黑洞"})
    assert r2.fetch(r2.decide("黑洞是什么?", "zh"), "zh") is None and online.calls == []


def test_sensitive_questions_are_not_looked_up_even_locally(lib):
    called = []
    r = Researcher(store=None, enabled=False, contact="", providers=[LibraryProvider(lib)],
                   rewrite=lambda q, lang: called.append(q) or {"kind": "knowledge", "topic": "other", "query": "死亡"})
    assert not r.decide("人死了会去哪里?", "zh").go and called == []


def test_provider_order_and_switch(lib):
    assert [p.name for p in from_settings({}, contact="c", library_path=lib.db_path)] == ["library", "wikipedia"]
    assert [p.name for p in from_settings({"library": False}, contact="c", library_path=lib.db_path)] == ["wikipedia"]
    assert label("library", "zh") == "小图书馆" and label("library", "en") == "my library"
    assert library.DB_PATH.name == "library.db" and search.LABELS["library"]
