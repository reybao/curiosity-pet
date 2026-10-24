"""本机 SQLite 存储(PET_DATA_DIR/pet.db)。

目前只存联网查询相关的数据:
- lookup_log:发出去的搜索词(改写后的话题词,不是孩子原话),保留 7 天供家长查看,到期删除;
- topic_week:按周、按主题统计的查询次数,长期保留,周报只用它做事实性趋势;
- kb_pending:从维基百科取回的资料,标为待审核,家长审核后进入知识库(阶段 4 知识库部分)。
"""

import sqlite3
import time
from pathlib import Path

from curiosity_pet import config

LOG_RETENTION_S = 7 * 24 * 3600

SCHEMA = """
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


def week_of(ts: float) -> str:
    return time.strftime("%G-W%V", time.localtime(ts))


class Store:
    def __init__(self, path: Path | str | None = None):
        path = Path(path) if path else config.DATA_DIR / "pet.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def record_lookup(self, lang, query, topic, title=None, found=False, now=None):
        now = now or time.time()
        with self.db:
            self.db.execute(
                "INSERT INTO lookup_log (ts, lang, query, topic, title, found) VALUES (?, ?, ?, ?, ?, ?)",
                (now, lang, query, topic, title, int(found)),
            )
            self.db.execute(
                "INSERT INTO topic_week (week, topic, n) VALUES (?, ?, 1) "
                "ON CONFLICT (week, topic) DO UPDATE SET n = n + 1",
                (week_of(now), topic),
            )
        self.purge(now)

    def save_pending(self, lang, title, url, text, now=None):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO kb_pending (ts, lang, title, url, text) VALUES (?, ?, ?, ?, ?)",
                (now or time.time(), lang, title, url, text),
            )

    def purge(self, now=None):
        """删除 7 天前的搜索词原文;主题计数保留。"""
        cutoff = (now or time.time()) - LOG_RETENTION_S
        with self.db:
            self.db.execute("DELETE FROM lookup_log WHERE ts < ?", (cutoff,))

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
