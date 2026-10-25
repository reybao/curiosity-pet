"""Usage log: record the **facts** of each exploration and question in the local database, for parents to review later.

Only countable facts are recorded: what was asked, in which language, on what topic, whether it was a follow-up, whether material was looked up, timing, and how it ended.
No evaluation is recorded (hard constraint 3). Answer text is deleted after 7 days by Store.purge; question text and statistics are kept long term (constraint 2).
"""

import logging
import re
import time

log = logging.getLogger("curiosity_pet.usage")

# Follow-up types: used only for "interaction habit" statistics, so rough keyword matching is enough
FOLLOW_UP_PATTERNS = {
    "simpler": re.compile(r"再简单|简单一点|简单点|听不懂|不明白|没听懂|什么意思|simpl|easier|don'?t understand", re.I),
    "example": re.compile(r"举个例子|举例|比如说|\bexample\b", re.I),
    "how_know": re.compile(r"你怎么知道|怎么知道的|真的吗|是真的吗|确定吗|how do you know|are you sure|\breally\?", re.I),
    "correction": re.compile(r"你说错|说错了|不对吧|不是这样|错了|that'?s wrong|you'?re wrong|not right|incorrect", re.I),
    "more": re.compile(r"再讲|多讲|再说一点|还有呢|继续讲|tell me more|what else|\bmore\b", re.I),
}


def classify_follow_up(text: str) -> str | None:
    for kind, pat in FOLLOW_UP_PATTERNS.items():
        if pat.search(text):
            return kind
    return None



def spoken_text(turn) -> str:
    """What the pet actually said (after the program removed questions, disclaimers and extra catchphrases), not the
    model's raw output; before, the parent log showed sentences the child never heard."""
    sentences = getattr(turn, "sentences", None) or []
    if not sentences:
        return ""  # nothing was said (everything was filtered); never log the raw model text as if it were spoken
    joiner = "" if turn.lang == "zh" else " "
    return joiner.join(sentences)


class UsageLog:
    """One client connection maps to one UsageLog; the first record automatically starts an exploration."""

    def __init__(self, store, tag_topic=None, client: str = "ipad"):
        self.store = store
        self.tag_topic = tag_topic  # (question, lang) -> topic, local model, returns None on failure
        self.client = client
        self.session_id: int | None = None
        self.last_topic: str | None = None

    def begin(self, now=None):
        if self.session_id is None:
            self.session_id = self.store.start_session(self.client, now=now)
        return self.session_id

    def record(self, turn, now=None):
        if not turn.question:
            return
        # Keep the id: pressing stop can end the session on another thread while this turn is being recorded
        # (that raised "NOT NULL constraint failed: turns.session_id")
        session_id = self.begin(now=now)
        follow_up = classify_follow_up(turn.question)
        topic = turn.topic
        if follow_up and topic in (None, "other", "chat") and self.last_topic:
            topic = self.last_topic  # a follow-up like "simpler please" reuses the previous question's topic
        if not topic and self.tag_topic and not turn.unavailable:
            try:
                topic = self.tag_topic(turn.question, turn.lang)
            except Exception as e:  # noqa: BLE001  a logging failure must not affect the conversation
                log.warning("Topic tagging failed: %s", type(e).__name__)
                topic = None
        self.store.record_turn(
            session_id,
            lang=turn.lang,
            question=turn.question,
            answer=spoken_text(turn),
            topic=topic or "other",
            follow_up=follow_up,
            looked_up=turn.looked_up,
            source=turn.source,
            asr_s=turn.asr_s,
            first_audio_s=turn.first_audio_s,
            total_s=turn.total_s,
            unavailable=turn.unavailable,
            now=now,
        )
        self.last_topic = topic or "other"

    def unanswered(self, question: str, lang: str, topic: str | None, now=None):
        """A question about specific things that no material could back: listed for the parent to add to the library."""
        try:
            self.store.record_unanswered(question, lang, topic or "other", now=now)
        except Exception as e:  # noqa: BLE001
            log.warning("unanswered log failed: %s", type(e).__name__)

    def note(self, said: str, lang: str, categories: list[str], now=None):
        """Something the child said that the parent may want to know about (concern.py); facts only."""
        try:
            self.store.add_note(lang, categories, said, now=now)
        except Exception as e:  # noqa: BLE001
            log.warning("parent note failed: %s", type(e).__name__)

    def end(self, reason: str, now=None):
        if self.session_id is not None:
            self.store.end_session(self.session_id, reason, now=now or time.time())
            self.session_id = None
        self.last_topic = None
