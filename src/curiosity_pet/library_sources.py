"""Extra sources for the local library, beyond the Wikipedia opening paragraphs.

Each loader reads files the parent downloaded into DATA_DIR/library/src/extra (never into the repo) and yields
library entries: {"lang", "title", "lead", "url", "redirects" (aliases), "source"}. A missing file is skipped.

| Source | File | License |
|---|---|---|
| Vikidia (English encyclopedia for 8 to 13 year olds) | vikidia_en_all_nopic_*.zim (Kiwix) | CC BY-SA |
| Simple English Wiktionary (dictionary) | simplewiktionary_content-*.json.bz2 (CirrusSearch) | CC BY-SA |
| Wikijunior (children's books on Wikibooks) | enwikibooks_content-*.json.bz2, namespace 110 | CC BY-SA |
| Chinese idioms with origins, xiehouyu, character dictionary (字典) | idiom.json, xiehouyu.json, word.json (pwxcoo/chinese-xinhua) | MIT |
| Children's classics (三字经, 千字文, 千家诗, 唐诗三百首, 声律启蒙, 弟子规) | mengxue/*.json (chinese-poetry) | MIT |
| Poems taught in primary school (data/school_poems.json, texts resolved by `pet-library school-poems`) | chinese-poetry, Werneror/Poetry | MIT |
| Children's books: Aesop for Children, Grimm, Andersen, Just So Stories, Peter Rabbit, Real Mother Goose | gutenberg/pg*.html | Public domain in the US |

Xiehouyu are filtered: entries with crude words, violence, death, or jokes about disabilities and marriage are dropped.
A few Grimm tales too grim for a 7-year-old are left out.
"""

import bz2
import html
import json
import re
from pathlib import Path

from curiosity_pet.wiki import trim

CHUNK_CHARS = 600
MAX_CHUNKS = 10


def chunks(text: str, size: int = CHUNK_CHARS, limit: int = MAX_CHUNKS) -> list[str]:
    """Split text into pieces of up to about size characters, at sentence ends where possible."""
    text = re.sub(r"\s+", " ", text).strip()
    out = []
    while text and len(out) < limit:
        piece = trim(text, size)
        out.append(piece)
        text = text[len(piece):].strip()
    return out


def _entry(lang, title, lead, url, source, aliases=()):
    return {"lang": lang, "title": title, "lead": lead, "url": url, "source": source,
            "redirects": [a for a in dict.fromkeys(aliases) if a and a != title][:40], "qid": "", "links": 0}


def _cirrus(path: Path, namespace: int):
    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith('{"index"'):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("namespace") == namespace and d.get("page_type") != "redirect":
                yield d


# ---------- Vikidia ----------

PARAGRAPH = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S)
TAG = re.compile(r"<[^>]+>")
FOOTNOTE = re.compile(r"\[\d+\]|\[citation needed\]")


VIKIDIA_SKIP = re.compile(r"^SCP\b|creepypasta", re.I)  # horror fiction


def _html_paragraphs(page: str) -> list[str]:
    body = page.split('id="mw-content-text"', 1)[-1]
    paras = []
    for p in PARAGRAPH.findall(body):
        text = FOOTNOTE.sub("", html.unescape(TAG.sub("", p))).strip()
        if len(text) > 30:
            paras.append(re.sub(r"\s+", " ", text))
    return paras


def load_vikidia(extra: Path):
    files = sorted(extra.glob("vikidia_en_all_*.zim"))
    if not files:
        return
    from libzim.reader import Archive  # build-time dependency (dependency group "library")

    z = Archive(str(files[-1]))
    redirects: dict[str, list[str]] = {}
    articles = []
    for i in range(z.all_entry_count):
        e = z._get_entry_by_id(i)
        if e.is_redirect:
            try:
                redirects.setdefault(e.get_redirect_entry().path, []).append(e.title)
            except RuntimeError:
                pass
            continue
        item = e.get_item()
        if item.mimetype.startswith("text/html") and "/" not in e.path and e.path != "Main_Page":
            articles.append((e.path, e.title, item))
    for path, title, item in articles:
        paras = _html_paragraphs(bytes(item.content).decode("utf-8", "replace"))
        lead = trim(" ".join(paras), CHUNK_CHARS)
        if len(lead) < 60 or VIKIDIA_SKIP.search(title):
            continue
        yield _entry("en", title, lead, "https://en.vikidia.org/wiki/" + path, "vikidia", redirects.get(path, []))


# ---------- Simple English Wiktionary ----------

WIKT_PREFIX = [re.compile(p) for p in (
    r"^[\w\-]+(?: \+ [\w\-]+)+\s*",  # etymology like "hard + -en"
    r"^\S+ is on the Basic English 850 List\.\s*",
    r"^\S+ is one of the \d+ most common headwords\.\s*",
    r"^The Simple English Wikipedia has an article on: .*?(?=\(|IPA|$)",
    r"^\((?:UK|US|AU|NZ|CA|Australia|Canada|General American|Received Pronunciation|American|British)[^)]*\)\s*",
    r"^IPA \(key\): /[^/]*/(?:,?\s*/[^/]*/)*,?\s*",
    r"^Hyphenation: \S+\s*",
    r"^Homophones?: [\w’'\-]+(?:, [\w’'\-]+)*\s*",
    r"^Rhymes?: -\S+\s*",
    r"^Audio(?: \([^)]*\))?:?\s*",
)]


WIKT_FORM_ONLY = re.compile(
    r"^(?:\([^)]*\)\s*)?(?:The |An? )?(?:present participle|past tense|past participle|plural|third-person singular|"
    r"simple past|comparative|superlative|alternative spelling|alternative form|misspelling)\b[^.]*\bof\b", re.I)


def clean_wiktionary(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    changed = True
    while changed:
        changed = False
        for p in WIKT_PREFIX:
            new = p.sub("", text, count=1)
            if new != text:
                text, changed = new.strip(), True
    return text


def load_wiktionary(extra: Path):
    for path in sorted(extra.glob("simplewiktionary_content-*.json.bz2")):
        for d in _cirrus(path, 0):
            title = str(d.get("title") or "").strip()
            text = clean_wiktionary(str(d.get("text") or ""))
            if not title or len(text) < 30 or (len(text) < 90 and WIKT_FORM_ONLY.match(text)):
                continue
            yield _entry("en", title, trim(text, 400), "https://simple.wiktionary.org/wiki/" + title.replace(" ", "_"),
                         "wiktionary", [r.get("title") for r in d.get("redirect") or [] if isinstance(r, dict)])


# ---------- Wikijunior ----------

def load_wikijunior(extra: Path):
    for path in sorted(extra.glob("enwikibooks_content-*.json.bz2")):
        for d in _cirrus(path, 110):
            full = str(d.get("title") or "")
            name = full.split(":", 1)[-1]
            parts = name.split("/")
            book, chapter = parts[0], parts[-1]
            text = str(d.get("text") or "")
            if len(text) < 200 or chapter.lower() in {"contents", "introduction", "about", "authors", "cover"}:
                continue
            title = f"{chapter} ({book})" if len(parts) > 1 else book
            url = "https://en.wikibooks.org/wiki/" + full.replace(" ", "_")
            for n, piece in enumerate(chunks(text)):
                yield _entry("en", title, piece, url, "wikijunior", [chapter] if n == 0 else [])


# ---------- Chinese idioms and xiehouyu ----------

XINHUA_URL = "https://github.com/pwxcoo/chinese-xinhua"
XIEHOUYU_BLOCK = re.compile(
    r"屁|屎|尿|粪|裤裆|奶|乳|骚|婊|嫖|娼|妓|淫|姘|寡妇|阉|太监|光棍|老婆|媳妇|偷汉|尼姑|和尚|丈母|小妾|"
    r"死|鬼|杀|血|刀|枪|棺|坟|尸|吊|砍|宰|斩|毒|赌|偷|贼|嫖|"
    r"麻子|瞎子|瘸子|聋子|哑巴|秃子|傻子|疯|驼背|罗锅|癞|瘫|残废|跛|结巴|"
    r"操|日你|妈的|狗日|王八|龟孙|杂种|婆娘|骂"
)
NOTE = re.compile(r"（[^）]*）|\([^)]*\)")


def load_idioms(extra: Path):
    path = extra / "idiom.json"
    if not path.exists():
        return
    for e in json.loads(path.read_text(encoding="utf-8")):
        word, expl = str(e.get("word") or "").strip(), str(e.get("explanation") or "").strip()
        if not word or not expl:
            continue
        lead = f"成语{word}({e.get('pinyin', '')}):{expl}"
        origin = str(e.get("derivation") or "").strip()
        if origin and origin not in ("无", "暂无"):
            lead += f" 出处:{origin}"
        yield _entry("zh", word, trim(lead, CHUNK_CHARS), XINHUA_URL, "idiom")


def load_xiehouyu(extra: Path):
    path = extra / "xiehouyu.json"
    if not path.exists():
        return
    seen = set()
    for e in json.loads(path.read_text(encoding="utf-8")):
        riddle = NOTE.sub("", str(e.get("riddle") or "")).strip()
        answers = [a.strip() for a in NOTE.sub("", str(e.get("answer") or "")).split("；") if a.strip()]
        if not riddle or not answers or riddle in seen or XIEHOUYU_BLOCK.search(riddle + "".join(answers)):
            continue
        seen.add(riddle)
        yield _entry("zh", riddle, f"歇后语:{riddle}——{'；'.join(answers[:2])}", XINHUA_URL, "xiehouyu")


def xiehouyu_counts(extra: Path) -> tuple[int, int]:
    """(entries in the file, entries kept after filtering)."""
    path = extra / "xiehouyu.json"
    if not path.exists():
        return 0, 0
    return len(json.loads(path.read_text(encoding="utf-8"))), sum(1 for _ in load_xiehouyu(extra))


# ---------- 蒙学: classic children's readers and poems ----------

POETRY_URL = "https://github.com/chinese-poetry/chinese-poetry"
WERNEROR_URL = "https://github.com/Werneror/Poetry"
CLAUSE = re.compile(r"[，。？！；、,.?!;\s]+")


def _clauses(lines) -> list[str]:
    return [c for line in lines for c in CLAUSE.split(line) if 3 <= len(c) <= 9]


def _windows(lines: list[str], size: int, step: int):
    for start in range(0, max(1, len(lines) - size + step), step):
        part = lines[start : start + size]
        if part:
            yield start // step + 1, part


def load_mengxue(extra: Path):
    folder = extra / "mengxue"
    if not folder.is_dir():
        return
    import opencc

    cc = opencc.OpenCC("t2s")

    def read(name):
        p = folder / f"{name}.json"
        return json.loads(cc.convert(p.read_text(encoding="utf-8"))) if p.exists() else None

    # Readers in short lines: overlapping windows so a line and the one after it are always in one entry
    for name, size, step in (("sanzijing-new", 4, 3), ("qianziwen", 6, 5)):
        d = read(name)
        if not d:
            continue
        book = d["title"]
        for n, part in _windows(d["paragraphs"], size, step):
            yield _entry("zh", f"{book}(第{n}段)", f"《{book}》:{''.join(part)}", POETRY_URL, "poetry", [book, *_clauses(part)])
    d = read("dizigui")
    if d:
        for chapter in d["content"]:
            for n, part in _windows(chapter["paragraphs"], 4, 3):
                yield _entry("zh", f"弟子规·{chapter['chapter']}(第{n}段)", f"《弟子规·{chapter['chapter']}》:{' '.join(part)}",
                             POETRY_URL, "poetry", ["弟子规", *_clauses(part)])
    d = read("shenglvqimeng")
    if d:
        for volume in d["content"]:
            for rhyme in volume["content"]:
                for n, para in enumerate(rhyme["paragraphs"], 1):
                    name = re.sub(r"\s+", "", rhyme["chapter"])
                    yield _entry("zh", f"声律启蒙·{name}({n})", f"《声律启蒙·{name}》:{para}", POETRY_URL, "poetry",
                                 ["声律启蒙", *_clauses([para])[:12]])
    seen = set()
    for name in ("tangshisanbaishou", "qianjiashi"):
        d = read(name)
        if not d:
            continue
        book = d["title"]
        for group in d["content"]:
            for poem in group["content"]:
                title = str(poem.get("chapter") or "").strip()
                author = re.sub(r"[（(].*?[)）]", "", str(poem.get("author") or "")).strip()
                lines = [str(x) for x in poem.get("paragraphs") or []]
                if not title or not lines or (title, lines[0]) in seen:
                    continue
                seen.add((title, lines[0]))
                lead = f"《{title}》({author},选自{book}):{''.join(lines)}"
                yield _entry("zh", title, trim(lead, CHUNK_CHARS), POETRY_URL, "poetry", [f"{author}{title}", *_clauses(lines)])


# ---------- Project Gutenberg children's books ----------

GUTENBERG_BOOKS = {
    19994: "The Aesop for Children", 2591: "Grimms' Fairy Tales", 1597: "Andersen's Fairy Tales",
    2781: "Just So Stories", 14838: "The Tale of Peter Rabbit", 10607: "The Real Mother Goose",
}
# Too frightening for a 7-year-old, left out
GUTENBERG_SKIP = {"THE ROBBER BRIDEGROOM", "THE JUNIPER TREE", "FITCHER'S BIRD", "THE GIRL WITHOUT HANDS"}
FRONT_MATTER = re.compile(r"project gutenberg|contents|list of|illustrat|^by |pictures by|^\d{4}$|rand|license|preface|introduction|milo winter|aesop for children$|brothers grimm fairy tales", re.I)


def _title_case(s: str) -> str:
    small = {"a", "an", "and", "the", "of", "in", "on", "to", "his", "her", "by", "for", "at", "with", "that", "who"}
    words = s.lower().split()
    return " ".join(w if i and w in small else w[:1].upper() + w[1:] for i, w in enumerate(words))


def gutenberg_stories(page: str, book: str) -> list[tuple[str, str]]:
    """(title, text) per story: h2 headings, Mother Goose's bold rhyme titles, or the whole book when it has none."""
    page = page.split("*** START OF", 1)[-1].split("*** END OF", 1)[0]
    page = page.split("***", 1)[-1] if "***" in page[:400] else page  # rest of the START line
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S)
    def title_marker(m):
        return "\n@@TITLE@@" + re.sub(r"\s+", " ", TAG.sub("", m.group(1))).strip() + "\n"

    page = re.sub(r'<div class="boldtitle">(.*?)</div>', title_marker, page, flags=re.S)
    page = re.sub(r"<h2\b[^>]*>(.*?)</h2>", title_marker, page, flags=re.S)
    page = re.sub(r"<br\s*/?>|</p>|</div>", "\n", page)
    text = html.unescape(TAG.sub("", page))
    parts = text.split("@@TITLE@@")
    stories = []
    if len(parts) == 1:
        body = re.sub(r"\s+", " ", parts[0]).strip()
        return [(book, body)] if body else []
    for part in parts[1:]:
        head, _, body = part.partition("\n")
        head = re.sub(r"\s+", " ", head).strip()
        body = re.sub(r"\s+", " ", body).strip()
        if not head or FRONT_MATTER.search(head) or head.upper() in GUTENBERG_SKIP or len(body) < 80:
            continue
        stories.append((_title_case(head), body))
    return stories


def load_gutenberg(extra: Path):
    folder = extra / "gutenberg"
    for book_id, book in GUTENBERG_BOOKS.items():
        path = folder / f"pg{book_id}.html"
        if not path.exists():
            continue
        url = f"https://www.gutenberg.org/ebooks/{book_id}"
        for title, body in gutenberg_stories(path.read_text(encoding="utf-8", errors="replace"), book):
            full = title if title == book else f"{title} ({book})"
            for n, piece in enumerate(chunks(body)):
                yield _entry("en", full, piece, url, "gutenberg", [title] if n == 0 else [])





def load_extras(extra: Path):
    """(source name, list of entries) for every source found in the folder."""
    extra = Path(extra)
    if not extra.is_dir():
        return
    for loader in LOADERS:
        items = list(loader(extra))
        if items:
            yield items[0]["source"], items


# ---------- School poems (resolved once, then loaded like the other sources) ----------

SCHOOL_LIST = Path(__file__).parent / "data" / "school_poems.json"
HAN = re.compile(r"[^㐀-鿿]")
ANY_AUTHOR = {"汉乐府", "北朝民歌", "诗经", "古诗十九首"}  # no single poet: the source must say anonymous
ANONYMOUS = {"", "佚名", "无名氏", "作者未详", "乐府", "汉乐府", "北朝民歌", "诗经", "古诗十九首"}
POEM_NOTE = re.compile(r"\s*[(（][^()（）]*[)）]")


def _norm(text: str) -> str:
    return HAN.sub("", text)


def _poem_corpus(extra: Path, cc):
    """(book, title, author, lines) for every poem in the local chinese-poetry files, preferred books first."""
    import glob

    for name in ("tangshisanbaishou", "qianjiashi"):
        p = extra / "mengxue" / f"{name}.json"
        if p.exists():
            d = json.loads(cc.convert(p.read_text(encoding="utf-8")))
            for group in d["content"]:
                for poem in group["content"]:
                    yield d["title"], poem.get("chapter", ""), poem.get("author", ""), poem.get("paragraphs") or []
    root = extra / "chinese-poetry"
    for pattern, book in (("全唐诗/poet.tang.*.json", "全唐诗"), ("全唐诗/poet.song.*.json", "全宋诗"), ("宋词/ci.song.*.json", "宋词")):
        for f in sorted(glob.glob(str(root / pattern))):
            for poem in json.loads(cc.convert(Path(f).read_text(encoding="utf-8"))):
                title = poem.get("title") or poem.get("rhythmic") or ""
                yield book, title, poem.get("author", ""), poem.get("paragraphs") or []
    p = root / "诗经" / "shijing.json"
    if p.exists():
        for poem in json.loads(cc.convert(p.read_text(encoding="utf-8"))):
            yield "诗经", poem.get("title", ""), "诗经", poem.get("content") or []


def _werneror(extra: Path):
    """Werneror/Poetry (MIT): one CSV per dynasty, simplified, columns 题目, 朝代, 作者, 内容."""
    import csv

    folder = extra / "werneror-poetry"
    for f in sorted(folder.glob("*.csv")):
        with f.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                content = row.get("内容") or ""
                lines = re.findall(r"[^。！？]+[。！？]?", content)
                yield "古诗词库", row.get("题目", ""), row.get("作者", ""), [x.strip() for x in lines if x.strip()]


def _clause_start(lines: list[str], hint: str) -> int | None:
    """Index of the clause where the hint starts (a poem's line, not a word inside one), or None."""
    clauses = [c for c in (_norm(x) for x in CLAUSE.split("".join(lines))) if c]
    for j in range(len(clauses)):
        if "".join(clauses[j : j + 4]).startswith(hint):
            return j
    return None


def _excerpt(lines: list[str], start: int) -> list[str]:
    """The whole poem when short; for a long piece (a stanza of 诗经, one of a numbered series) the four clauses
    from the matched line, with their punctuation."""
    if len(_norm("".join(lines))) <= 120:
        return lines
    clauses = [c for c in (_norm(x) for x in CLAUSE.split("".join(lines))) if c]
    for line in lines:  # a stanza stored as one line (诗经)
        if clauses[start] in _norm(line) and len(_norm(line)) <= 80:
            return [line]
    pieces = re.findall(r"[^，。？！；、]+[，。？！；、]?", "".join(lines))
    pieces = [x for x in pieces if _norm(x)]
    chosen = pieces[start : start + 4]
    return ["".join(chosen[:2]), "".join(chosen[2:])] if len(chosen) == 4 else ["".join(chosen)]


def resolve_school_poems(extra: Path, log=print) -> dict:
    """Look up the text of every poem in data/school_poems.json and write extra/school_poems.json.

    Sources, best first: 唐诗三百首 and 千家诗 (they carry the versions taught in school), then chinese-poetry's
    全唐诗, 全宋诗, 宋词 and 诗经, then Werneror/Poetry for Han, Northern and Southern dynasties, Yuan, Ming and Qing.
    A poem counts as found only when its known first line starts a line of the text and the author matches."""
    import itertools

    import opencc

    cc = opencc.OpenCC("t2s")
    wanted = json.loads(SCHOOL_LIST.read_text(encoding="utf-8"))["poems"]
    found: dict[int, dict] = {}
    rank = {"唐诗三百首": 3, "千家诗": 3, "全唐诗": 2, "全宋诗": 2, "宋词": 2, "诗经": 2, "古诗词库": 1}
    for book, title, author, lines in itertools.chain(_poem_corpus(extra, cc), _werneror(extra)):
        lines = [POEM_NOTE.sub("", x) for x in lines if isinstance(x, str)]
        text = _norm("".join(lines))
        if len([c for c in CLAUSE.split("".join(lines)) if _norm(c)]) < 4:  # a fragment, not a poem
            continue
        for i, w in enumerate(wanted):
            names = [w["author"], *w.get("alt_author", [])]
            if w["author"] in ANY_AUTHOR:
                author_ok = author.strip() in ANONYMOUS or w["author"] in author
            else:
                author_ok = bool(author) and any(n in author or author in n for n in names)
            if not author_ok:
                continue
            for variant, first in enumerate([w["first"], *w.get("alt", [])]):
                h = _norm(first)
                start = _clause_start(lines, h) if h in text else None
                if start is None:
                    continue
                base = _norm(w["title"].split("（")[0].split("·")[0])
                score = (variant == 0) * 100 + rank[book] * 10 + (base in _norm(title)) * 5 - len(text) / 1000
                if i not in found or score > found[i]["score"]:
                    found[i] = {"score": score, "book": book, "lines": _excerpt(lines, start), "found_title": title,
                                "variant": variant > 0, "url": WERNEROR_URL if book == "古诗词库" else POETRY_URL}
    out, missing, books = [], [], {}
    for i, w in enumerate(wanted):
        if i in found:
            f = found[i]
            out.append({**w, "lines": f["lines"], "book": f["book"], "source_title": f["found_title"], "url": f["url"],
                        "variant": f["variant"]})
            books[f["book"]] = books.get(f["book"], 0) + 1
        else:
            missing.append(f"{w['title']} ({w['author']})")
    (extra / "school_poems.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"School poems: {len(out)} of {len(wanted)} found {books}; missing: {missing or 'none'}")
    return {"found": len(out), "wanted": len(wanted), "books": books, "missing": missing}


def load_school_poems(extra: Path):
    path = extra / "school_poems.json"
    if not path.exists():
        return
    for p in json.loads(path.read_text(encoding="utf-8")):
        lines = [str(x) for x in p["lines"]]
        lead = f"《{p['title']}》({p['dynasty']}·{p['author']},小学古诗):{''.join(lines)}"
        if p.get("variant"):
            lead += f"(这是古籍里的版本,课本里的版本有个别字不同,第一句是\"{p['first']}\")"
        elif p.get("textbook"):
            lead += f"(这是古籍里的版本,{p['textbook']})"
        opening = _norm("".join(lines))
        yield _entry("zh", p["title"], trim(lead, CHUNK_CHARS), p["url"], "poetry",
                     [f"{p['author']}{p['title']}", p["first"], opening[:3], opening[:5], opening[:7], *_clauses(lines)])


# ---------- Chinese character dictionary (字典) ----------

PINYIN = "a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüɡńňǹḿ"
CLASSIC_LINE = re.compile(r"--《|——《|。注")


def zidian_text(e: dict, cc=None) -> str:
    """Pinyin, radical, strokes, traditional form and the modern senses, without classical quotations.

    The modern part starts at a heading such as "猫（貓）māo" or "好hǎo"; the heading with the main pinyin wins."""
    char = e["word"]
    expl = str(e.get("explanation") or "")
    main = str(e.get("pinyin") or "").replace("ɡ", "g").split(",")[0].strip()
    heads = [m for m in re.finditer(rf"{re.escape(char)}(?:（.）)?\s*([{PINYIN}]+)", expl) if m.start() > 0 or True]
    heads = [m for m in heads if m.group(1)]
    pick = next((m for m in heads if m.group(1).replace("ɡ", "g") == main), heads[0] if heads else None)
    if pick:
        modern = expl[pick.end():]
        nxt = re.search(rf"\n\s*{re.escape(char)}(?:（.）)?\s*[{PINYIN}]+", modern)
        modern = modern[: nxt.start()] if nxt else modern
    else:
        modern = " ".join(ln.strip() for ln in expl.splitlines() if ln.strip() and not CLASSIC_LINE.search(ln))
    modern = re.sub(r"\s+", " ", modern.replace("～", char)).strip()
    modern = re.sub(r"⒈|⒉|⒊|⒋|⒌|⒍|⒎|⒏|⒐", lambda m: " " + str("⒈⒉⒊⒋⒌⒍⒎⒏⒐".index(m.group()) + 1) + ".", modern).strip()
    modern = re.sub(r"(?:\s*\d\.\s*)+(?=\d\.|$)", " ", modern).strip()  # empty numbered senses
    old = e.get("oldword") or ""
    head = f"汉字「{char}」:拼音{main},部首{e.get('radicals', '')},{e.get('strokes', '')}画"
    if old and old != char and (cc is None or cc.convert(old) == char):
        head += f",繁体写作{old}"
    return trim(f"{head}。意思:{modern}", 400)


def load_zidian(extra: Path):
    path = extra / "word.json"
    if not path.exists():
        return
    import opencc

    cc = opencc.OpenCC("t2s")
    for e in json.loads(path.read_text(encoding="utf-8")):
        char = str(e.get("word") or "").strip()
        if len(char) != 1 or not e.get("explanation"):
            continue
        aliases = [f"{char}字"]
        old = e.get("oldword") or ""
        if old and old != char and cc.convert(old) == char:
            aliases.append(old)
        yield _entry("zh", char, zidian_text(e, cc), XINHUA_URL, "zidian", aliases)


LOADERS = [load_vikidia, load_wiktionary, load_wikijunior, load_idioms, load_xiehouyu, load_zidian, load_mengxue,
           load_school_poems, load_gutenberg]
