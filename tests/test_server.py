"""iPad web service: protocol, half-duplex, access restrictions, no outbound connections, no logging of the child's words.

ASR, TTS, VAD and the model are all fakes; only the service layer is tested.
"""

import json
import logging
import re
import struct
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from curiosity_pet import pipeline, server
from curiosity_pet.store import Store

QUESTION = "为什么天空是蓝色的?"
ORIGIN = {"origin": "http://testserver"}


class FakeASR:
    def transcribe(self, audio):
        return QUESTION, "zh"


class FakeTTS:
    def synthesize(self, text, lang):
        return np.full(2400, 0.1, dtype=np.float32)


class FakeDetector:
    """Treats the utterance as finished after 3 non-zero audio chunks."""

    def __init__(self):
        self.fed = 0

    def feed(self, chunk):
        self.fed += 1
        return np.ones(1600, dtype=np.float32) if self.fed % 3 == 0 else None

    def reset(self):
        pass


@pytest.fixture
def detectors():
    return []


@pytest.fixture
def client(monkeypatch, detectors, tmp_path):
    monkeypatch.setattr(
        pipeline, "stream_chat", lambda msgs: iter(["天空看起来是蓝色的，", "因为阳光会散开。"])
    )

    def make_detector():
        d = FakeDetector()
        detectors.append(d)
        return d

    engine = server.Engine(
        asr=FakeASR(), tts=FakeTTS(), make_detector=make_detector,
        store=Store(tmp_path / "pet.db"), tag_topic=lambda q, lang: "science",
    )
    return TestClient(server.create_app(engine, allowed_hosts=[*server.DEFAULT_ALLOWED_HOSTS, "testserver"]))


def receive_until_done(ws):
    """Receive messages until done; return (list of JSON messages, list of binary audio frames)."""
    msgs, audio = [], []
    while True:
        m = ws.receive()
        if m.get("bytes") is not None:
            audio.append(m["bytes"])
            continue
        msg = json.loads(m["text"])
        msgs.append(msg)
        if msg["type"] == "done":
            return msgs, audio


def pcm_chunk(n=512, value=1000):
    return struct.pack(f"<{n}h", *([value] * n))


def test_index_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


def test_web_files_have_no_external_urls():
    # Hard constraint 1: no CDN, third-party fonts or analytics
    allowed = {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"}
    for f in Path(server.WEB_DIR).rglob("*"):
        if f.is_file() and f.suffix != ".png":
            urls = set(re.findall(r"https?://[^\s\"'<>)]+", f.read_text(encoding="utf-8")))
            assert urls <= allowed, (f.name, urls - allowed)


def test_page_and_static_files_are_not_cached(client):
    # The iPad's home-screen web app kept showing the old UI after updates
    for path in ("/", "/static/app.js", "/static/style.css"):
        assert client.get(path).headers["cache-control"] == "no-cache", path


def test_untrusted_host_is_rejected(client):
    r = client.get("/", headers={"host": "evil.example.com"})
    assert r.status_code == 400


def test_tailscale_host_is_allowed(client):
    r = client.get("/", headers={"host": "pet-mini.tail1234.ts.net"})
    assert r.status_code == 200


def test_websocket_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example.com"}) as ws:
            ws.receive_text()


def test_text_turn_protocol(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "listening"}
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        msgs, audio = receive_until_done(ws)

    types = [m["type"] for m in msgs]
    assert msgs[0] == {"type": "state", "state": "thinking"}
    assert {"type": "heard", "text": QUESTION, "lang": "zh"} in msgs
    sentences = [m for m in msgs if m["type"] == "sentence"]
    assert [s["text"] for s in sentences] == ["天空看起来是蓝色的，", "因为阳光会散开。"]
    assert {"type": "state", "state": "speaking"} in msgs
    assert types.index("state") < types.index("sentence")
    # Per-sentence audio: 4-byte sentence id + 24kHz PCM16
    assert len(audio) == 2
    ids = [struct.unpack("<I", a[:4])[0] for a in audio]
    assert ids == [s["id"] for s in sentences]
    assert len(audio[0]) == 4 + 2400 * 2
    assert "first_audio_s" in msgs[-1]["timings"]


def test_playback_done_returns_to_listening(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        receive_until_done(ws)
        ws.send_text(json.dumps({"type": "playback_done"}))
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "listening"}


def test_audio_turn_via_vad(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        for _ in range(3):
            ws.send_bytes(pcm_chunk())
        msgs, audio = receive_until_done(ws)
    assert msgs[0] == {"type": "state", "state": "thinking"}
    assert any(m["type"] == "heard" and m["text"] == QUESTION for m in msgs)
    assert audio


def test_audio_is_ignored_while_speaking(client, detectors):
    # Half-duplex: the pet does not listen while speaking, so it does not mistake its own voice for a question
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        receive_until_done(ws)
        fed_before = detectors[0].fed
        for _ in range(5):
            ws.send_bytes(pcm_chunk())
        ws.send_text(json.dumps({"type": "playback_done"}))
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "listening"}
    assert detectors[0].fed == fed_before


def test_end_session_clears_history_and_goes_idle(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        receive_until_done(ws)
        ws.send_text(json.dumps({"type": "end_session"}))
        assert json.loads(ws.receive_text()) == {"type": "session_ended"}
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "idle"}
        assert server.current_session().pet.history == []
        # Idle: audio and typed questions are ignored until the child presses start again
        for _ in range(3):
            ws.send_bytes(pcm_chunk())
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        ws.send_text(json.dumps({"type": "start"}))
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "listening"}
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        msgs, audio = receive_until_done(ws)
        assert audio and any(m["type"] == "heard" for m in msgs)


def test_stop_during_a_running_turn_discards_it_and_listening_resumes(monkeypatch, client):
    # The bug the parent hit: stop while the pet was thinking or speaking left the server waiting
    # for playback_done forever, so every later question was ignored
    import threading

    gate = threading.Event()
    pieces = ["天空看起来是蓝色的\uff0c", "因为阳光会散开\u3002"]

    def slow_stream(msgs):
        yield pieces[0]
        gate.wait(timeout=5)
        yield pieces[1]

    monkeypatch.setattr(pipeline, "stream_chat", slow_stream)
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "thinking"}
        ws.send_text(json.dumps({"type": "end_session"}))
        seen = []
        while True:
            m = ws.receive()
            if m.get("bytes") is not None:
                seen.append("audio")
                continue
            msg = json.loads(m["text"])
            seen.append(msg["type"])
            if msg == {"type": "state", "state": "idle"}:
                break
        assert "session_ended" in seen and "done" not in seen
        gate.set()  # the old turn's thread wakes up after the stop and must be discarded
        # Resume with a fast model and ask again: a full answer, nothing left over from the old turn
        monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(pieces))
        ws.send_text(json.dumps({"type": "start"}))
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "listening"}
        ws.send_text(json.dumps({"type": "text", "text": "再简单一点"}))
        msgs, audio = receive_until_done(ws)
        assert msgs[0] == {"type": "state", "state": "thinking"}
        assert len(audio) == 2
    # The cancelled turn was not recorded; the second one was
    st = server.current_session().pet.usage.store
    questions = [t["question"] for s in st.recent_sessions(days=1) for t in s["turn_list"]]
    assert questions == ["再简单一点"]


def test_child_text_is_not_logged(client, caplog, capsys):
    # Hard constraint 2: launchd writes output to a log file, so the service must not print or log what the child says or the answers
    caplog.set_level(logging.DEBUG)
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        receive_until_done(ws)
    out = capsys.readouterr()
    for text in (QUESTION, "天空看起来是蓝色的", "因为阳光会散开"):
        assert text not in caplog.text
        assert text not in out.out + out.err


def test_pcm16_to_float():
    raw = struct.pack("<3h", 0, 16384, -32768)
    np.testing.assert_allclose(server.pcm16_to_float(raw), [0.0, 0.5, -1.0])


def test_float_to_pcm16_clips():
    out = server.float_to_pcm16(np.array([0.0, 2.0, -2.0], dtype=np.float32))
    assert struct.unpack("<3h", out) == (0, 32767, -32767)


def test_usage_is_recorded_with_end_reason(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        receive_until_done(ws)
        # The pet does not accept new questions while speaking; report playback done first
        ws.send_text(json.dumps({"type": "playback_done"}))
        assert json.loads(ws.receive_text()) == {"type": "state", "state": "listening"}
        ws.send_text(json.dumps({"type": "text", "text": "再简单一点"}))
        receive_until_done(ws)
        st = server.current_session().pet.usage.store
        ws.send_text(json.dumps({"type": "end_session"}))
        ws.receive_text()
    sessions = st.recent_sessions(days=1)
    assert len(sessions) == 1
    s = sessions[0]
    assert s["turns"] == 2 and s["end_reason"] == "end_button" and s["client"] == "ipad"
    assert [t["question"] for t in s["turn_list"]] == [QUESTION, "再简单一点"]
    assert s["turn_list"][0]["topic"] == "science"
    assert s["turn_list"][1]["follow_up"] == "simpler"
    assert s["turn_list"][0]["answer"]  # visible within 7 days


def test_disconnect_ends_session(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        receive_until_done(ws)
        st = server.current_session().pet.usage.store
    assert st.recent_sessions(days=1)[0]["end_reason"] == "disconnect"


def test_opening_the_page_without_asking_creates_no_session(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        st = server.current_session().pet.usage.store
    assert st.recent_sessions(days=1) == []
