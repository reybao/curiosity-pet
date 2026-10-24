"""iPad 网页服务:协议、半双工、访问限制、不外连、不记录孩子的话。

ASR、TTS、VAD、模型都用假的,只测服务层。
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

QUESTION = "为什么天空是蓝色的?"
ORIGIN = {"origin": "http://testserver"}


class FakeASR:
    def transcribe(self, audio):
        return QUESTION, "zh"


class FakeTTS:
    def synthesize(self, text, lang):
        return np.full(2400, 0.1, dtype=np.float32)


class FakeDetector:
    """收到 3 块非零音频后判定说完。"""

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
def client(monkeypatch, detectors):
    monkeypatch.setattr(
        pipeline, "stream_chat", lambda msgs: iter(["天空看起来是蓝色的，", "因为阳光会散开。"])
    )

    def make_detector():
        d = FakeDetector()
        detectors.append(d)
        return d

    engine = server.Engine(asr=FakeASR(), tts=FakeTTS(), make_detector=make_detector)
    return TestClient(server.create_app(engine, allowed_hosts=[*server.DEFAULT_ALLOWED_HOSTS, "testserver"]))


def receive_until_done(ws):
    """收消息直到 done,返回(JSON 消息列表, 二进制音频帧列表)。"""
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
    # 硬性约束第 1 条:没有 CDN、第三方字体或统计
    allowed = {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"}
    for f in Path(server.WEB_DIR).rglob("*"):
        if f.is_file():
            urls = set(re.findall(r"https?://[^\s\"'<>)]+", f.read_text(encoding="utf-8")))
            assert urls <= allowed, (f.name, urls - allowed)


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
    # 每句音频:4 字节句子编号 + 24kHz PCM16
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
    # 半双工:宠物说话时不听,避免把自己的声音当成提问
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


def test_push_to_talk(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "ptt_start"}))
        ws.send_bytes(pcm_chunk())
        ws.send_bytes(pcm_chunk())
        ws.send_text(json.dumps({"type": "ptt_end"}))
        msgs, _ = receive_until_done(ws)
    assert any(m["type"] == "heard" for m in msgs)


def test_end_session_clears_history(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "text", "text": QUESTION}))
        receive_until_done(ws)
        ws.send_text(json.dumps({"type": "end_session"}))
        assert json.loads(ws.receive_text()) == {"type": "session_ended"}
        assert server.current_session().pet.history == []


def test_child_text_is_not_logged(client, caplog, capsys):
    # 硬性约束第 2 条:launchd 把输出写进日志文件,服务不得打印或记录孩子说的话和回答
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
