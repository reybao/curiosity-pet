"""Watch API: the only entry point published to the internet (Tailscale Funnel), so it is tested hardest.

Pairing, token checks, limits, the turn protocol, and that nothing else of the pet (the iPad page,
the WebSocket, parent pages) is reachable through it. ASR, TTS and the model are fakes.
"""

import base64
import io
import json
import logging
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from curiosity_pet import pipeline, server, watch_api
from curiosity_pet.store import Store

QUESTION = "为什么天空是蓝色的?"


class FakeASR:
    def transcribe(self, audio):
        return QUESTION, "zh"


class FakeTTS:
    def synthesize(self, text, lang):
        return np.full(2400, 0.1, dtype=np.float32)


def wav(seconds=1.0, rate=16000) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.full(int(seconds * rate), 0.1, dtype=np.float32), rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@pytest.fixture
def auth(tmp_path):
    return watch_api.WatchAuth(tmp_path)


@pytest.fixture
def client(monkeypatch, tmp_path, auth):
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: iter(["天空看起来是蓝色的，", "因为阳光会散开。"]))
    engine = server.Engine(
        asr=FakeASR(), tts=FakeTTS(), make_detector=lambda: None,
        store=Store(tmp_path / "pet.db"), tag_topic=lambda q, lang: "science",
    )
    app = watch_api.create_watch_app(engine, auth, allowed_hosts=["testserver", "*.ts.net"])
    return TestClient(app)


def paired(client, auth) -> dict:
    code = auth.new_pair_code()
    r = client.post("/watch/pair", json={"code": code, "name": "test watch"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def run_turn(client, headers, audio=None, timeout=10):
    r = client.post("/watch/turn", content=audio or wav(), headers={**headers, "Content-Type": "audio/wav"})
    assert r.status_code == 200, r.text
    tid = r.json()["turn_id"]
    got, after, deadline = {"sentences": []}, -1, time.time() + timeout
    while time.time() < deadline:
        p = client.get(f"/watch/turn/{tid}", params={"after": after, "wait": 1}, headers=headers).json()
        got.update({k: v for k, v in p.items() if k != "sentences"})
        got["sentences"] += p["sentences"]
        if p["sentences"]:
            after = p["sentences"][-1]["id"]
        if p["done"]:
            return got
    raise AssertionError("turn did not finish")


# ---------- pairing ----------


def test_unpaired_requests_are_rejected(client):
    assert client.get("/watch/ping").status_code == 401
    assert client.get("/watch/ping", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/watch/turn", content=wav()).status_code == 401


def test_pairing_gives_a_token_that_works(client, auth):
    headers = paired(client, auth)
    r = client.get("/watch/ping", headers=headers)
    assert r.status_code == 200 and r.json()["ok"]


def test_token_is_stored_only_as_a_hash(client, auth, tmp_path):
    headers = paired(client, auth)
    token = headers["Authorization"].split()[1]
    stored = "".join(p.read_text() for p in tmp_path.glob("watch_*.json"))
    assert token not in stored


def test_pair_code_is_single_use(client, auth):
    code = auth.new_pair_code()
    assert client.post("/watch/pair", json={"code": code}).status_code == 200
    assert client.post("/watch/pair", json={"code": code}).status_code == 401


def test_pair_code_expires(client, auth, monkeypatch):
    code = auth.new_pair_code()
    real = time.time
    monkeypatch.setattr(watch_api.time, "time", lambda: real() + watch_api.PAIR_CODE_TTL_S + 1)
    assert client.post("/watch/pair", json={"code": code}).status_code == 401


def test_pair_code_dies_after_too_many_wrong_attempts(client, auth):
    code = auth.new_pair_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(watch_api.PAIR_MAX_ATTEMPTS):
        assert client.post("/watch/pair", json={"code": wrong}).status_code == 401
    # even the right code no longer works: guessing 6 digits gets at most a handful of tries
    assert client.post("/watch/pair", json={"code": code}).status_code == 401


def test_no_pair_code_means_no_pairing(client):
    assert client.post("/watch/pair", json={"code": "123456"}).status_code == 401


def test_revoked_token_stops_working(client, auth):
    headers = paired(client, auth)
    for t in auth.list_tokens():
        auth.revoke(t["id"])
    assert client.get("/watch/ping", headers=headers).status_code == 401


# ---------- only the watch endpoints are exposed ----------


@pytest.mark.parametrize("path", ["/", "/ws", "/static/app.js", "/skin.json", "/parent", "/docs", "/openapi.json"])
def test_nothing_else_of_the_pet_is_reachable(client, auth, path):
    headers = paired(client, auth)
    assert client.get(path, headers=headers).status_code == 404


def test_untrusted_host_is_rejected(client):
    assert client.get("/watch/ping", headers={"host": "evil.example.com"}).status_code == 400


# ---------- limits ----------


def test_oversized_audio_is_rejected(client, auth):
    headers = paired(client, auth)
    big = b"\0" * (watch_api.MAX_AUDIO_BYTES + 1)
    r = client.post("/watch/turn", content=big, headers={**headers, "Content-Type": "audio/wav"})
    assert r.status_code == 413


def test_garbage_audio_is_rejected(client, auth):
    headers = paired(client, auth)
    r = client.post("/watch/turn", content=b"not audio", headers={**headers, "Content-Type": "audio/wav"})
    assert r.status_code == 400


def test_rate_limit(client, auth, monkeypatch):
    monkeypatch.setattr(watch_api, "RATE_PER_MINUTE", 3)
    headers = paired(client, auth)
    codes = [client.get("/watch/ping", headers=headers).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]


def test_failed_auth_flood_locks_out(client, monkeypatch):
    monkeypatch.setattr(watch_api, "MAX_FAILED_AUTH", 3)
    for _ in range(3):
        client.get("/watch/ping", headers={"Authorization": "Bearer wrong"})
    assert client.post("/watch/pair", json={"code": "123456"}).status_code == 429


# ---------- the turn protocol ----------


def test_turn_returns_heard_text_and_sentences_with_audio(client, auth):
    headers = paired(client, auth)
    got = run_turn(client, headers)
    assert got["heard"] == QUESTION and got["lang"] == "zh"
    texts = [s["text"] for s in got["sentences"]]
    assert texts == ["天空看起来是蓝色的，", "因为阳光会散开。"]
    audio, rate = sf.read(io.BytesIO(base64.b64decode(got["sentences"][0]["audio"])))
    assert rate == 24000 and len(audio) == 2400


def test_resampled_upload_is_accepted(client, auth):
    headers = paired(client, auth)
    got = run_turn(client, headers, audio=wav(rate=44100))
    assert got["heard"] == QUESTION


def test_unknown_turn_is_404(client, auth):
    headers = paired(client, auth)
    assert client.get("/watch/turn/nope", headers=headers).status_code == 404


def test_turns_are_private_to_their_watch(client, auth):
    a = paired(client, auth)
    b = paired(client, auth)
    tid = client.post("/watch/turn", content=wav(), headers={**a, "Content-Type": "audio/wav"}).json()["turn_id"]
    assert client.get(f"/watch/turn/{tid}", headers=b).status_code == 404


def test_end_clears_the_conversation(client, auth):
    headers = paired(client, auth)
    run_turn(client, headers)
    assert client.post("/watch/end", headers=headers).status_code == 200
    hub = client.app.state.hub
    assert all(s.pet.history == [] for s in hub.sessions.values())


def test_watch_turns_are_recorded_as_watch_usage(client, auth, tmp_path):
    headers = paired(client, auth)
    run_turn(client, headers)
    client.post("/watch/end", headers=headers)
    sessions = Store(tmp_path / "pet.db").recent_sessions()
    assert sessions and sessions[-1]["client"] == "watch"


def test_child_text_is_not_logged(client, auth, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    headers = paired(client, auth)
    run_turn(client, headers)
    out = capsys.readouterr()
    for text in (QUESTION, "天空看起来是蓝色的", "因为阳光会散开"):
        assert text not in caplog.text
        assert text not in out.out + out.err
    token = headers["Authorization"].split()[1]
    assert token not in caplog.text
