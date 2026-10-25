"""Memory the child chooses (interest cards, My Discoveries), the natural wrap-up, and ending after goodbye."""

import json

import numpy as np

from curiosity_pet import config, parent_log, pipeline
from curiosity_pet.pipeline import Pet
from curiosity_pet.store import Store
from curiosity_pet.usage import UsageLog


class TTS:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, lang):
        self.spoken.append(text)
        return np.zeros(10, dtype=np.float32)


class Player:
    def play(self, audio, text=None, on_start=None):
        pass


def make(tmp_path, monkeypatch, reply="恐龙生活在很久很久以前。"):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter([reply]))
    store = Store(tmp_path / "pet.db")
    tts = TTS()
    return Pet(asr=None, tts=tts, player=Player(), usage=UsageLog(store)), tts, store


def test_interest_cards_from_her_own_words(tmp_path, monkeypatch):
    pet, tts, store = make(tmp_path, monkeypatch)
    pet.answer("我喜欢恐龙")
    assert tts.spoken[0] == "我记住啦,你喜欢恐龙。" and store.interests() == ["dinosaurs"]
    pet.answer("I love space!")
    tts.spoken.clear()
    pet.answer("你记得我喜欢什么吗?")
    assert tts.spoken == ["我记得你喜欢恐龙和太空。"]
    pet.answer("我不喜欢恐龙了")
    assert store.interests() == ["space"]
    pet.answer("你喜欢吃什么?")  # about the pet, not her
    assert store.interests() == ["space"]


def test_save_keeps_the_last_exchange(tmp_path, monkeypatch, capsys):
    pet, tts, store = make(tmp_path, monkeypatch)
    pet.answer("收藏这个")
    assert "还没聊" in tts.spoken[-1] and store.discoveries() == []
    pet.answer("恐龙生活在什么时候?")
    pet.answer("收藏这个")
    assert [(d["question"], d["answer"]) for d in store.discoveries()] == [("恐龙生活在什么时候?", "恐龙生活在很久很久以前。")]
    parent_log.main(["--db", str(tmp_path / "pet.db")])
    assert "我的发现(1 条" in capsys.readouterr().out


def test_wrap_up_after_the_time_limit(tmp_path, monkeypatch):
    pet, tts, store = make(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "WRAP_UP_MINUTES", 0)
    turn = pet.answer("恐龙生活在什么时候?")
    assert turn.ended and tts.spoken[-1].startswith("我们今天探索了好一会儿啦")
    assert pet.history == [] and pet.started_at is None


def test_no_wrap_up_in_the_middle_of_a_riddle(tmp_path, monkeypatch):
    pet, tts, store = make(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "WRAP_UP_MINUTES", 0)
    turn = pet.answer("给我出个脑筋急转弯")
    assert not turn.ended and pet.riddles.pending is not None


def test_goodbye_goes_idle_after_playback(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from curiosity_pet import server

    class Detector:
        def reset(self):
            pass

        def feed(self, chunk):
            return None

    engine = server.Engine(asr=None, tts=TTS(), make_detector=Detector)
    c = TestClient(server.create_app(engine, allowed_hosts=["testserver"]))
    with c.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"type": "text", "text": "拜拜"}))
        seen = []
        while True:
            m = ws.receive()
            if m.get("text"):
                msg = json.loads(m["text"])
                seen.append(msg["type"])
                if msg["type"] == "done":
                    break
        ws.send_text(json.dumps({"type": "playback_done"}))
        assert ws.receive_json() == {"type": "session_ended"}
        assert ws.receive_json() == {"type": "state", "state": "idle"}


def test_will_you_remember_me_gets_the_honest_fixed_answer(tmp_path, monkeypatch):
    from curiosity_pet.memory import asks_if_remembered

    for q in ["你会记住我今天说的话吗?", "Do you have memory about me? Will you remember what I said next time?", "你会忘记我吗"]:
        assert asks_if_remembered(q), q
    assert not asks_if_remembered("你记得我喜欢什么吗?") and not asks_if_remembered("记住这个单词怎么写")
    pet, tts, store = make(tmp_path, monkeypatch)
    pet.answer("你会记住我今天说的话吗?")
    assert "".join(tts.spoken).startswith("我们聊的话,我不会一直记着。")
