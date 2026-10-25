"""Reviewed child Q&A: short answers to the questions a 7-year-old asks, written offline by a large model and approved
by the parent before the child hears them (CLAUDE.md "Knowledge base", source priority 1).

Seed files live in the repo (data/qa_zh.json, data/qa_en.json). The parent's verdicts live outside git in
DATA_DIR/library/qa_status.json, so every family reviews its own copy. Every entry starts as "pending" and is never
served until approved; a rejected entry is never served. Approvals take effect at once (the status file is re-read
when it changes), with no rebuild and no server restart.

Kinds:
  qa           a question and its answer ("为什么天空是蓝色的?")
  poem_note    the meaning of a primary-school poem, attached when the child asks what a poem means
  idiom_story  the story of an idiom in kid words, attached when the child asks for it

Review:  uv run pet-library qa stats | list [--status pending] [--lang zh] [--kind qa] | show ID
         uv run pet-library qa review [--lang zh]      (one entry at a time: a = approve, r = reject, s = skip, q = quit)
         uv run pet-library qa approve ID... | reject ID...
"""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from curiosity_pet import config

SEED_DIR = Path(__file__).parent / "data"
STATUS_PATH = config.DATA_DIR / "library" / "qa_status.json"
STATUSES = ("pending", "approved", "rejected")

# Question words and particles that every child question shares; removed before comparing questions
ZH_FILLER = re.compile(r"为什么|为啥|怎么样|怎么|什么|是不是|有没有|能不能|会不会|我想知道|我想问你|我问你|问你|请问|你知道|告诉我|你说|那么|"
                       r"一下|吗|呢|呀|啊|吧|嘛|了|的|是|会|要|能|都|还|那")
EN_STOP = {"why", "what", "how", "who", "where", "when", "which", "do", "does", "did", "is", "are", "was", "were", "a", "an", "the",
           "to", "of", "in", "on", "at", "for", "and", "or", "it", "its", "they", "them", "their", "we", "our", "you", "your", "i",
           "me", "my", "can", "could", "would", "will", "be", "so", "that", "this", "there", "have", "has", "get", "gets", "make",
           "makes", "tell", "about", "really", "please", "know"}


@dataclass
class QA:
    id: str
    lang: str
    q: str
    a: str
    kind: str = "qa"
    topic: str = ""
    alt: list = field(default_factory=list)
    ref: str = ""  # poem title or idiom for notes
    check: str = ""  # what the answer rests on, for the reviewer


ZH_STOP = set("为什么 为啥 什么 怎么 怎么样 是不是 有没有 能不能 会不会 可不可以 为何 如何 哪里 哪儿 吗 呢 呀 啊 吧 嘛 了 的 地 得 "
              "是 会 要 能 都 还 那 那么 这 这个 那个 一个 个 些 我 你 他 她 它 我们 你们 他们 想 问 知道 请问 告诉 说 一下 "
              "有 在 和 跟 就 也 又 很 太 可以 为 被 把 让 到 去 来 着 过 呢 么 啦 哦 嗯".split())
_jieba = None


def _zh_tokens(text: str) -> set:
    """Content words of a Chinese question (jieba's fine-grained cut, question words and particles removed)."""
    global _jieba
    if _jieba is None:
        import logging

        import jieba

        jieba.setLogLevel(logging.ERROR)
        _jieba = jieba
    han = re.sub(r"[^\u4e00-\u9fff]", " ", text)
    return {w for w in _jieba.cut_for_search(han) if w.strip() and w not in ZH_STOP}


def _stem(w: str) -> str:
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3 and not w.endswith("ss"):
            w = w[: len(w) - len(suf)] + rep
            break
    if w.endswith("y") and len(w) > 4:  # windy -> wind, cloudy -> cloud, rainy -> rain
        w = w[:-1]
    return w


def _en_words(text: str) -> set:
    out = set()
    for w in re.findall(r"[a-z']+", text.lower()):
        w = w.replace("'s", "").strip("'")
        if len(w) > 2 and w not in EN_STOP:
            out.add(_stem(w))
    return out


def similarity(child: str, phrase: str, lang: str) -> float:
    """Overlap of the content words of the child's question and a stored one, counted both ways (Dice): words the
    child adds count against the match, so "星星为什么会眨眼睛?" does not match "为什么要眨眼睛?" (people blinking).
    One shared word is enough only when both questions are that short ("为什么打雷?")."""
    a, b = (_zh_tokens(child), _zh_tokens(phrase)) if lang == "zh" else (_en_words(child), _en_words(phrase))
    shared = len(a & b)
    if not a or not b or shared == 0 or (shared == 1 and max(len(a), len(b)) > 2):
        return 0.0
    return 2 * shared / (len(a) + len(b))


class QAStore:
    def __init__(self, seed_dir: Path = SEED_DIR, status_path: Path = STATUS_PATH):
        self.seed_dir = Path(seed_dir)
        self.status_path = Path(status_path)
        self._entries: dict[str, QA] | None = None
        self._status: dict = {}
        self._status_mtime = None

    # ---------- loading ----------

    def entries(self) -> dict[str, QA]:
        if self._entries is None:
            self._entries = {}
            for lang in ("zh", "en"):
                path = self.seed_dir / f"qa_{lang}.json"
                if not path.exists():
                    continue
                for e in json.loads(path.read_text(encoding="utf-8")):
                    qa = QA(id=e["id"], lang=lang, q=e["q"], a=e["a"], kind=e.get("kind", "qa"), topic=e.get("topic", ""),
                            alt=list(e.get("alt", [])), ref=e.get("ref", ""), check=e.get("check", ""))
                    self._entries[qa.id] = qa
        return self._entries

    def _statuses(self) -> dict:
        try:
            mtime = self.status_path.stat().st_mtime
        except FileNotFoundError:
            self._status, self._status_mtime = {}, None
            return self._status
        if mtime != self._status_mtime:
            try:
                self._status = json.loads(self.status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._status = {}
            self._status_mtime = mtime
        return self._status

    def status(self, qa_id: str) -> str:
        return self._statuses().get(qa_id, {}).get("status", "pending")

    def set_status(self, ids, status: str) -> int:
        assert status in STATUSES
        known = self.entries()
        data = dict(self._statuses())
        n = 0
        for qa_id in ids:
            if qa_id not in known:
                continue
            if status == "pending":
                data.pop(qa_id, None)
            else:
                data[qa_id] = {"status": status, "at": time.strftime("%Y-%m-%d %H:%M")}
            n += 1
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.status_path)
        self._status_mtime = None
        return n

    def approved(self, lang: str | None = None, kind: str | None = None) -> list[QA]:
        return [e for e in self.entries().values()
                if (lang is None or e.lang == lang) and (kind is None or e.kind == kind) and self.status(e.id) == "approved"]

    # ---------- use ----------

    def candidates(self, question: str, lang: str, floor: float = 0.4, k: int = 3) -> list[tuple[float, QA]]:
        scored = []
        for e in self.approved(lang, "qa"):
            score = max(similarity(question, p, lang) for p in [e.q, *e.alt])
            if score >= floor:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]

    def match(self, question: str, lang: str, judge=None) -> QA | None:
        """The approved Q&A entry the child's question asks, or None.

        Word overlap alone confuses questions with the same words and a different meaning ("冰为什么会化?" and "水为什么
        会结冰?", 21% wrong in a leave-one-out test), so it only proposes up to three candidates. An exact match (all
        content words the same, no close second) is used directly; otherwise the local model picks the candidate that
        asks the same thing, or none. Without a judge only exact matches count."""
        cands = self.candidates(question, lang)
        if not cands:
            return None
        top, second = cands[0][0], cands[1][0] if len(cands) > 1 else 0.0
        if top >= 0.999 and second < 0.6:
            return cands[0][1]
        if judge is None:
            return None
        try:
            pick = judge(question, [e.q for _, e in cands], lang)
        except Exception:  # noqa: BLE001  a failed judge only means "no reviewed answer"
            return None
        return cands[pick - 1][1] if isinstance(pick, int) and 1 <= pick <= len(cands) else None

    def note(self, ref: str, kind: str, lang: str = "zh", first_line: str = "") -> QA | None:
        """The approved note for a poem or idiom (when two poems share a title, the one naming the first line)."""
        cands = [e for e in self.approved(lang, kind) if e.ref == ref]
        if len(cands) > 1 and first_line:
            cands = [e for e in cands if first_line[:4] in e.q + " ".join(e.alt)] or cands
        return cands[0] if cands else None


JUDGE_PROMPT = {
    "zh": "孩子的问题:{q}\n候选问题:\n{c}\n哪一个候选和孩子问的是同一个问题(意思一样,同一个答案就能回答)?都不是就写0。只输出 JSON:{{\"same\": 编号}}",
    "en": "The child's question: {q}\nCandidate questions:\n{c}\nWhich candidate asks the same thing (one answer fits both)? "
          "Write 0 if none. Output JSON only: {{\"same\": number}}",
}


def judge_with_model(question: str, candidates: list[str], lang: str) -> int:
    """Local model: which candidate question means the same as the child's (1-based), 0 for none."""
    import httpx

    from urllib.parse import urlparse

    from curiosity_pet.llm import LOCAL_HOSTS

    if urlparse(config.OLLAMA_URL).hostname not in LOCAL_HOSTS:
        return 0
    listing = "\n".join(f"{i}. {c}" for i, c in enumerate(candidates, 1))
    body = {"model": config.HELPER_MODEL, "messages": [{"role": "user", "content": JUDGE_PROMPT[lang].format(q=question, c=listing)}],
            "stream": False, "think": False, "format": "json", "options": {"temperature": 0}}
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=20)
    r.raise_for_status()
    value = json.loads(r.json()["message"]["content"]).get("same", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------- review CLI (pet-library qa ...) ----------

def _line(e: QA, status: str) -> str:
    return f"{e.id:<12} {status:<9} {e.kind:<11} {e.topic:<10} {e.q}"


def cli(argv: list[str]) -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="pet-library qa", description="Review the child Q&A library")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=STATUSES)
    ls.add_argument("--lang", choices=["zh", "en"])
    ls.add_argument("--kind", choices=["qa", "poem_note", "idiom_story"])
    ls.add_argument("--limit", type=int, default=0)
    sh = sub.add_parser("show")
    sh.add_argument("ids", nargs="+")
    for name in ("approve", "reject", "reset"):
        p = sub.add_parser(name, help=f"mark entries {name}d" if name != "reset" else "mark entries pending again")
        p.add_argument("ids", nargs="+")
    rv = sub.add_parser("review", help="go through pending entries one by one")
    rv.add_argument("--lang", choices=["zh", "en"])
    rv.add_argument("--kind", choices=["qa", "poem_note", "idiom_story"])
    args = ap.parse_args(argv)
    store = QAStore()
    entries = store.entries()

    if args.cmd == "stats":
        counts: dict = {}
        for e in entries.values():
            key = (e.lang, e.kind, store.status(e.id))
            counts[key] = counts.get(key, 0) + 1
        print(f"{len(entries)} entries ({store.status_path})")
        for (lang, kind, status), n in sorted(counts.items()):
            print(f"  {lang} {kind:<11} {status:<9} {n}")
    elif args.cmd == "list":
        rows = [e for e in entries.values() if (not args.lang or e.lang == args.lang) and (not args.kind or e.kind == args.kind)
                and (not args.status or store.status(e.id) == args.status)]
        for e in rows[: args.limit or None]:
            print(_line(e, store.status(e.id)))
        print(f"({len(rows)} entries)")
    elif args.cmd == "show":
        for qa_id in args.ids:
            e = entries.get(qa_id)
            if not e:
                print(f"{qa_id}: not found")
                continue
            print(f"{e.id} [{store.status(e.id)}] {e.kind} {e.topic} {e.ref}\n  Q: {e.q}\n  also: {' / '.join(e.alt)}\n  A: {e.a}\n  basis: {e.check}\n")
    elif args.cmd in ("approve", "reject", "reset"):
        status = {"approve": "approved", "reject": "rejected", "reset": "pending"}[args.cmd]
        ids = [i for i in args.ids if i in entries]
        missing = [i for i in args.ids if i not in entries]
        print(f"{store.set_status(ids, status)} marked {status}" + (f"; not found: {' '.join(missing)}" if missing else ""))
    elif args.cmd == "review":
        todo = [e for e in entries.values() if store.status(e.id) == "pending"
                and (not args.lang or e.lang == args.lang) and (not args.kind or e.kind == args.kind)]
        print(f"{len(todo)} pending. a = approve, r = reject, s = skip, q = quit")
        for e in todo:
            print(f"\n{e.id} {e.kind} {e.topic} {e.ref}\n  Q: {e.q}\n  A: {e.a}\n  basis: {e.check}")
            choice = input("  [a/r/s/q] > ").strip().lower()
            if choice == "q":
                break
            if choice in ("a", "r"):
                store.set_status([e.id], "approved" if choice == "a" else "rejected")
