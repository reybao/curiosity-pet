"""Local SQLite storage (PET_DATA_DIR/pet.db).

- sessions / turns:factual records of each exploration and each question (written by usage.py). Answer text is deleted after 7 days; question text is kept;
- topic_week:question counts per week and topic, kept long term; the weekly report uses only this for factual trends;
- lookup_log:Wikipedia search terms that were sent (the rewritten topic terms, not the child's words), kept for 7 days;
- kb_pending:material fetched from Wikipedia, marked pending review; after parent review it enters the knowledge base (stage 4).
"""

import sqlite3
import statistics
import time
from pathlib import Path

from curiosity_pet import config

LOG_RETENTION_S = 7 * 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    start_ts REAL NOT NULL,
    end_ts REAL,
    turns INTEGER NOT NULL DEFAULT 0,
    end_reason TEXT,
    client TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    lang TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    topic TEXT NOT NULL,
    follow_up TEXT,
    looked_up INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    kb_hit INTEGER NOT NULL DEFAULT 0,
    asr_s REAL,
    first_audio_s REAL,
    total_s REAL,
    unavailable INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS riddles_used (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS unanswered (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    lang TEXT NOT NULL,
    question TEXT NOT NULL,
    topic TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lookup_log (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    lang TEXT NOT NULL,
    query TEXT NOT NULL,
    topic TEXT NOT NULL,
    title TEXT,
    found INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS topic_week (
    week TEXT NOT NULL,
    topic TEXT NOT NULL,
    n INTEGER NOT NULL,
    PRIMARY KEY (week, topic)
);
CREATE TABLE IF NOT EXISTS interests (
    topic TEXT PRIMARY KEY,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS discoveries (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    lang TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parent_notes (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    lang TEXT NOT NULL,
    categories TEXT NOT NULL,
    said TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kb_pending (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    lang TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (url)
);
"""

TURN_FIELDS = (
    "ts", "lang", "question", "answer", "topic", "follow_up", "looked_up", "source",
    "kb_hit", "asr_s", "first_audio_s", "total_s", "unavailable",
)


STALE_SESSION_S = 30 * 60  # an exploration with no activity this long is over


def week_of(ts: float) -> str:
    return time.strftime("%G-W%V", time.localtime(ts))


class Store:
    def __init__(self, path: Path | str | None = None):
        path = Path(path) if path else config.DATA_DIR / "pet.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    # ---------- explorations and questions ----------

    def close_stale_sessions(self, idle_s: float = STALE_SESSION_S, now=None) -> int:
        """End explorations left open with no activity for idle_s (the watch client never ended its sessions, so one
        stayed "open" for hours and "nobody is using it" could never be true). The end time is the last activity."""
        now = now or time.time()
        rows = self.db.execute(
            "SELECT s.id, COALESCE(MAX(t.ts), s.start_ts) FROM sessions s LEFT JOIN turns t ON t.session_id = s.id "
            "WHERE s.end_ts IS NULL GROUP BY s.id"
        ).fetchall()
        stale = [(last, sid) for sid, last in rows if now - last > idle_s]
        with self.db:
            self.db.executemany("UPDATE sessions SET end_ts = ?, end_reason = 'stale' WHERE id = ? AND end_ts IS NULL", stale)
        return len(stale)

    def open_sessions(self) -> list[int]:
        return [i for (i,) in self.db.execute("SELECT id FROM sessions WHERE end_ts IS NULL")]

    def start_session(self, client: str, now=None) -> int:
        self.close_stale_sessions(now=now)
        with self.db:
            cur = self.db.execute(
                "INSERT INTO sessions (start_ts, client) VALUES (?, ?)", (now or time.time(), client)
            )
        return cur.lastrowid

    def end_session(self, session_id: int, reason: str, now=None):
        with self.db:
            self.db.execute(
                "UPDATE sessions SET end_ts = ?, end_reason = ? WHERE id = ? AND end_ts IS NULL",
                (now or time.time(), reason, session_id),
            )

    def record_turn(
        self, session_id: int, *, lang, question, answer, topic, follow_up=None, looked_up=False,
        source=None, kb_hit=False, asr_s=None, first_audio_s=None, total_s=None, unavailable=False,
        now=None,
    ):
        now = now or time.time()
        with self.db:
            self.db.execute(
                "INSERT INTO turns (session_id, ts, lang, question, answer, topic, follow_up, looked_up, "
                "source, kb_hit, asr_s, first_audio_s, total_s, unavailable) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, now, lang, question, answer, topic, follow_up, int(looked_up), source,
                 int(kb_hit), asr_s, first_audio_s, total_s, int(unavailable)),
            )
            self.db.execute("UPDATE sessions SET turns = turns + 1 WHERE id = ?", (session_id,))
            self.db.execute(
                "INSERT INTO topic_week (week, topic, n) VALUES (?, ?, 1) "
                "ON CONFLICT (week, topic) DO UPDATE SET n = n + 1",
                (week_of(now), topic),
            )
        self.purge(now)

    def recent_sessions(self, days: int = 7, now=None) -> list[dict]:
        """Explorations from the last few days, each with its list of questions (chronological order)."""
        now = now or time.time()
        cutoff = now - days * 24 * 3600
        sessions = [
            dict(zip(("id", "start_ts", "end_ts", "turns", "end_reason", "client"), row))
            for row in self.db.execute(
                "SELECT id, start_ts, end_ts, turns, end_reason, client FROM sessions "
                "WHERE start_ts >= ? ORDER BY start_ts",
                (cutoff,),
            )
        ]
        for s in sessions:
            s["turn_list"] = [
                dict(zip(TURN_FIELDS, row))
                for row in self.db.execute(
                    f"SELECT {', '.join(TURN_FIELDS)} FROM turns WHERE session_id = ? ORDER BY ts", (s["id"],)
                )
            ]
        return sessions

    def stats(self, days: int = 7, now=None) -> dict:
        """Only counts and medians, no evaluative fields."""
        sessions = self.recent_sessions(days, now)
        turns = [t for s in sessions for t in s["turn_list"]]

        def count(key):
            out = {}
            for t in turns:
                v = t[key]
                if v:
                    out[v] = out.get(v, 0) + 1
            return out

        durations = [s["end_ts"] - s["start_ts"] for s in sessions if s["end_ts"]]
        first_audio = [t["first_audio_s"] for t in turns if t["first_audio_s"] is not None]
        by_day = {}
        for t in turns:
            d = time.strftime("%Y-%m-%d", time.localtime(t["ts"]))
            by_day[d] = by_day.get(d, 0) + 1
        return {
            "days": days,
            "sessions": len(sessions),
            "questions": len(turns),
            "by_day": by_day,
            "by_lang": count("lang"),
            "by_topic": count("topic"),
            "follow_ups": count("follow_up"),
            "looked_up": sum(t["looked_up"] for t in turns),
            "unavailable": sum(t["unavailable"] for t in turns),
            "end_reasons": {k: v for k, v in count_dict(sessions, "end_reason").items()},
            "median_session_s": statistics.median(durations) if durations else None,
            "median_first_audio_s": statistics.median(first_audio) if first_audio else None,
        }

    # ---------- web lookup ----------

    # ---------- riddles ----------

    def used_riddles(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT id FROM riddles_used")]

    def mark_riddle(self, riddle_id: str, now=None):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO riddles_used (id, ts) VALUES (?, ?)", (riddle_id, now or time.time()))

    def reset_riddles(self, lang: str):
        with self.db:
            self.db.execute("DELETE FROM riddles_used WHERE id LIKE ?", (f"{lang}-%",))

    def record_unanswered(self, question: str, lang: str, topic: str, now=None):
        with self.db:
            self.db.execute(
                "INSERT INTO unanswered (ts, lang, question, topic) VALUES (?, ?, ?, ?)",
                (now or time.time(), lang, question, topic),
            )

    def unanswered(self, days: int = 30, now=None) -> list[dict]:
        cutoff = (now or time.time()) - days * 24 * 3600
        cur = self.db.execute(
            "SELECT ts, lang, question, topic FROM unanswered WHERE ts >= ? ORDER BY ts DESC", (cutoff,)
        )
        return [dict(zip(("ts", "lang", "question", "topic"), row)) for row in cur]

    def record_lookup(self, lang, query, topic, title=None, found=False, now=None):
        now = now or time.time()
        with self.db:
            self.db.execute(
                "INSERT INTO lookup_log (ts, lang, query, topic, title, found) VALUES (?, ?, ?, ?, ?, ?)",
                (now, lang, query, topic, title, int(found)),
            )
        self.purge(now)

    def save_pending(self, lang, title, url, text, now=None):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO kb_pending (ts, lang, title, url, text) VALUES (?, ?, ?, ?, ?)",
                (now or time.time(), lang, title, url, text),
            )

    def recent_lookups(self):
        cur = self.db.execute("SELECT ts, lang, query, topic, title, found FROM lookup_log ORDER BY ts DESC")
        keys = ("ts", "lang", "query", "topic", "title", "found")
        return [dict(zip(keys, row)) for row in cur]

    def topic_counts(self, week=None):
        cur = self.db.execute(
            "SELECT week, topic, n FROM topic_week" + (" WHERE week = ?" if week else "") + " ORDER BY week, topic",
            (week,) if week else (),
        )
        return [{"week": w, "topic": t, "n": n} for w, t, n in cur]

    # ---------- what the child chose to keep (memory.py) ----------

    def add_interest(self, topic: str, now=None):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO interests (topic, ts) VALUES (?, ?)", (topic, now or time.time()))

    def remove_interest(self, topic: str):
        with self.db:
            self.db.execute("DELETE FROM interests WHERE topic = ?", (topic,))

    def interests(self) -> list[str]:
        return [t for (t,) in self.db.execute("SELECT topic FROM interests ORDER BY ts")]

    def add_discovery(self, lang: str, question: str, answer: str, now=None) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO discoveries (ts, lang, question, answer) VALUES (?, ?, ?, ?)",
                (now or time.time(), lang, question, answer),
            )
        return cur.lastrowid

    def discoveries(self) -> list[dict]:
        cur = self.db.execute("SELECT id, ts, lang, question, answer FROM discoveries ORDER BY ts DESC")
        return [dict(zip(("id", "ts", "lang", "question", "answer"), row)) for row in cur]

    def delete_discovery(self, discovery_id: int):
        with self.db:
            self.db.execute("DELETE FROM discoveries WHERE id = ?", (discovery_id,))

    # ---------- things the parent may want to know (concern.py) ----------

    def add_note(self, lang: str, categories: list[str], said: str, now=None):
        with self.db:
            self.db.execute(
                "INSERT INTO parent_notes (ts, lang, categories, said) VALUES (?, ?, ?, ?)",
                (now or time.time(), lang, ",".join(categories), said),
            )
        self.purge(now)

    def notes(self, days: int = 30, now=None) -> list[dict]:
        cutoff = (now or time.time()) - days * 24 * 3600
        cur = self.db.execute(
            "SELECT id, ts, lang, categories, said FROM parent_notes WHERE ts >= ? ORDER BY ts DESC", (cutoff,)
        )
        return [{"id": i, "ts": ts, "lang": lang, "categories": cats.split(","), "said": said} for i, ts, lang, cats, said in cur]

    def clear_notes(self, ids: list[int] | None = None):
        with self.db:
            if ids is None:
                self.db.execute("DELETE FROM parent_notes")
            else:
                self.db.executemany("DELETE FROM parent_notes WHERE id = ?", [(i,) for i in ids])

    # ---------- retention rules ----------

    def purge(self, now=None):
        """Older than 7 days: delete the search term text and the answer text (question text and topic counts are kept)."""
        cutoff = (now or time.time()) - LOG_RETENTION_S
        with self.db:
            self.db.execute("DELETE FROM lookup_log WHERE ts < ?", (cutoff,))
            self.db.execute("UPDATE turns SET answer = NULL WHERE ts < ? AND answer IS NOT NULL", (cutoff,))
            from curiosity_pet.concern import NOTE_RETENTION_DAYS

            note_cutoff = (now or time.time()) - NOTE_RETENTION_DAYS * 24 * 3600
            self.db.execute("DELETE FROM parent_notes WHERE ts < ?", (note_cutoff,))


def count_dict(rows, key):
    out = {}
    for r in rows:
        v = r.get(key)
        if v:
            out[v] = out.get(v, 0) + 1
    return out
