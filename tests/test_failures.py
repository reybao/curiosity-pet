"""Failure tests (stage 7): the model goes away, the network is down, the service restarts, backups are consistent."""

import shutil
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
import pytest

from curiosity_pet import pipeline
from curiosity_pet.llm import UNAVAILABLE_TEXT, PetUnavailable
from curiosity_pet.lookup import Decision, Researcher
from curiosity_pet.pipeline import Pet
from curiosity_pet.store import Store
from curiosity_pet.usage import UsageLog

PROJECT = Path(__file__).resolve().parents[1]


class TTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class Player:
    def play(self, audio, text=None, on_start=None):
        pass


def test_model_gone_mid_answer_says_tired_and_recovers(monkeypatch):
    state = {"down": True}

    def stream(msgs):
        if state["down"]:
            raise PetUnavailable("ollama exited")
        return iter(["月亮绕着地球转。"])

    monkeypatch.setattr(pipeline, "stream_chat", stream)
    tts = TTS()
    pet = Pet(asr=None, tts=tts, player=Player())
    turn = pet.answer("月亮为什么会动?")
    assert turn.unavailable and tts.spoken == [UNAVAILABLE_TEXT["zh"]]
    state["down"] = False
    tts.spoken.clear()
    pet.answer("月亮为什么会动?")
    assert tts.spoken == ["月亮绕着地球转。"]


def test_network_down_still_answers_offline(monkeypatch):
    class DeadProvider:
        name = "wikipedia"

        def search(self, query, lang):
            raise OSError("network is unreachable")

    class OfflineResearcher(Researcher):
        def decide(self, question, lang):
            return Decision(True, "", query="月亮", topic="space", kind="knowledge")

    researcher = OfflineResearcher(providers=[DeadProvider()], rewrite=lambda q, l: {})
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["月亮绕着地球转。"]))
    tts = TTS()
    turn = Pet(asr=None, tts=tts, player=Player(), researcher=researcher).answer("月亮为什么会动?")
    assert "月亮绕着地球转。" in tts.spoken and not turn.unavailable


def test_records_survive_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["恐龙生活在很久以前。"]))
    db = tmp_path / "pet.db"
    store = Store(db)
    pet = Pet(asr=None, tts=TTS(), player=Player(), usage=UsageLog(store))
    pet.answer("我喜欢恐龙")
    pet.answer("恐龙生活在什么时候?")
    pet.answer("收藏这个")
    pet.answer("我今天好难过")
    store.db.close()  # the process dies
    again = Store(db)  # and starts again
    assert again.interests() == ["dinosaurs"]
    assert [d["question"] for d in again.discoveries()] == ["恐龙生活在什么时候?"]
    assert [n["said"] for n in again.notes()] == ["我今天好难过"]
    assert again.db.execute("SELECT COUNT(*) FROM turns").fetchone()[0] >= 3


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="sqlite3 command line tool needed")
def test_backup_script_makes_a_consistent_copy_and_rotates(tmp_path):
    data, backups = tmp_path / "data", tmp_path / "backups"
    data.mkdir()
    store = Store(data / "pet.db")
    store.add_interest("space")
    (data / "settings.json").write_text('{"skin": "cat"}')
    (data / "skin-goku").mkdir()
    (data / "skin-goku" / "skin.json").write_text("{}")
    for _ in range(3):
        subprocess.run(["bash", str(PROJECT / "scripts" / "backup.sh"), str(data), str(backups)], check=True,
                       env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "KEEP": "2"}, capture_output=True)
        __import__("time").sleep(1.1)  # distinct timestamps
    kept = sorted(backups.iterdir())
    assert len(kept) == 2
    copy = sqlite3.connect(kept[-1] / "pet.db")
    assert copy.execute("SELECT topic FROM interests").fetchall() == [("space",)]
    assert (kept[-1] / "settings.json").exists() and (kept[-1] / "skin-goku" / "skin.json").exists()


def test_sessions_left_open_are_closed_at_their_last_activity(tmp_path):
    store = Store(tmp_path / "pet.db")
    old = store.start_session("watch", now=1000.0)
    store.record_turn(old, lang="zh", question="q", answer="a", topic="other", follow_up=None, looked_up=False,
                      source=None, asr_s=0.1, first_audio_s=1.0, total_s=2.0, unavailable=False, now=1100.0)
    fresh = store.start_session("ipad", now=1100.0 + 31 * 60)  # starting a new one closes the stale one
    row = store.db.execute("SELECT end_ts, end_reason FROM sessions WHERE id = ?", (old,)).fetchone()
    assert row == (1100.0, "stale") and store.open_sessions() == [fresh]
