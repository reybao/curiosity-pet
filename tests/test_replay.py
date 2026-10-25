"""The replay evaluation harness, on fictional turns with a fake model: scoring, context handling, isolation."""

import importlib.util
from pathlib import Path

from curiosity_pet import call_parent, pipeline

spec = importlib.util.spec_from_file_location("replay_eval", Path(__file__).resolve().parents[1] / "evals" / "replay_eval.py")
replay_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay_eval)

TURNS = [
    {"id": 1, "session": 1, "lang": "zh", "question": "你好。"},
    {"id": 2, "session": 1, "lang": "zh", "question": "Ha ha ha!"},
    {"id": 3, "session": 1, "lang": "zh", "question": "一加一等于几?"},
    {"id": 4, "session": 2, "lang": "zh", "question": "我要找妈妈。"},
    {"id": 5, "session": 2, "lang": "zh", "question": "要。"},
    {"id": 6, "session": 3, "lang": "zh", "question": "十。"},
    {"id": 7, "session": 3, "lang": "zh", "question": "好,谢谢,拜拜。"},
]
LABELS = {"1": {"intent": "chat", "context": None}, "2": {"intent": "noise", "context": None},
          "3": {"intent": "math", "context": None}, "4": {"intent": "call", "context": None},
          "5": {"intent": "call_reply", "context": "call_pending"}, "6": {"intent": "answer", "context": "pet_asked"},
          "7": {"intent": "goodbye", "context": None}}


class NoLookup:
    def decide(self, question, lang):
        from curiosity_pet.lookup import Decision

        return Decision(False, "test")


def test_replay_scores_routes_and_keeps_everything_local(monkeypatch):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["好的。"]))
    sent = []
    monkeypatch.setattr(call_parent, "telegram_send", lambda *a: sent.append(a) or True)
    rows = replay_eval.replay(TURNS, LABELS, log=lambda *a: None, researcher=NoLookup())
    by_id = {r["id"]: r for r in rows}
    assert by_id[1]["status"] == "ok" and by_id[2]["route"] == "ignore" and by_id[3]["route"] == "math"
    assert by_id[4]["route"] == "call" and by_id[5]["status"] == "ok"  # the pending question was reproduced
    assert by_id[6]["status"] == "context_changed"  # the fake model asked nothing before "十。"
    assert by_id[7]["status"] == "ok"  # "好,谢谢,拜拜" is a goodbye
    assert sent == []  # the fake sender in the harness, never Telegram
    s = replay_eval.summarize(rows)
    assert s["scored"] == 6 and s["correct"] == 6 and s["context_changed"] == 1
    assert "你好" not in replay_eval.summary_only(s)  # the committable summary carries no child words
