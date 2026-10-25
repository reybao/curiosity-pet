"""Riddles ("脑筋急转弯") in natural conversation, run by the program, not improvised by the model.

The parent's complaint: the model repeated the same riddle and gave the answer away at once.
Here the riddle comes from a local bank (data/riddles.json), used ones are remembered in the database so
they do not repeat until the bank is exhausted, and the answer is withheld: the child's next message is
judged (exact match, accepted alternatives, then the local model for near misses), a wrong answer gets
one hint, the second wrong answer or "I don't know" reveals it. If the child asks something else instead,
the riddle is dropped and the question is answered normally.

The other direction matters too: in real use the child said "我能不能给你问一个Riddle?" and "Could you answer my
riddle? I am not a human being, so who am I?", and the pet answered each time with a riddle of its own. When the
child poses a riddle (child_poses), the pet says "go ahead" if the riddle has not come yet, then guesses it with the
model; it never answers a child's riddle with a new one.

Many children's riddles are classics, so the pet first looks the child's riddle up in its own bank (recognize):
"What has hands but cannot grab things?" is the bank's "What has hands but cannot clap?", and the pet answers
"a clock" instead of guessing. A message in an unmistakable riddle form ("What has ... but ...?", "打一个字",
"什么东西越...越...") counts as the child posing a riddle even without "I have a riddle for you" (looks_like_riddle).
"""

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from curiosity_pet.followup import looks_like_new_question

BANK_PATH = Path(__file__).parent / "data" / "riddles.json"

WANT = re.compile(
    r"脑筋急转弯|猜谜|谜语|出个谜|出一个谜|出题考我|考考我|猜猜看|猜一猜|(?<![a-z])riddles?(?![a-z])|brain ?teasers?|guessing game",
    re.IGNORECASE,
)
RIDDLE_WORD = r"(?:谜语|脑筋急转弯|谜题|谜|题|riddles?)"
# The child poses a riddle to the pet (checked before WANT, which also matches the word "riddle")
CHILD_POSES = re.compile(
    rf"我(?:来|要|想|能不能|可以|可不可以|也)?(?:给你|跟你|向你|问你|考你|对你)(?:出|问|说|讲|猜)?(?:一个|个|一道|道)?{RIDDLE_WORD}"
    rf"|我(?:来|要|想|也)?(?:出|问|说|讲)(?:一个|个|一道|道){RIDDLE_WORD}(?:给你|让你猜|你猜)"
    rf"|我(?:来)?考考你|我考你|你(?:来)?猜猜我是谁|猜猜我是谁|你(?:能|会|可以|能不能)?(?:回答|答|猜)(?:出)?(?:一下)?我的(?:这个)?{RIDDLE_WORD}"
    r"|my riddle|i (?:have|got|'ve got) a riddle|riddle for you|answer my riddle|guess my riddle"
    r"|(?:can|could|may) i (?:ask|tell|give) you a riddle|let me (?:ask|tell|give) you a riddle"
    r"|i(?:'ll| will| want to) (?:ask|tell|give) you a riddle|guess (?:what|who) i am",
    re.IGNORECASE,
)
# Unmistakable riddle forms, so a riddle told without "I have a riddle" is still recognized as one.
# Plain questions such as "什么东西会飞?" or "What has stripes?" do not match.
RIDDLE_FORM = re.compile(
    r"打一(?:个)?(?:字|物|动物|水果|植物|东西|用品|身体部位)|什么东西.{0,12}越.{0,6}越|什么东西.{1,14}(?:却|但是|可是)|"
    r"(?:我|它)是(?:什么|谁)[?？]?$|猜猜我是(?:什么|谁)|"
    r"^(?:what|which)\s+(?:has|have|can|goes|gets|is|comes|runs|flies|falls|kind of)\b[^?]{2,80}\b(?:but|yet)\b|"
    r"\bwhat am i\b|\bwho am i\b",
    re.IGNORECASE,
)
STOP_EN = {"what", "which", "who", "a", "an", "the", "is", "are", "it", "its", "but", "and", "or", "of", "to", "in", "on",
           "you", "your", "i", "me", "my", "am", "do", "does", "can", "has", "have", "that", "this", "with", "riddle"}
# Riddle boilerplate that almost every Chinese riddle shares; removed before comparing riddles
ZH_BOILER = re.compile(r"什么东西|什么|打一个?(?:字|物|动物|水果|植物|东西|用品|身体部位)|是谁|我考考你|考考你|你猜|猜一猜|猜猜")
QUESTION_HINT = re.compile(r"[?？]|什么|谁|哪|为什么|怎么|几|(?<![a-z])(?:what|who|which|where|why|how|when)(?![a-z])", re.IGNORECASE)
# "Another one" only as a short request: "I have another question" is not a request for another riddle (real case)
ANOTHER = re.compile(r"再来一个|再出一个|再来一题|再来|还有吗|another one|another riddle|one more|next one", re.IGNORECASE)
# "I didn't ask you a riddle" / "我没跟你说谜语" mention riddles without wanting one (real cases)
NEGATED = re.compile(
    r"(?:didn'?t|did not|don'?t|do not|not|never|no)\W+(?:[a-z']+\W+){0,4}(?:riddles?|brain ?teasers?)|"
    r"(?:没有|没|不是|不要|别|不想|并没有).{0,8}(?:谜语|脑筋急转弯|猜谜)",
    re.IGNORECASE,
)


# A reply to the pet's guess ("对了", "不对", "答案是…", "Yes!", "Nope, it's a cat")
REPLY_WORDS = re.compile(r"对|错|不是|答案|谜底|猜中|yes|yeah|no\b|nope|right|wrong|correct|answer|it'?s", re.IGNORECASE)


def word_count(text: str) -> int:
    """Chinese characters count as words, so "long" means the same in both languages."""
    return len(re.findall(r"[\u4e00-\u9fff]", text)) // 2 + len(re.findall(r"[a-z']+", text, re.IGNORECASE))


def is_long(text: str, limit: int = 14) -> bool:
    return word_count(text) > limit
GIVE_UP = re.compile(
    r"不知道|猜不到|猜不出|想不出|告诉我|答案是什么|是什么呀|说答案|不猜了|"
    r"i don'?t know|no idea|give up|tell me|what is it|what'?s the answer",
    re.IGNORECASE,
)

TEXT = {
    "zh": {
        "intro": "来一个脑筋急转弯:{q}",
        "correct": "答对了,就是{a}!",
        "hint": "还不对哦。提示:{hint}再想想。",
        "reveal": "答案是{a}。",
        "reveal_after": "没关系,答案是{a}。",
        "empty": "我准备的谜语都猜完啦,下次再给你新的。",
        "ready": "好呀,你出吧,我来猜!",
        "known": "这个我知道!是{a}!我猜对了吗?",
    },
    "en": {
        "intro": "Here is a riddle: {q}",
        "correct": "You got it, {a}!",
        "hint": "Not yet. Hint: {hint} Try again.",
        "reveal": "The answer is {a}.",
        "reveal_after": "That's okay, the answer is {a}.",
        "empty": "You have solved all my riddles, I will bring new ones next time.",
        "ready": "Okay, tell me your riddle, and I'll guess!",
        "known": "I know this one! Is it {a}? Am I right?",
    },
}


@dataclass
class Riddle:
    id: str
    q: str
    a: str
    accept: list
    hint: str
    lang: str


@dataclass
class Outcome:
    text: str
    resolved: bool  # the riddle is finished (correct, revealed, or dropped)
    correct: bool = False
    dropped: bool = False  # the child changed the subject; answer their message normally


def load_bank(path: Path = BANK_PATH) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"zh": [], "en": []}
    return {
        lang: [Riddle(r["id"], r["q"], r["a"], [str(x).lower() for x in r.get("accept", [])], r.get("hint", ""), lang) for r in data.get(lang, [])]
        for lang in ("zh", "en")
    }


PREFIX = re.compile(r"^(是不是|是|应该是|我猜是|我觉得是|答案是|it'?s|is it|i think it'?s|the answer is|maybe|a |an |the )\s*")


def normalize(text: str) -> str:
    """Lowercase, drop lead-ins like "is it", "it's a", "是不是", and all punctuation and spaces."""
    text = text.lower().strip()
    while True:
        stripped = PREFIX.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    return re.sub(r"[\s。.!！?？,，、~～]+", "", text)


def wants_riddle(text: str) -> bool:
    return bool(WANT.search(text)) and not child_poses(text) and not NEGATED.search(text)


def child_poses(text: str) -> bool:
    return bool(CHILD_POSES.search(text)) and not NEGATED.search(text)


def has_riddle_content(text: str) -> bool:
    """Whether the riddle itself is in the message, not only "I have a riddle for you"."""
    rest = CHILD_POSES.sub("", text)
    # At least a few words beyond the announcement ("My riddle is: What." is a cut-off sentence, not a riddle)
    enough = len(re.findall(r"[\u4e00-\u9fff]", rest)) >= 4 or len(re.findall(r"[a-z']+", rest, re.IGNORECASE)) >= 3
    return enough and (bool(QUESTION_HINT.search(rest)) or bool(RIDDLE_FORM.search(rest)))  # "打一个字" has no question word


def looks_like_riddle(text: str) -> bool:
    return bool(RIDDLE_FORM.search(text.strip()))


def _bigrams(text: str) -> set:
    han = re.sub(r"[^\u4e00-\u9fff]", "", ZH_BOILER.sub("", text))
    return {han[i : i + 2] for i in range(len(han) - 1)}


def _words(text: str) -> set:
    return {w.rstrip("s") for w in re.findall(r"[a-z']+", text.lower()) if w not in STOP_EN and len(w) > 1}


def riddle_similarity(child: str, bank_q: str, lang: str) -> float:
    """Share of the bank riddle's content (Chinese character pairs, English content words) found in the child's words."""
    a, b = (_bigrams(child), _bigrams(bank_q)) if lang == "zh" else (_words(child), _words(bank_q))
    if not b or len(a & b) < 2:
        return 0.0
    return len(a & b) / len(b)


def wants_another(text: str) -> bool:
    return bool(ANOTHER.search(text)) and word_count(text) <= 6 and not NEGATED.search(text)


def could_be_told_riddle(text: str) -> bool:
    """Whether a message without any announcement may be a riddle from the bank: it asks something and is not a long
    statement. A parent's long remark about pictures matched "What has an eye but cannot see?" on two words."""
    return bool(QUESTION_HINT.search(text)) and not is_long(text, 25)


class RiddleGame:
    def __init__(self, bank: dict | None = None, store=None, judge=None, rng=None):
        self.bank = bank if bank is not None else load_bank()
        self.store = store  # remembers used riddles across sessions
        self.judge = judge  # (riddle, child_answer) -> bool, for near misses; None means exact matching only
        self.rng = rng or random.Random()
        self.pending: Riddle | None = None
        self.misses = 0
        self.last: Riddle | None = None  # set after a riddle, so "another one" makes sense
        self.used_here: set = set()  # riddles given in this process, even without a database
        # The child's own riddle: "waiting" for it to be told, "guessing" while the pet guesses and hears
        # whether it was right (a few turns at most), None otherwise
        self.child_stage: str | None = None
        self.child_turns = 0

    def reset(self):
        self.pending = None
        self.misses = 0
        self.last = None
        self.child_stage = None
        self.child_turns = 0

    def recognize(self, text: str, lang: str, threshold: float = 0.6) -> "Riddle | None":
        """The bank riddle the child is telling, if it is one of the classics the pet knows."""
        told = CHILD_POSES.sub("", text)
        best, best_key = None, (0.0, 0.0)
        for r in self.bank.get(lang, []):
            score = riddle_similarity(told, r.q, lang)
            if score < threshold:
                continue
            # Ties ("an eye" vs "lots of eyes") go to the riddle whose wording is closest overall
            a, b = (_bigrams(told), _bigrams(r.q)) if lang == "zh" else (_words(told), _words(r.q))
            key_ = (score, len(a & b) / len(a | b))
            if key_ > best_key:
                best, best_key = r, key_
        return best

    def _used(self) -> set:
        return (set(self.store.used_riddles()) if self.store else set()) | self.used_here

    def next(self, lang: str) -> str:
        """Pick an unused riddle, remember it, and return the sentence to speak."""
        pool = self.bank.get(lang, [])
        used = self._used()
        unused = [r for r in pool if r.id not in used]
        if not unused and pool:
            if self.store:
                self.store.reset_riddles(lang)  # all solved: start over
            self.used_here = {i for i in self.used_here if not i.startswith(f"{lang}-")}
            unused = pool
        if not unused:
            self.pending = None
            return TEXT[lang]["empty"]
        r = self.rng.choice(unused)
        self.used_here.add(r.id)
        if self.store:
            self.store.mark_riddle(r.id)
        self.pending = r
        self.last = r
        self.misses = 0
        return TEXT[lang]["intro"].format(q=r.q)

    def answer(self, text: str) -> Outcome:
        """Judge the child's message against the pending riddle."""
        r = self.pending
        t = TEXT[r.lang]
        if self._matches(r, text) or (self.judge is not None and self._ask_judge(r, text)):
            self.pending = None
            return Outcome(t["correct"].format(a=r.a), resolved=True, correct=True)
        if GIVE_UP.search(text):
            self.pending = None
            return Outcome(t["reveal_after"].format(a=r.a), resolved=True)
        if looks_like_new_question(text) or is_long(text) or NEGATED.search(text):
            # A new question, or a long remark about something else (a parent's comment was taken as a wrong
            # answer and the riddle was given away): drop the riddle and answer normally
            self.pending = None
            return Outcome("", resolved=True, dropped=True)
        self.misses += 1
        if self.misses >= 2:
            self.pending = None
            return Outcome(t["reveal"].format(a=r.a), resolved=True)
        return Outcome(t["hint"].format(hint=r.hint), resolved=False)

    def _matches(self, r: Riddle, text: str) -> bool:
        guess = normalize(text)
        if not guess:
            return False
        for cand in [r.a.lower(), *r.accept]:
            c = normalize(cand)
            if c and (guess == c or c in guess or (len(c) >= 3 and guess in c)):
                return True
        return False

    def _ask_judge(self, r: Riddle, text: str) -> bool:
        try:
            return bool(self.judge(r, text))
        except Exception:  # noqa: BLE001  judging must never break the conversation
            return False


def judge_with_model(riddle: Riddle, child_answer: str) -> bool:
    """Ask the local model whether the child's answer means the same thing; strict JSON, temperature 0."""
    import httpx

    from curiosity_pet import config
    from curiosity_pet.llm import LOCAL_HOSTS
    from urllib.parse import urlparse

    if urlparse(config.OLLAMA_URL).hostname not in LOCAL_HOSTS:
        return False
    prompt = (
        f"Riddle: {riddle.q}\nCorrect answer: {riddle.a}\nChild's answer: {child_answer}\n"
        "Does the child's answer mean the same thing as the correct answer? Output JSON only."
    )
    body = {
        "model": config.HELPER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": {"type": "object", "properties": {"same": {"type": "boolean"}}, "required": ["same"]},
        "options": {"temperature": 0},
    }
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=20)
    r.raise_for_status()
    return bool(json.loads(r.json()["message"]["content"]).get("same"))
