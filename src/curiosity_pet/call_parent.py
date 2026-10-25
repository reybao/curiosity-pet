"""Call a parent: "叫爸爸来", "我要妈妈", "叫爸爸妈妈过来", "tell daddy I'm done" sends the parent(s) a Telegram message.

This is the one path where something the child did leaves the home, so it is a parent-approved exception to hard
constraint 1, and the program keeps every decision that matters:
- recognition: clear fixed phrases are matched by the program (`detect`); other sentences that name a parent
  (`mentions_parent`) go to the local model, which only answers dad / mom / both / none (`judge_with_model`) and is
  told to say none when unsure. Riddles and stories never reach the judge (the pipeline passes judge_ok=False);
- the pet always asks first with a fixed line ("要我告诉爸爸你在找他吗?") and sends only after a yes, so a wrong
  guess costs one question, never a message;
- the message is fixed by default ("宝宝想找爸爸", time, device); the child's own words are added only when the parent sets
  settings.json "call_parent": {"include_words": true};
- "爸爸" goes to dad's chat only, "妈妈" to mom's only, "爸爸妈妈" / "你们" / "parents" to both;
- at most one message per `min_interval_s` (default 120 s) across all devices;
- every attempt is written to the parent_calls table (text kept 7 days) and shown by pet-log;
- "call_parent": {"enabled": false} turns it off; with no destination configured it is off as well.

settings.json (in the data directory, never in the repo):
    "call_parent": {
        "enabled": true, "include_words": false, "min_interval_s": 120,
        "telegram": {"bot_token": "...", "chat_id": "123", "chat_ids": {"dad": "123", "mom": "456"}}
    }
"chat_ids" routes a request for one parent to that parent's chat; a parent not listed gets "chat_id".
Only sendMessage is ever called on the token: getUpdates or a webhook would break the assistant bot that shares it.
Settings are read on every request, so the parent's switch works without a restart.

Concern push (`notify_concern`, parent's choice 2026-10-24): when the child says something in a serious parent-note
category (concern.SERIOUS: hurting herself or others), the parents get a fixed message with the category, time and
device, never her sentence unless the parent sets "include_words": true. It is its own switch, off unless set:
    "call_parent": {"concern_push": {"enabled": true, "categories": ["harm_self", "harm_others"],
                                     "include_words": false, "parents": "both", "min_interval_s": 600}}
It has its own rate limit (default one per 10 minutes), so it never uses up the child's own call. Every attempt is a
parent_calls row; the sentence itself stays in parent_notes on this machine either way.
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from curiosity_pet import concern, config

log = logging.getLogger("curiosity_pet.call_parent")

DEFAULT_INTERVAL_S = 120
CONFIRM_TIMEOUT_S = 60  # an unanswered "要我告诉爸爸吗?" lapses after this
STATUS_WINDOW_S = 10 * 60  # "你告诉爸爸了吗?" counts a message sent within this as "already told"
# "Did you tell Daddy?" / "你帮我叫妈妈了吗?": answered from what was really sent (the model said "爸爸很快就来")
STATUS_ASK = re.compile(
    r"(?:你|有没有)?(?:帮我)?(?:告诉|叫|喊|找|通知|看|问)(?:了|过)?(?:我的?)?(?:爸爸|妈妈|爸妈|爸爸妈妈)(?:了|没有|了没)?吗?\s*[?？]|"
    r"(?:告诉|叫|喊|通知)(?:了|过)?(?:爸爸|妈妈|爸妈)(?:了)?(?:吗|没有|没)|"
    r"\bdid you (?:tell|call|text|message) (?:my )?(?:dad|daddy|mom|mommy|mum|parents)\b",
    re.IGNORECASE,
)
TEXT_RETENTION_S = 7 * 24 * 3600
MAX_WORDS = 200
SEND_TIMEOUT_S = 8
JUDGE_TIMEOUT_S = 15
TARGETS = ("dad", "mom", "both")

# Chinese words have no word boundaries; English ones do ("mom" is not in "moment")
WORDS = {
    "both": (r"爸爸妈妈|妈妈爸爸|爸妈|爹妈|大人们|大人", r"mommy and daddy|daddy and mommy|mom and dad|dad and mom|mum and dad|"
             r"mama and papa|parents|grown-?ups"),
    "dad": (r"爸爸|爸比|爹地|老爸|爸", r"daddy|dad|papa|father"),
    "mom": (r"妈妈|妈咪|老妈|妈", r"mommy|mummy|mom|mum|mama|mother"),
}


def _words(key: str) -> str:
    # Letters only around English words: \b fails next to Chinese ("叫Daddy来"), which also counts as \w
    zh, en = WORDS[key]
    return rf"{zh}|(?<![a-z])(?:{en})(?![a-z])"


MATCH_ORDER = ("both", "dad", "mom")  # "both" first, so "爸爸妈妈" is one match
PARENT = "|".join(_words(k) for k in MATCH_ORDER)
WHICH = re.compile("|".join(f"(?P<{k}>{_words(k)})" for k in MATCH_ORDER), re.IGNORECASE)
# Pre-filter for the model judge (one call costs about 2 s, measured): a parent word or "你们" ("你们快来"), plus a
# word that a request needs. "我爸爸是医生" or "妈妈说我可以看电视" never reach the model and lose no time.
CUE = re.compile(rf"{PARENT}|你们", re.IGNORECASE)
REQUEST_CUE = re.compile(
    r"找|要|想|哪|来|快|叫|喊|陪|抱|回家|回来|过来|"
    r"(?<![a-z])(?:where|want|need|miss|come|call|get|tell|here|help)",
    re.IGNORECASE,
)
# A name or "小猫," said first ("皮卡丘,叫爸爸来") and polite lead-ins are allowed; the request itself must lead,
# so "为什么爸爸叫爸爸" or "妈妈叫我吃饭" are not requests.
VOCATIVE = r"(?:[^,，。.!！?？\s]{1,8}[,，]\s*)?"
ZH_LEAD = r"(?:请你?|你|帮我|能不能|能|可不可以|可以|快|快点|去|我要|我想)*"
ZH_REQUEST = re.compile(
    rf"^{VOCATIVE}{ZH_LEAD}(?:帮我)?"
    rf"(?:(?:叫|喊|找|告诉|通知|打电话给|发消息给|发信息给)\s*(?:一下|一声|个)?\s*(?:{PARENT})"  # spaces: ASR writes "我想找 daddy"
    rf"|(?:跟|和|给)\s*(?:{PARENT})\s*(?:说|讲|打电话|打个电话|发消息)"
    rf"|让\s*(?:{PARENT})\s*(?:来|过来|回来))"
    rf"(?P<rest>.*)$",
    re.IGNORECASE,
)
EN_REQUEST = re.compile(
    rf"^{VOCATIVE}(?:please\s+|can you\s+|could you\s+|will you\s+|would you\s+|go\s+|i want you to\s+)*"
    rf"(?:call|tell|get|text|message|ask|fetch)\s+(?:my\s+)?(?:{PARENT})(?P<rest>.*)$",
    re.IGNORECASE,
)
AND_PARENT = re.compile(rf"\s*(?:和|跟|还有|与|and\s+(?:my\s+)?|&)\s*(?:{PARENT})", re.IGNORECASE)
PUNCT = re.compile(r"[\s,，。.!！?？~～、]+")

YES_WORDS = (r"要|好的|好啊|好呀|好吧|好嘞|好哒|好|对的|对呀|对|是的|是呀|是|嗯嗯|嗯呢|嗯|可以|行|发吧|快发|发|快点|快|"
             r"叫吧|叫|喊吧|喊|去吧|告诉他们|告诉他|告诉她|yes|yeah|yep|yup|ok|okay|sure|please|do it|uh huh|go")
# Particles a child adds ("要的", "好吧呀"): stripped before matching
TRAILING = re.compile(r"(?:的|啊|呀|吧|嘛|呢|哦|喔|啦|了|哈)+$")
YES = re.compile(rf"^(?:{YES_WORDS})$", re.I)
# Several yes words in a row count too: "好,是。" was not taken as a yes (real case), and the model then pretended to pass
# the message on
YES_RUN = re.compile(rf"^(?:{YES_WORDS})+$", re.I)
# Whole words only: "Now." was taken as "no" (real case)
NO = re.compile(r"^(?:不|不要|不用|不了|算了|别|别发|没事|没有|不告诉|no|nope|no thanks|don'?t|never ?mind|cancel|not now|stop)"
                r"(?:$|[\s,，。.!！]|了|啦|吧)", re.I)
# Short refusals built from 不/别/没 ("不好", "不是", "不要叫", "别叫了", "嗯不要") and English "nah", "not yet": the child
# said no, so the pet should not ask again
NO_SHORT = re.compile(r"^(?:嗯|哦|呃)?(?:不|别|没)(?:要|用|好|是|行|发|叫|喊|找|告诉)*(?:他们|他|她|了|啦|吧|呀)*$|^(?:nah|not yet|no no)$",
                      re.I)

NAMES = {
    "dad": {"zh": "爸爸", "en": "Daddy"}, "mom": {"zh": "妈妈", "en": "Mommy"},
    "both": {"zh": "爸爸妈妈", "en": "Mommy and Daddy"},
}
PARENTS_OF = {"dad": ["dad"], "mom": ["mom"], "both": ["dad", "mom"]}  # whose rate-limit slots a request uses
PRONOUN = {"dad": {"zh": "他", "en": "him"}, "mom": {"zh": "她", "en": "her"}, "both": {"zh": "他们", "en": "them"}}
DEVICES = {"ipad": "iPad", "watch": "手表 watch"}

SAY = {
    "zh": {
        "ask": "要我告诉{who}你在找{him}吗?",
        "ask_again": "我没听清。要我告诉{who}你在找{him}吗?说\"要\"或者\"不要\"。",
        "status_sent": "刚才已经给{who}发过消息了。",
        "status_none": "我还没有给{who}发消息。要我告诉{who}你在找{him}吗?",
        "ask_words": "要我把你的话发给{who}吗?",
        "sent": "好的,我已经告诉{who}了。",
        "declined": "好的,那就不发了。",
        "failed": "哎呀,消息没发出去。你直接去找{who}吧。",
        "limited": "刚才已经给{who}发过一条消息了,过两分钟才能再发。",
        "off": "我现在不能给{who}发消息,你直接去找{him}吧。",
    },
    "en": {
        "ask": "Should I tell {who} you're looking for {him}?",
        "ask_again": "I didn't catch that. Should I tell {who} you're looking for {him}? Say yes or no.",
        "status_sent": "I already sent {who} a message a moment ago.",
        "status_none": "I haven't sent {who} a message yet. Should I tell {who} you're looking for {him}?",
        "ask_words": "Should I send what you said to {who}?",
        "sent": "Okay, I told {who}.",
        "declined": "Okay, I won't send it.",
        "failed": "Oops, the message didn't go through. Please go find {who}.",
        "limited": "I already sent {who} a message a moment ago. I can send another one in a couple of minutes.",
        "off": "I can't send messages to {who} right now. Please go find {him}.",
    },
}

JUDGE_PROMPT = """A 7-year-old child said this to a talking pet program on an iPad:
"{text}"

Does she want the program to get a parent for her right now (call, fetch or tell a parent so the parent comes or
gets a message)? Missing a parent ("我想爸爸了") or asking where a parent is ("爸爸在哪儿") counts as wanting them.
Answer "dad", "mom", "both" (both parents, or parents in general: 爸爸妈妈, 爸妈, 你们, 大人, parents, mom and dad)
or "none".
Answer "none" when she only talks about a parent: a fact about them, what a parent said or allowed, a question about
parents, a story, a game or a riddle with a parent in it, or asks NOT to tell a parent ("不要告诉妈妈").
If you are not sure, answer "none".

Examples: "我想找爸爸" -> dad; "我要妈妈" -> mom; "爸爸妈妈快来" -> both; "你们快来" -> both; "where's daddy" -> dad;
"我爸爸是医生" -> none; "妈妈说我可以看电视" -> none; "Why do daddies have beards?" -> none.

Output JSON only: {{"call": "dad" | "mom" | "both" | "none"}}"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS parent_calls (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    client TEXT NOT NULL,
    parent TEXT NOT NULL,
    status TEXT NOT NULL,
    text TEXT
);
"""
STATUS_NAMES = {
    "sent": "已发送", "partial": "只发出了一部分", "failed": "发送失败", "declined": "孩子说不发",
    "limited": "太频繁,未发", "off": "功能关闭,未发",
    "concern_sent": "担心提醒已发送", "concern_partial": "担心提醒只发出了一部分", "concern_failed": "担心提醒发送失败",
    "concern_limited": "担心提醒太频繁,未发",
}


@dataclass
class Request:
    parent: str  # "dad", "mom" or "both"
    words: str  # the whole utterance, sent only when the parent allows it


def which(span: str) -> str | None:
    """Who a stretch of text names: "both" for 爸爸妈妈 / parents or when dad and mom are both named."""
    found = {k for m in WHICH.finditer(span) for k in TARGETS if m.group(k)}
    if "both" in found or {"dad", "mom"} <= found:
        return "both"
    return next(iter(found), None)


def detect(text: str) -> Request | None:
    """A clear request to call or tell a parent, from fixed phrases only (no model)."""
    t = text.strip()
    m = ZH_REQUEST.match(t) or EN_REQUEST.match(t)
    if not m:
        return None
    # Only the request part counts: in "妈妈,叫爸爸来" the vocative is not a target
    head = t[: m.start("rest")]
    vocative = re.match(VOCATIVE, head)
    head = head[vocative.end():] if vocative else head
    also = AND_PARENT.match(m.group("rest"))  # "叫爸爸和妈妈来", "call daddy and mommy"
    parent = which(head + (also.group(0) if also else ""))
    return Request(parent=parent, words=t) if parent else None


def mentions_parent(text: str) -> bool:
    return bool(CUE.search(text) and REQUEST_CUE.search(text))


def judge_with_model(text: str, lang: str, model: str | None = None, base_url: str | None = None) -> str:
    """Local model only: "dad", "mom", "both" or "none". Any failure or odd answer is "none"."""
    model = model or config.HELPER_MODEL
    base_url = base_url or config.OLLAMA_URL
    from curiosity_pet.llm import LOCAL_HOSTS

    if urlparse(base_url).hostname not in LOCAL_HOSTS:
        return "none"
    # Plain JSON mode, as in lookup.rewrite_with_model (schema-constrained decoding misbehaved with the 9B)
    body = {"model": model, "messages": [{"role": "user", "content": JUDGE_PROMPT.format(text=text[:MAX_WORDS])}],
            "stream": False, "think": False, "format": "json", "options": {"temperature": 0, "num_predict": 16}}
    try:
        r = httpx.post(f"{base_url}/api/chat", json=body, timeout=JUDGE_TIMEOUT_S)
        r.raise_for_status()
        data = json.loads(r.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.warning("call judge failed: %s", type(e).__name__)
        return "none"
    call = data.get("call") if isinstance(data, dict) else None
    return call if call in TARGETS else "none"


def answer_kind(text: str) -> str | None:
    """"yes", "no" or None (something else: the pet drops the question and answers normally)."""
    t = PUNCT.sub(" ", text).strip().lower()
    if NO.match(t):
        return "no"
    if not re.search(r"[?\uff1f]\s*$", text) and (NO_SHORT.match(t) or NO_SHORT.match(t.replace(" ", ""))):
        return "no"
    joined = TRAILING.sub("", t.replace(" ", ""))
    if YES.match(t) or YES_RUN.match(joined) or YES_RUN.match(t.replace(" ", "")):
        return "yes"
    return None


def options(settings: dict | None = None) -> dict:
    settings = config.load_settings(config.SETTINGS_FILE) if settings is None else settings
    opts = settings.get("call_parent")
    return opts if isinstance(opts, dict) else {}


def chat_for(opts: dict, parent: str) -> str | None:
    tg = opts.get("telegram") if isinstance(opts.get("telegram"), dict) else {}
    ids = tg.get("chat_ids") if isinstance(tg.get("chat_ids"), dict) else {}
    chat = ids.get(parent) or tg.get("chat_id")
    return str(chat) if chat and tg.get("bot_token") else None


def chats_for(opts: dict, target: str) -> list[str]:
    """The chats a request goes to, each once ("both" with a single configured chat sends one message)."""
    chats = [chat_for(opts, p) for p in (("dad", "mom") if target == "both" else (target,))]
    return list(dict.fromkeys(c for c in chats if c))


def enabled(opts: dict, target: str) -> bool:
    return opts.get("enabled", True) is not False and bool(chats_for(opts, target))


def message_text(req: Request, client: str, opts: dict, now: float | None = None) -> str:
    """The fixed message; the child's words only when the parent turned include_words on."""
    who = NAMES[req.parent]
    stamp = time.strftime("%H:%M", time.localtime(now or time.time()))
    lines = [
        f"宝宝想找{who['zh']} / Your daughter is asking for {who['en']}",
        f"{stamp} · {DEVICES.get(client, client)}",
    ]
    if opts.get("include_words") is True and req.words:
        lines.append(f"她说 / She said: “{req.words[:MAX_WORDS]}”")
    return "\n".join(lines)


def telegram_send(opts: dict, chat: str, text: str, client: httpx.Client | None = None) -> bool:
    url = f"https://api.telegram.org/bot{opts['telegram']['bot_token']}/sendMessage"
    try:
        c = client or httpx.Client(timeout=SEND_TIMEOUT_S, follow_redirects=False)
        r = c.post(url, json={"chat_id": chat, "text": text})
        return r.status_code == 200 and bool(r.json().get("ok"))
    except (httpx.HTTPError, ValueError) as e:
        # Never log the URL: it holds the token
        log.warning("Telegram send failed: %s", type(e).__name__)
        return False


class CallLog:
    """parent_calls in the pet database: one row per attempt; the text is cleared after 7 days."""

    def __init__(self, db):
        self.db = db
        self.db.executescript(SCHEMA)

    def add(self, client: str, parent: str, status: str, text: str | None, now: float | None = None):
        with self.db:
            self.db.execute(
                "INSERT INTO parent_calls (ts, client, parent, status, text) VALUES (?, ?, ?, ?, ?)",
                (now or time.time(), client, parent, status, text),
            )

    def purge(self, now: float | None = None):
        with self.db:
            self.db.execute(
                "UPDATE parent_calls SET text = NULL WHERE ts < ?", ((now or time.time()) - TEXT_RETENTION_S,)
            )

    def recent(self, days: int = 7, now: float | None = None) -> list[dict]:
        self.purge(now)
        since = (now or time.time()) - days * 24 * 3600
        rows = self.db.execute(
            "SELECT ts, client, parent, status, text FROM parent_calls WHERE ts >= ? ORDER BY ts", (since,)
        ).fetchall()
        return [dict(zip(("ts", "client", "parent", "status", "text"), r)) for r in rows]


def report_lines(db, days: int = 7) -> list[str]:
    """For pet-log: every call attempt with what was sent."""
    lines = []
    for r in CallLog(db).recent(days):
        when = time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))
        status = STATUS_NAMES.get(r["status"], r["status"])
        who = NAMES.get(r["parent"], {}).get("zh", r["parent"])
        lines.append(f"  {when}  {who}  {r['client']}  {status}")
        if r["text"]:
            lines += [f"         {x}" for x in r["text"].splitlines()]
    return lines


class RateLimit:
    """One message per interval per key: each parent has their own (asking for Mommy right after Daddy used to be
    blocked and the pet claimed it had told Mommy). iPad and watch share it."""

    def __init__(self):
        self.lock = threading.Lock()
        self.last: dict = {}

    @property
    def last_sent(self) -> float | None:
        return max(self.last.values()) if self.last else None

    @last_sent.setter
    def last_sent(self, value):
        with self.lock:
            self.last = {} if value is None else {None: value}

    def blocked(self, interval: float, now: float, key=None) -> bool:
        with self.lock:
            t = self.last.get(key)
            return t is not None and now - t < interval

    def take(self, interval: float, now: float, key=None) -> bool:
        with self.lock:
            t = self.last.get(key)
            if t is not None and now - t < interval:
                return False
            self.last[key] = now
            return True

    def give_back(self, now: float, key=None):
        with self.lock:
            if self.last.get(key) == now:
                del self.last[key]  # a failed send does not use up the slot


LIMIT = RateLimit()


class CallParent:
    """Per conversation: holds the pending confirmation. handle() returns the fixed line to speak, or None."""

    def __init__(self, client: str = "ipad", store=None, send=telegram_send, limit: RateLimit = LIMIT,
                 settings=None, clock=time.time, judge=judge_with_model):
        self.client = client
        self.log = CallLog(store.db) if store is not None else None
        self.send = send  # (opts, chat_id, text) -> bool
        self.limit = limit
        self.settings = settings  # callable returning the settings dict (tests); None reads settings.json
        self.clock = clock
        self.judge = judge  # (text, lang) -> "dad" | "mom" | "both" | "none"; None: fixed phrases only
        self.pending: Request | None = None
        self.pending_ts = 0.0
        self.asked_again = False

    def _opts(self) -> dict:
        return options(self.settings() if self.settings else None)

    def _record(self, parent: str, status: str, text: str | None, now: float):
        if self.log is not None:
            try:
                self.log.add(self.client, parent, status, text, now=now)
            except Exception as e:  # noqa: BLE001  a logging failure must not affect the conversation
                log.warning("call log failed: %s", type(e).__name__)

    def _recognize(self, text: str, lang: str, opts: dict, judge_ok: bool) -> Request | None:
        req = detect(text)
        if req is not None:
            return req
        # The model is asked only when the feature is on and a parent is named: off costs no time at all
        if not (judge_ok and self.judge and mentions_parent(text) and opts.get("enabled", True) is not False
                and any(chats_for(opts, t) for t in TARGETS)):
            return None
        try:
            call = self.judge(text, lang)
        except Exception as e:  # noqa: BLE001  a judge failure means "not a request"
            log.warning("call judge failed: %s", type(e).__name__)
            return None
        return Request(parent=call, words=text.strip()) if call in TARGETS else None

    def handle(self, text: str, lang: str, judge_ok: bool = True) -> str | None:
        """judge_ok=False (a riddle or story is going on) keeps the model out: only fixed phrases count."""
        lang = lang if lang in SAY else "zh"
        now = self.clock()
        if self.pending is not None:
            req, self.pending = self.pending, None
            if now - self.pending_ts <= CONFIRM_TIMEOUT_S:
                kind = answer_kind(text)
                again = detect(text)
                if kind == "yes" or (again is not None and again.parent == req.parent):
                    return self._send(req, lang, now)  # saying the request again means yes
                if kind == "no":
                    self._record(req.parent, "declined", None, now)
                    return self._say("declined", req.parent, lang)
                asks_something = re.search(r"[?？]|什么|为什么|怎么|谁|哪|几|多少|吗|\b(?:what|why|how|who|where)\b", text, re.I)
                if not self.asked_again and len(PUNCT.sub("", text)) <= 6 and again is None and not asks_something:
                    # "叫。", "我的。": speech recognition garbles short answers; ask once more instead of
                    # handing it to the model, which then pretended it had called the parent (real case)
                    self.pending, self.pending_ts, self.asked_again = req, now, True
                    return self._say("ask_again", req.parent, lang)
            self.asked_again = False
        status = STATUS_ASK.search(text)
        if status:
            parent = which(status.group(0)) or "dad"
            if any(self.limit.blocked(STATUS_WINDOW_S, now, key=k) for k in PARENTS_OF[parent]):
                return self._say("status_sent", parent, lang)
            self.pending, self.pending_ts, self.asked_again = Request(parent=parent, words=text.strip()), now, False
            return self._say("status_none", parent, lang)
        opts = self._opts()
        req = self._recognize(text, lang, opts, judge_ok)
        if req is None:
            return None
        if not enabled(opts, req.parent):
            self._record(req.parent, "off", None, now)
            return self._say("off", req.parent, lang)
        interval = self._interval(opts)
        if all(self.limit.blocked(interval, now, key=k) for k in PARENTS_OF[req.parent]):
            self._record(req.parent, "limited", None, now)
            return self._say("limited", req.parent, lang)
        self.pending, self.pending_ts, self.asked_again = req, now, False
        return self._say("ask_words" if opts.get("include_words") is True else "ask", req.parent, lang)

    def ask_for(self, parent: str, text: str, lang: str) -> str | None:
        """The router judged (with the conversation's context) that she wants a parent: ask first, as handle() does."""
        lang = lang if lang in SAY else "zh"
        if parent not in TARGETS:
            return None
        now = self.clock()
        opts = self._opts()
        if not enabled(opts, parent):
            self._record(parent, "off", None, now)
            return self._say("off", parent, lang)
        if all(self.limit.blocked(self._interval(opts), now, key=k) for k in PARENTS_OF[parent]):
            self._record(parent, "limited", None, now)
            return self._say("limited", parent, lang)
        self.pending, self.pending_ts, self.asked_again = Request(parent=parent, words=text.strip()), now, False
        return self._say("ask_words" if opts.get("include_words") is True else "ask", parent, lang)

    def confirm(self, kind: str, lang: str) -> str | None:
        """The router judged her reply to "要我告诉爸爸吗?" as yes or no."""
        lang = lang if lang in SAY else "zh"
        if self.pending is None or kind not in ("yes", "no"):
            return None
        req, self.pending = self.pending, None
        now = self.clock()
        if kind == "yes":
            return self._send(req, lang, now)
        self._record(req.parent, "declined", None, now)
        return self._say("declined", req.parent, lang)

    def _send(self, req: Request, lang: str, now: float) -> str:
        opts = self._opts()  # read again: the parent may have switched it off in between
        if not enabled(opts, req.parent):
            self._record(req.parent, "off", None, now)
            return self._say("off", req.parent, lang)
        interval = self._interval(opts)
        free = [k for k in PARENTS_OF[req.parent] if self.limit.take(interval, now, key=k)]
        if not free:
            self._record(req.parent, "limited", None, now)
            return self._say("limited", req.parent, lang)
        text = message_text(req, self.client, opts, now)
        # Each chat once ("both" with a single configured chat sends one message)
        chat_of = {k: chat_for(opts, k) for k in free}
        ok_chats = {c for c in dict.fromkeys(c for c in chat_of.values() if c) if self.send(opts, c, text)}
        sent_to = [k for k in free if chat_of[k] in ok_chats]
        for k in free:
            if k not in sent_to:
                self.limit.give_back(now, key=k)
        if not sent_to:
            self._record(req.parent, "failed", text, now)
            return self._say("failed", req.parent, lang)
        if req.parent == "both" and len(sent_to) < 2:
            got = sent_to[0]
            self._record(req.parent, "partial", text, now)
            return self._say("sent", got, lang)
        self._record(req.parent, "sent", text, now)
        return self._say("sent", req.parent, lang)

    @staticmethod
    def _interval(opts: dict) -> float:
        try:
            return max(0.0, float(opts.get("min_interval_s", DEFAULT_INTERVAL_S)))
        except (TypeError, ValueError):
            return DEFAULT_INTERVAL_S

    @staticmethod
    def _say(key: str, parent: str, lang: str) -> str:
        return SAY[lang][key].format(who=NAMES[parent][lang], him=PRONOUN[parent][lang])

    def reset(self):
        self.pending = None
        self.asked_again = False


# ---------- concern push (parent notes to Telegram, serious categories only) ----------

CONCERN_INTERVAL_S = 600
CONCERN_NAMES_EN = {
    "harm_self": "talked about hurting herself", "harm_others": "talked about hurting others",
    "bullied": "talked about being bullied", "family_conflict": "talked about a conflict at home",
    "scared": "talked about being scared", "sad": "talked about being sad", "angry": "talked about being angry",
    "unwell": "talked about feeling unwell",
}
CONCERN_LIMIT = RateLimit()  # separate from LIMIT: a push never uses up the child's own call


def concern_options(opts: dict) -> dict:
    push = opts.get("concern_push")
    return push if isinstance(push, dict) else {}


def concern_message(categories: list[str], words: str, client: str, push: dict, now: float | None = None) -> str:
    """Facts only: the category names, time and device; her sentence only when the parent turned include_words on."""
    stamp = time.strftime("%H:%M", time.localtime(now or time.time()))
    zh = "、".join(concern.NAMES[c].removeprefix("说到") for c in categories)  # "说到伤害自己、伤害别人"
    en = ", ".join(CONCERN_NAMES_EN[c] for c in categories)
    lines = [f"宝宝说到{zh} / Your daughter {en}", f"{stamp} · {DEVICES.get(client, client)}"]
    if push.get("include_words") is True and words:
        lines.append(f"她说 / She said: “{words[:MAX_WORDS]}”")
    return "\n".join(lines)


def notify_concern(categories: list[str], words: str, client: str = "ipad", store=None, send=telegram_send,
                   limit: RateLimit = CONCERN_LIMIT, settings: dict | None = None,
                   now: float | None = None) -> str | None:
    """Push a parent note in a chosen category to the parents' Telegram. Returns the parent_calls status, or None
    when nothing applies (switch off, no chosen category, nowhere to send). Blocks for up to SEND_TIMEOUT_S per chat,
    so the pipeline calls it off the answer path (a thread)."""
    opts = options(settings)
    push = concern_options(opts)
    if push.get("enabled") is not True:
        return None
    chosen = push.get("categories", concern.SERIOUS)
    chosen = chosen if isinstance(chosen, list) else list(concern.SERIOUS)
    found = [c for c in categories if c in chosen and c in CONCERN_NAMES_EN]
    target = push.get("parents", "both")
    target = target if target in TARGETS else "both"
    chats = chats_for(opts, target)
    if not found or not chats:
        return None
    now = now or time.time()
    try:
        interval = max(0.0, float(push.get("min_interval_s", CONCERN_INTERVAL_S)))
    except (TypeError, ValueError):
        interval = CONCERN_INTERVAL_S
    text = concern_message(found, words, client, push, now)
    if not limit.take(interval, now):
        status = "concern_limited"
    else:
        sent = [chat for chat in chats if send(opts, chat, text)]
        if not sent:
            limit.give_back(now)
        status = "concern_failed" if not sent else "concern_partial" if len(sent) < len(chats) else "concern_sent"
    if store is not None:
        try:
            CallLog(store.db).add(client, target, status, text, now=now)
        except Exception as e:  # noqa: BLE001  a logging failure must not affect the conversation
            log.warning("concern push log failed: %s", type(e).__name__)
    return status
