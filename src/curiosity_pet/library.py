"""The local library ("小图书馆"): an offline copy of child-relevant Wikipedia articles, searched before going online.

Sources are Wikimedia's CirrusSearch dumps (plain text, no wikitext to parse), downloaded once into
DATA_DIR/library/src. English is Simple English Wikipedia (written for children and learners); Chinese keeps the
zh.wikipedia articles about the same concepts (matched by Wikidata item), converted to Simplified Chinese.
Simple English Wikipedia already covers Chinese culture topics a child asks about (Journey to the West, Chinese New
Year, Sun Wukong). Well-linked or much-viewed Chinese articles outside that set were measured and left out: they are
mostly counties, elections, politicians, celebrities and TV dramas.
Only the title, the opening paragraph (about 600 characters), redirect titles and the page URL are kept.
Extra child-level sources (Vikidia, Simple English Wiktionary, Wikijunior, Chinese idioms and xiehouyu, classic
children's readers and poems, six Project Gutenberg children's books) are added from src/extra by library_sources.py.
Entries whose title or opening sentence centers on serial killers, sexual violence, massacres, terror attacks or
horror films are dropped from every source.

Search is SQLite full-text search: English words with the Porter stemmer, Chinese as character bigrams.
Exact title or redirect matches come first. Nothing leaves the machine, so a local lookup needs no Wikipedia
contact info and works with online lookup switched off. The relevance check in lookup.py still decides whether
a hit is used; when nothing relevant is found locally the online providers are tried.

Wikipedia text is CC BY-SA; this copy is for private family use and keeps each article's URL.

Build:  uv run --group library pet-library build      (about 10 minutes for both languages)
Try:    uv run pet-library search "彩虹" zh
"""

import argparse
import bz2
import json
import math
import re
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from urllib.parse import quote

from curiosity_pet import config
from curiosity_pet.wiki import DISAMBIGUATION_MARKERS, WikiResult, trim

LIB_DIR = config.DATA_DIR / "library"
DB_PATH = LIB_DIR / "library.db"
SRC_DIR = LIB_DIR / "src"
HOST = "library"
LEAD_CHARS = 600
MIN_LEAD_CHARS = {"en": 60, "zh": 30}
# Optional: also keep Chinese articles outside the Simple English set when this many pages link to them (0 = off)
ZH_MIN_LINKS = 0
DISAMBIGUATION_TEMPLATES = {
    "template:disambiguation", "template:disambig", "template:dab", "template:geodis", "template:hndis",
    "template:disambiguation/cat", "template:消歧义", "template:消歧義", "template:disambig/cat",
}
# Articles a children's library does not need, by category name
ADULT_CATEGORY = re.compile(
    r"pornograph|sex(ual)? (act|position|industry|work)|erotic|prostitut|fetish|色情|性行为|性行為|性交|性工作|情色|卖淫|賣淫|成人影片|AV女优|AV女優",
    re.IGNORECASE,
)
CJK = re.compile(r"[㐀-鿿豈-﫿]+")
ASCII_WORD = re.compile(r"[a-z0-9]+")
# Leading clutter in CirrusSearch opening text: coordinates ("32°49′48″N 34°58′17″E / 32.83; 34.97") and
# Chinese Wikipedia notices ("注意：本条目所述主体由于各地翻译有所差异…。", "本条目含有蒙古文字母…。")
COORD_TOKEN = re.compile(r"^\s*(?:-?[\d.]+°(?:[\d.]+′)?(?:[\d.]+″)?\s*[NSEW]?|-?\d+\.\d+|[/;\ufeff\u200b])\s*")
NOTICE = re.compile(r"^\s*(?:注意：|本条目|本條目)[^。]*。\s*")
# Not for a 7-year-old's library, judged on the title and the first sentence only (so that "Julius Caesar ... was
# murdered" further on stays)
GRIM = re.compile(
    r"serial killer|mass murder|murderer|\brapist|\brape\b|sexual (?:assault|abuse)|massacre|terrorist attack|"
    r"horror (?:film|movie)|slasher|creepypasta|"
    r"连环杀手|杀人犯|杀人魔|杀人事件|杀人案|凶杀|谋杀案|血案|惨案|强奸|性侵|屠杀|恐怖袭击|恐怖片|恐怖电影|血腥|分尸|"
    r"\bmurder case\b|\bkilling spree\b",
    re.IGNORECASE,
)
# Child-level sources get a small ranking bonus over encyclopedia articles (which have link counts instead)
SOURCE_BONUS = {"vikidia": 0.15, "wikijunior": 0.15, "idiom": 0.15, "poetry": 0.15, "gutenberg": 0.1}
# Dictionary entries are short and dense: they win only when the child asks what a word means, how a character
# is written or read. The intent is read from the child's own words (the rewritten query often drops "什么意思").
DEFINITION_WORDS = {"mean", "means", "meaning", "definition", "define", "word", "spell", "spelling",
                    "意思", "字", "拼音", "笔画", "部首", "组词", "读音"}
DEFINITION_ASK = {
    "zh": re.compile(r"什么意思|啥意思|意思是|是什么字|这个字|那个字|怎么写|怎么读|读什么|读音|拼音|笔画|几画|部首|偏旁|组词|造句"),
    "en": re.compile(r"\bmeans?\b|\bmeaning\b|\bdefin(e|ition)\b|\bspell(ed|ing)?\b|\bwhat word\b", re.IGNORECASE),
}
DICTIONARY_SOURCES = {"wiktionary", "zidian"}
DICTIONARY_BONUS = {True: 0.3, False: -0.25}


# Poem and character questions are answered from the library with words taken straight from the child's question:
# the model rewrite turns "鹅鹅鹅后面是什么?" into "鹅" and calls "你会背咏鹅吗?" small talk.
# These lookups are local only, so the child's words never leave the machine.
HAN = r"[\u4e00-\u9fff]"
POEM_AFTER = re.compile(rf"({HAN}{{2,14}}?)的?(?:下一句|上一句|后一句|前一句|下句|上句)"
                        rf"|({HAN}{{3,14}}?)的?(?:后面|下面|前面|接下来)(?:是什么|是啥|一句)")
POEM_RECITE = re.compile(rf"(?:会背|背一下|背给我听|背背|背诵|会不会背|能背)(?:一下)?(?:这首|那首)?(?:诗|古诗)?({HAN}{{2,12}}?)(?:这首诗|那首诗|这首古诗)?(?:吗|呢|吧|给我听|$)")
POEM_THIS = re.compile(rf"({HAN}{{2,12}}?)(?:这首诗|那首诗|这首古诗)")
POEM_LEAD = re.compile(r"^(?:你知道|请问|那么|那|你会背|你能背|你会|我想问|问你)")
CHAR_ASK = [
    re.compile(rf"({HAN}{{1,4}})的({HAN})(?:字)?(?:是|怎么|有|的|读|几)"),  # 森林的森是什么部首
    re.compile(rf"(?<![这那个])({HAN})字(?:怎么|是|有|的|读|几|什么)"),  # 猫字怎么写
    re.compile(rf"^({HAN})(?:是什么意思|什么意思|怎么写|怎么读|有几画|是什么部首)"),  # 好是什么意思
]


def local_target(question: str, lang: str) -> tuple[str, str] | None:
    """("poem", line or title) or ("definition", character) taken from a Chinese question, else None."""
    if lang != "zh":
        return None
    q = re.sub(r"[\s,，。.!！?？、:：“”\"']+", "", question)
    for pattern in (POEM_AFTER, POEM_RECITE, POEM_THIS):
        m = pattern.search(q)
        if m:
            target = POEM_LEAD.sub("", next(g for g in m.groups() if g)).strip("的")
            if 2 <= len(target) <= 14:
                return "poem", target
    for i, pattern in enumerate(CHAR_ASK):
        m = pattern.search(q)
        if m:
            if i == 0:
                word, char = m.group(1), m.group(2)
                if char in word:
                    return "definition", char
                continue
            return "definition", m.group(1)
    return None


# ---------- Idiom stories and poems, served from the library ----------
# Real failures before this: "给我讲个成语故事" got 画蛇添足 told wrong three times, "这首诗想表达什么" got the meaning of
# 《江雪》 wrong, "你会背多少首唐诗?" looked up an unrelated idiom. These requests are recognized here and answered with the
# library entry (plus a parent-approved note from qa.py when there is one), never from the model's memory alone.

IDIOM_STORY_LIST = Path(__file__).parent / "data" / "idiom_stories.json"
POEM_THEMES = {
    "春": "春柳燕", "夏": "夏荷蝉莲", "秋": "秋枫霜菊", "冬": "冬雪寒冰", "雪": "雪", "月": "月", "山": "山", "水": "水江河",
    "江": "江", "河": "河", "花": "花", "鸟": "鸟鹂鹅燕莺", "雨": "雨", "风": "风", "树": "树柳", "家": "家乡故", "朋友": "友君送",
}
ASK_IDIOM = re.compile(r"成语故事|讲(?:个|一个|个好听的)?成语|成语.{0,4}(?:故事|讲讲)|的故事|讲讲|这个成语")
ASK_RECITE = re.compile(r"(?:背|念|读)(?:一首|首|个|一个|几首|一下)?(?:唐诗|古诗|诗)|会背.{0,6}(?:唐诗|古诗|诗)")
ASK_COUNT = re.compile(r"(?:会背|知道|有)(?:多少|几)首(?:唐诗|古诗|诗)|会背(?:多少|几首)")
ASK_THEME = re.compile(r"(?:关于|写)(.{1,4}?)的(?:唐诗|古诗|诗)|(春天|夏天|秋天|冬天|月亮|雪|花|山|水|江|鸟|雨|风|树)的(?:唐诗|古诗|诗)")
ASK_MEANING = re.compile(r"(?:想)?(?:表达|讲|说|写)(?:的是)?(?:什么|啥)|是什么意思|什么意思|啥意思|意思是什么|讲的什么")
ASK_AGAIN = re.compile(r"^(?:不对|不是|错了|你说错了|你讲错了|不是这个意思|不是这样|不是这样的|说错了|讲错了)")
THIS_POEM = re.compile(r"这首诗|这首古诗|那首诗|这首|这个诗")
THIS_IDIOM = re.compile(r"这个成语|那个成语")


def library_request(question: str, lang: str) -> tuple[str, str] | None:
    """(kind, detail) for requests answered with an idiom or poem entry: ("idiom", ""), ("poem", ""), ("poem_theme", "冬"),
    ("poem_count", ""), ("poem_meaning", ""), ("idiom_meaning", ""), ("again", ""). Names and titles are found later
    against the library. Chinese only."""
    if lang != "zh":
        return None
    q = re.sub(r"[\s,，。.!！?？、:：“”\"']+", "", question)
    if ASK_AGAIN.match(q) and len(q) <= 14:
        return "again", ""
    if ASK_COUNT.search(q):
        return "poem_count", ""
    m = ASK_THEME.search(q)
    if m:
        theme = next(g for g in m.groups() if g)
        key_ = next((k for k in POEM_THEMES if k in theme), None)
        if key_:
            return "poem_theme", key_
    if THIS_POEM.search(q) and ASK_MEANING.search(q):
        return "poem_meaning", ""
    if THIS_IDIOM.search(q) and ASK_MEANING.search(q):
        return "idiom_meaning", ""
    if ASK_RECITE.search(q):
        return "poem", ""
    if ASK_IDIOM.search(q):
        return "idiom", ""
    if ASK_MEANING.search(q):
        return "meaning", ""  # "画蛇添足是什么意思" / "江雪是什么意思": only if a known idiom or poem title is named
    return None



def definition_intent(question: str, lang: str) -> str | None:
    """"definition" when the child asks what a word means or how a character is written or read."""
    return "definition" if DEFINITION_ASK["zh" if lang == "zh" else "en"].search(question) else None
KEY_STRIP = re.compile(r"[\s\-_·・,，.。:：;；!！?？'\"“”‘’()（）《》「」]+")

SCHEMA = """
CREATE TABLE docs(id INTEGER PRIMARY KEY, lang TEXT, title TEXT, lead TEXT, url TEXT, qid TEXT, links INTEGER, source TEXT);
CREATE TABLE aliases(lang TEXT, key TEXT, doc INTEGER);
CREATE VIRTUAL TABLE fts_en USING fts5(title, body, content='', tokenize='porter unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE fts_zh USING fts5(title, body, content='', tokenize='unicode61');
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


# ---------- text helpers ----------

def key(text: str) -> str:
    """Normalized form for exact title and redirect matching."""
    return KEY_STRIP.sub("", text.lower())


def clean_lead(text: str) -> str:
    text = text.replace("\u200b", "").strip()
    if re.match(r"^\s*-?\d+(?:\.\d+)?°", text):
        while True:
            stripped = COORD_TOKEN.sub("", text, count=1)
            if stripped == text:
                break
            text = stripped
    while NOTICE.match(text):
        text = NOTICE.sub("", text, count=1)
    return text.strip()


def too_grim(title: str, lead: str) -> bool:
    first = re.split(r"(?<=[.!?。！？])\s", lead.strip(), maxsplit=1)[0][:300]
    return bool(GRIM.search(title) or GRIM.search(first))


def zh_variants(term: str) -> list[str]:
    """A Chinese word and its form without the diminutive "小" that children add ("小猫" -> "猫")."""
    out = [term]
    if len(term) >= 2 and term.startswith("小"):
        out.append(term[1:])
    return out


def zh_tokens(text: str, unigrams: bool = False) -> list[str]:
    """Character bigrams for runs of Chinese characters (plus single characters when asked), lowercase ASCII words."""
    out = []
    for m in re.finditer(r"[㐀-鿿豈-﫿]+|[A-Za-z0-9]+", text):
        run = m.group().lower()
        if not CJK.fullmatch(run):
            out.append(run)
            continue
        if unigrams or len(run) == 1:
            out.extend(run)
        out.extend(run[i : i + 2] for i in range(len(run) - 1))
    return out


def en_variants(term: str) -> list[str]:
    """A word and its likely singular, for exact title matching ("zebras" -> "zebra", "bees" -> "bee")."""
    t = term.lower()
    out = [t]
    if len(t) > 3 and t.endswith("ies"):
        out.append(t[:-3] + "y")
    elif len(t) > 4 and t.endswith("es") and t[:-2].endswith(("s", "x", "z", "ch", "sh")):
        out += [t[:-2]]  # boxes, foxes, peaches (but "bees" -> "bee", never "be")
    elif len(t) > 3 and t.endswith("es"):
        out.append(t[:-1])
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        out.append(t[:-1])
    return out


def article_url(lang: str, title: str) -> str:
    host = "simple.wikipedia.org/wiki/" if lang == "en" else "zh.wikipedia.org/zh-cn/"
    return "https://" + host + quote(title.replace(" ", "_"))


# ---------- reading the dumps ----------

def iter_docs(path: Path):
    """Articles from one CirrusSearch dump shard (JSON lines, bz2): skips index lines, redirects and other namespaces."""
    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith('{"index"'):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("namespace") != 0 or d.get("page_type") == "redirect":
                continue
            yield d


def is_disambiguation(doc: dict, lead: str) -> bool:
    if any(t.lower() in DISAMBIGUATION_TEMPLATES for t in doc.get("template") or []):
        return True
    return any(m in lead[:200] for m in DISAMBIGUATION_MARKERS)


def extract(doc: dict, lang: str) -> dict | None:
    """The fields the library keeps, or None for articles it skips."""
    title = str(doc.get("title") or "").strip()
    lead = clean_lead(str(doc.get("opening_text") or doc.get("text") or ""))
    if not title or len(lead) < MIN_LEAD_CHARS[lang] or is_disambiguation(doc, lead):
        return None
    if any(ADULT_CATEGORY.search(c) for c in doc.get("category") or []):
        return None
    redirects = [r["title"] for r in doc.get("redirect") or [] if isinstance(r, dict) and r.get("namespace") == 0 and r.get("title")]
    return {
        "title": title,
        "lead": trim(lead, LEAD_CHARS),
        "qid": doc.get("wikibase_item") or "",
        "links": int(doc.get("incoming_links") or 0),
        "redirects": redirects[:30],
    }


def _scan_zh_shard(args) -> tuple[list[dict], int]:
    """Worker: Chinese articles in one shard that match the English set or are well linked, converted to Simplified."""
    path, qids, min_links = args
    import opencc  # build-time dependency (dependency group "library")

    cc = opencc.OpenCC("t2s")
    kept, seen = [], 0
    for doc in iter_docs(Path(path)):
        seen += 1
        if doc.get("wikibase_item") not in qids and not (min_links and int(doc.get("incoming_links") or 0) >= min_links):
            continue
        item = extract(doc, "zh")
        if item is None:
            continue
        item["url"] = article_url("zh", item["title"])
        item["title"] = cc.convert(item["title"])
        item["lead"] = cc.convert(item["lead"])
        item["redirects"] = [cc.convert(r) for r in item["redirects"]]
        kept.append(item)
    return kept, seen


# ---------- building ----------

def _insert(db: sqlite3.Connection, lang: str, items) -> int:
    fts = "fts_en" if lang == "en" else "fts_zh"
    n = 0
    for it in items:
        if too_grim(it["title"], it["lead"]):
            continue
        cur = db.execute(
            "INSERT INTO docs(lang, title, lead, url, qid, links, source) VALUES (?,?,?,?,?,?,?)",
            (lang, it["title"], it["lead"], it["url"], it.get("qid", ""), it.get("links", 0), it.get("source", "wikipedia")),
        )
        doc_id = cur.lastrowid
        keys = {key(it["title"])} | {key(r) for r in it["redirects"]}
        db.executemany("INSERT INTO aliases(lang, key, doc) VALUES (?,?,?)", [(lang, k, doc_id) for k in keys if k])
        if lang == "en":
            title_text, body_text = it["title"] + " " + " ".join(it["redirects"]), it["lead"]
        else:
            title_text = " ".join(zh_tokens(it["title"] + " " + " ".join(it["redirects"]), unigrams=True))
            body_text = " ".join(zh_tokens(it["lead"]))
        db.execute(f"INSERT INTO {fts}(rowid, title, body) VALUES (?,?,?)", (doc_id, title_text, body_text))
        n += 1
    return n


def build(src_dir: Path = SRC_DIR, db_path: Path = DB_PATH, zh_min_links: int = ZH_MIN_LINKS, workers: int = 6, log=print) -> dict:
    """Build the library database from the dump shards in src_dir; replaces the old database only when done."""
    src_dir, db_path = Path(src_dir), Path(db_path)
    en_files = sorted(src_dir.glob("simplewiki_content-*.json.bz2"))
    zh_files = sorted(src_dir.glob("zhwiki_content-*.json.bz2"))
    if not en_files:
        raise FileNotFoundError(f"No simplewiki_content-*.json.bz2 in {src_dir}")
    tmp = db_path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    t0 = time.time()

    en_items, qids, en_seen = [], set(), 0
    for f in en_files:
        for doc in iter_docs(f):
            en_seen += 1
            item = extract(doc, "en")
            if item:
                item["url"] = article_url("en", item["title"])
                en_items.append(item)
                if item["qid"]:
                    qids.add(item["qid"])
    with db:
        n_en = _insert(db, "en", en_items)
    log(f"English: {n_en} of {en_seen} articles ({time.time() - t0:.0f} s)")
    del en_items

    n_zh, zh_seen = 0, 0
    if zh_files:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for kept, seen in pool.map(_scan_zh_shard, [(str(f), qids, zh_min_links) for f in zh_files]):
                zh_seen += seen
                with db:
                    n_zh += _insert(db, "zh", kept)
                log(f"Chinese: {n_zh} kept of {zh_seen} scanned ({time.time() - t0:.0f} s)")

    from curiosity_pet.library_sources import load_extras

    extras = {}
    for source, items in load_extras(src_dir / "extra"):
        with db:
            extras[source] = extras.get(source, 0) + _insert(db, items[0]["lang"], items)
        log(f"{source}: {extras[source]} entries ({time.time() - t0:.0f} s)")

    with db:
        db.execute("CREATE INDEX aliases_key ON aliases(lang, key)")
        db.executemany("INSERT INTO meta VALUES (?,?)", [
            ("built", time.strftime("%Y-%m-%d %H:%M")), ("sources", " ".join(f.name for f in en_files + zh_files)),
            ("en_articles", str(n_en)), ("zh_articles", str(n_zh)), ("zh_min_links", str(zh_min_links)),
            *((f"{k}_entries", str(v)) for k, v in extras.items()),
        ])
    db.execute("INSERT INTO fts_en(fts_en) VALUES ('optimize')")
    db.execute("INSERT INTO fts_zh(fts_zh) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(db_path)
    stats = {"en": n_en, "zh": n_zh, "en_scanned": en_seen, "zh_scanned": zh_seen, **extras,
             "seconds": round(time.time() - t0), "mb": round(db_path.stat().st_size / 1e6)}
    log(f"Done: {stats}")
    return stats


# ---------- searching ----------

class _Text:
    """Word matching for ranking: Chinese by substring; English by whole word (and its singular), or by prefix for
    words of five letters or more ("erupt" in "eruption"), so that "bee" does not match "been"."""

    def __init__(self, text: str, lang: str):
        self.lang = lang
        self.lower = text.lower()
        if lang == "en":
            self.words = {v for w in ASCII_WORD.findall(self.lower) for v in en_variants(w)}

    def has(self, term: str) -> bool:
        if self.lang == "zh":
            return term in self.lower
        if " " in term:
            return term in self.lower
        return term in self.words or (len(term) >= 5 and any(w.startswith(term) for w in self.words))


QUALIFIED = re.compile(r"^(.+?)\s*[(（](.+)[)）]$")


def _qualified(title: str, variants: list[list[str]]) -> bool:
    """"孙悟空 (七龙珠)" for "七龙珠 孙悟空": the base title is one query word and the qualifier holds another."""
    m = QUALIFIED.match(title.lower())
    if not m or len(variants) < 2:
        return False
    base, qualifier = key(m.group(1)), m.group(2)
    for i, vs in enumerate(variants):
        if any(key(v) == base for v in vs):
            return any(any(v in qualifier for v in other) for j, other in enumerate(variants) if j != i)
    return False

class Library:
    """Read-only access to library.db. Each search opens its own connection (the server answers on worker threads)."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)

    def available(self) -> bool:
        return self.db_path.exists()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def search(self, query: str, lang: str, limit: int = 3, intent: str | None = None) -> list[WikiResult]:
        """Best matches first. Candidates come from exact title or redirect matches and full-text search, and are
        ranked by how many query words appear in the title and the opening paragraph (counting simple English
        plurals), whether the title is an exact match, and how well linked the article is. Candidates missing
        too many query words are dropped, so an empty list means "nothing here, try online"."""
        terms = [t for t in query.split() if t]
        if not terms or not self.available():
            return []
        lang = "zh" if lang == "zh" else "en"
        try:
            with self._connect() as db:
                exact = self._exact(db, terms, lang)  # doc id -> (level, indexes of the words its title or a redirect matched)
                ids = list(dict.fromkeys(list(exact) + self._fulltext(db, terms, lang)))
                if not ids:
                    return []
                rows = db.execute(
                    f"SELECT id, title, lead, url, links, source FROM docs WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        except sqlite3.Error:
            return []
        variants = [zh_variants(t.lower()) if lang == "zh" else en_variants(t) for t in terms]
        wants_definition = intent == "definition" or any(t.lower() in DEFINITION_WORDS for t in terms)
        wants_poem = intent == "poem"
        scored = []
        for doc_id, title, lead, url, links, source in rows:
            t, body = _Text(title, lang), _Text(lead, lang)
            matched = exact[doc_id][1] if doc_id in exact else set()  # a redirect match counts as the word in the title
            in_title = sum(i in matched or any(t.has(v) for v in vs) for i, vs in enumerate(variants)) / len(variants)
            in_either = sum(i in matched or any(t.has(v) or body.has(v) for v in vs) for i, vs in enumerate(variants))
            # An article titled exactly like a query word is about the subject even when the other words fall
            # past the kept opening paragraph ("volcano erupt" -> Volcano), so it needs only half of the words
            if doc_id in exact:
                needed = math.ceil(len(variants) / 2)
            else:
                needed = len(variants) if len(variants) <= 2 else math.ceil(len(variants) * 2 / 3)
            # The first word is usually the subject: an article that never mentions it is about something else
            # ("星星 眨眼" must not return the article on eye blinking)
            first_present = 0 in matched or any(t.has(v) or body.has(v) for v in variants[0])
            if in_either < needed or (len(variants) > 1 and not first_present):
                continue
            score = (0.6 * in_title + 0.4 * _qualified(title, variants) + 0.4 * in_either / len(variants)
                     + (0.3 + 0.1 * (exact[doc_id][0] == 0) if doc_id in exact else 0.0)
                     + 0.15 * min(1.0, math.log1p(links) / math.log1p(2000)) + SOURCE_BONUS.get(source, 0.0)
                     + (DICTIONARY_BONUS[wants_definition] if source in DICTIONARY_SOURCES else 0.0)
                     + (0.4 if wants_poem and source == "poetry" else 0.0))
            scored.append((score, WikiResult(title=title, text=lead, url=url, host=HOST)))
        scored.sort(key=lambda x: -x[0])
        # One entry per title: a story or book chapter is stored in several pieces, keep the best-matching piece
        out, seen = [], set()
        for _, r in scored:
            if (r.title, r.url) not in seen:
                seen.add((r.title, r.url))
                out.append(r)
        return out[:limit]

    def answer_entry(self, answer: str, query: str, lang: str) -> WikiResult | None:
        """The entry titled exactly like the model's answer name ("蓝鲸", "Blue whale"), if it also mentions a word of the
        rewritten query ("动物", "animal"). The second check rejects namesakes: for "oldest tree" the model said
        "Methuselah", and the library's Methuselah is the biblical person. Encyclopedia-like sources only (no dictionary
        entries or xiehouyu); among same-titled entries the child-level source wins, then the better linked one."""
        name = key(answer)
        terms = [t for t in query.split() if t]
        if not name or not terms or not self.available():
            return None
        lang = "zh" if lang == "zh" else "en"
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT d.id, d.title, d.lead, d.url, d.links, d.source FROM aliases a JOIN docs d ON d.id = a.doc "
                    "WHERE a.lang = ? AND a.key = ?", [lang, name]).fetchall()
        except sqlite3.Error:
            return None
        variants = [zh_variants(t.lower()) if lang == "zh" else en_variants(t) for t in terms]
        if lang == "zh":  # the rewrite sometimes keeps a phrase ("世界上最高的楼"): its character pairs count too
            variants += [[t[i : i + 2]] for t in terms if len(t) >= 3 for i in range(len(t) - 1)]
        best, best_score = None, None
        for _, title, lead, url, links, source in rows:
            if source in DICTIONARY_SOURCES or source == "xiehouyu":
                continue
            base = QUALIFIED.match(title.lower())
            if name not in {key(title), key(base.group(1)) if base else None}:
                continue  # matched a redirect, not the title
            t, body = _Text(title, lang), _Text(lead, lang)
            if not any(t.has(v) or body.has(v) for vs in variants for v in vs if key(v) != name):
                continue  # mentions no word of the question: a namesake
            score = (SOURCE_BONUS.get(source, 0.0), links or 0)
            if best_score is None or score > best_score:
                best, best_score = WikiResult(title=title, text=lead, url=url, host=HOST), score
        return best

    def _exact(self, db, terms: list[str], lang: str) -> dict[int, tuple[int, set]]:
        """Docs whose title or a redirect equals the whole query or one of its words, best linked first.
        Level 0: the whole query or the first word (usually the subject), 1: another word; plus the matched word indexes."""
        groups = [["".join(terms)] if lang == "zh" else [" ".join(terms)]]
        groups += [zh_variants(t) if lang == "zh" else en_variants(t) for t in terms]
        out: dict[int, tuple[int, set]] = {}
        for i, group in enumerate(groups):
            words = set(range(len(terms))) if i == 0 else {i - 1}
            keys = [key(k) for k in group if key(k)]
            if not keys:
                continue
            rows = db.execute(
                f"SELECT d.id FROM aliases a JOIN docs d ON d.id = a.doc WHERE a.lang = ? AND a.key IN ({','.join('?' * len(keys))}) "
                "ORDER BY d.links DESC LIMIT 5", [lang, *keys]).fetchall()
            for (doc_id,) in rows:
                level, seen = out.get(doc_id, (0 if i <= 1 else 1, set()))
                out[doc_id] = (min(level, 0 if i <= 1 else 1), seen | words)
        return out

    def _fulltext(self, db, terms: list[str], lang: str) -> list[int]:
        if lang == "en":
            words = [w for t in terms for w in ASCII_WORD.findall(t.lower())]
            if not words:
                return []
            match = " OR ".join(f'"{w}"' for w in words)
            table = "fts_en"
        else:
            phrases = []
            for t in terms:
                toks = zh_tokens(t)
                if toks:
                    phrases.append('"' + " ".join(toks) + '"')
            if not phrases:
                return []
            match = " OR ".join(phrases)
            table = "fts_zh"
        rows = db.execute(
            f"SELECT f.rowid, bm25({table}, 8.0, 1.0) AS score, d.links FROM {table} f JOIN docs d ON d.id = f.rowid "
            f"WHERE {table} MATCH ? ORDER BY score LIMIT 40", [match]).fetchall()
        # bm25 is negative (lower is better); well-linked articles get a small boost on near ties
        rows.sort(key=lambda r: r[1] - 0.3 * math.log1p(r[2]))
        return [r[0] for r in rows[:15]]

    # ----- idioms and poems -----

    def _titles(self, where: str) -> list[str]:
        try:
            with self._connect() as db:
                return [r[0] for r in db.execute(f"SELECT DISTINCT title FROM docs WHERE lang = 'zh' AND {where}")]
        except sqlite3.Error:
            return []

    def idiom_titles(self) -> set:
        if not hasattr(self, "_idioms"):
            self._idioms = set(self._titles("source = 'idiom'"))
        return self._idioms

    def poem_titles(self) -> list[str]:
        """Titles of the primary-school poems and other poems (not reader passages such as 三字经(第3段))."""
        if not hasattr(self, "_poems"):
            titles = self._titles("source = 'poetry'")
            self._poems = sorted((t for t in titles if "(第" not in t and "·" not in t[:5] or t.startswith(("清平乐", "西江月", "浣溪沙"))),
                                 key=len, reverse=True)
        return self._poems

    def find_idiom(self, text: str) -> str | None:
        """An idiom named in the child's words (4 to 8 characters; question words such as 什么意思 never count)."""
        han = re.sub(r"[^\u4e00-\u9fff]", "", text)
        idioms = self.idiom_titles()
        for n in (4, 5, 6, 7, 8):
            for i in range(len(han) - n + 1):
                gram = han[i : i + n]
                if gram in idioms and not re.search(r"什么|怎么|为什么|意思|故事|成语|一个|这个", gram):
                    return gram
        return None

    def find_poem(self, text: str) -> str | None:
        for title in self.poem_titles():
            if len(title) >= 2 and title in text:
                return title
        return None

    def _entry(self, where: str, args) -> tuple | None:
        try:
            with self._connect() as db:
                rows = db.execute(f"SELECT title, lead, url FROM docs WHERE lang = 'zh' AND {where}", args).fetchall()
        except sqlite3.Error:
            return None
        if not rows:
            return None
        # a primary-school poem entry ("小学古诗") is preferred over the same poem from another collection
        rows.sort(key=lambda r: "小学古诗" not in r[1])
        return rows[0]

    def idiom_entry(self, name: str, qa=None) -> WikiResult | None:
        row = self._entry("source = 'idiom' AND title = ?", [name])
        if not row:
            return None
        note = qa.note(name, "idiom_story", "zh") if qa else None
        text = (f"故事:{note.a} " if note else "") + row[1]
        return WikiResult(title=row[0], text=text, url=row[2], host=HOST)

    def poem_entry(self, title: str, qa=None, meaning: bool = False) -> WikiResult | None:
        row = self._entry("source = 'poetry' AND title = ?", [title])
        if not row:
            return None
        text = row[1]
        if meaning and qa:
            first = re.sub(r"^.*?:", "", text)[:5]
            note = qa.note(title, "poem_note", "zh", first_line=first)
            if note:
                text = f"{text} 大意:{note.a}"
        return WikiResult(title=row[0], text=text, url=row[2], host=HOST)

    def school_poems(self) -> list[tuple]:
        try:
            with self._connect() as db:
                return db.execute("SELECT title, lead, url FROM docs WHERE lang = 'zh' AND source = 'poetry' AND lead LIKE '%小学古诗%' "
                                  "ORDER BY id").fetchall()
        except sqlite3.Error:
            return []

    def story_idioms(self) -> list[str]:
        try:
            names = json.loads(IDIOM_STORY_LIST.read_text(encoding="utf-8"))["idioms"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return []
        have = self.idiom_titles()
        return [n for n in names if n in have]

    def info(self) -> dict:
        if not self.available():
            return {}
        with self._connect() as db:
            return dict(db.execute("SELECT key, value FROM meta").fetchall())


def main():
    ap = argparse.ArgumentParser(prog="pet-library", description="Build or query the local library")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build library.db from the dumps in the source directory")
    b.add_argument("--src", default=str(SRC_DIR))
    b.add_argument("--db", default=str(DB_PATH))
    b.add_argument("--zh-min-links", type=int, default=ZH_MIN_LINKS)
    b.add_argument("--workers", type=int, default=6)
    s = sub.add_parser("search", help="search the library")
    s.add_argument("query")
    s.add_argument("lang", nargs="?", default="zh")
    sub.add_parser("info", help="show what the library holds")
    sub.add_parser("school-poems", help="look up the texts of the school poem list (data/school_poems.json) in the downloaded poetry collections")
    sub.add_parser("qa", help="review the child Q&A library (pet-library qa --help)", add_help=False)
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "qa":
        from curiosity_pet.qa import cli

        return cli(sys.argv[2:])
    args = ap.parse_args()
    if args.cmd == "build":
        build(Path(args.src), Path(args.db), args.zh_min_links, args.workers)
    elif args.cmd == "search":
        t0 = time.perf_counter()
        results = Library().search(args.query, args.lang)
        print(f"{len(results)} results in {1000 * (time.perf_counter() - t0):.0f} ms")
        for r in results:
            print(f"- {r.title}  {r.url}\n  {r.text[:160]}")
    elif args.cmd == "school-poems":
        from curiosity_pet.library_sources import resolve_school_poems

        resolve_school_poems(SRC_DIR / "extra")
    else:
        print(json.dumps(Library().info(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
