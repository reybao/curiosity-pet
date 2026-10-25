"""Apple Watch API (stage 2b): the only entry point of the pet published to the internet.

The watch cannot run Tailscale, and a GPS watch away from home reaches the internet only through the paired
iPhone, so this small app listens on its own port (127.0.0.1:8731 by default) and `tailscale funnel` publishes
it as https://<mac>.<tailnet>.ts.net:8443. Everything else of the pet (the iPad page, the WebSocket, parent
pages) stays on the tailnet-only port; this app has the watch endpoints and nothing else.

watchOS allows plain HTTP requests but restricts long-lived sockets (WebSockets) to audio-streaming apps,
so the protocol is request/response:
  POST /watch/pair   {"code": "123456", "name": ...}  -> {"token": ...}   (code from `uv run pet-watch-pair`)
  GET  /watch/ping                                     -> {"ok": true, "name": ...}
  POST /watch/turn   body = WAV recording              -> {"turn_id": ...}
  GET  /watch/turn/{id}?after=N&wait=S                 -> {"heard", "lang", "sentences": [{"id", "text", "audio"}],
                                                           "done", "source", "unavailable"}   (long poll; audio = base64 WAV)
  POST /watch/end                                      -> {"ok": true}    (forget the conversation)

Security (the port is public):
- Every request but /watch/pair needs "Authorization: Bearer <token>". Tokens are 256-bit random values,
  stored only as SHA-256 hashes in PET_DATA_DIR/watch_tokens.json; the parent can list and revoke them.
- A pairing code is 6 digits, valid PAIR_CODE_TTL_S, single use, and dies after PAIR_MAX_ATTEMPTS wrong tries.
- Too many failed authentications in a window lock pairing and auth out for a while; each token is rate limited.
- Uploads are capped at MAX_AUDIO_BYTES; only the Host names of the tailnet are accepted.
- Logs record timings only: never the child's words, the answers, pairing codes or tokens (hard constraint 2).
The audio stays between the watch and this Mac: Funnel relays the TLS stream, which ends on this machine.
"""

import asyncio
import base64
import collections
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from curiosity_pet import config

log = logging.getLogger("curiosity_pet.watch")

WATCH_PORT = int(os.environ.get("PET_WATCH_PORT", "8731"))
PAIR_CODE_TTL_S = 300
PAIR_MAX_ATTEMPTS = 5
MAX_FAILED_AUTH = 20  # in FAILED_AUTH_WINDOW_S, across all clients
FAILED_AUTH_WINDOW_S = 600
RATE_PER_MINUTE = 120  # per token; a turn takes a few long polls
MAX_AUDIO_BYTES = 3_000_000  # about 30 s of 48 kHz 16-bit mono
MAX_AUDIO_S = 30
SESSION_IDLE_S = 600  # a pause this long starts a new exploration
TURN_KEEP_S = 300
MAX_WAIT_S = 15
ASR_RATE = 16000
TTS_RATE = 24000


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write_private(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class WatchAuth:
    """Pairing codes and tokens, kept in the data directory so the pairing command and the server can be
    separate processes."""

    def __init__(self, data_dir: Path | None = None):
        d = Path(data_dir) if data_dir is not None else config.DATA_DIR
        self.tokens_file = d / "watch_tokens.json"
        self.pair_file = d / "watch_pair.json"
        self.lock = threading.Lock()

    def new_pair_code(self) -> str:
        code = f"{secrets.randbelow(10**6):06d}"
        salt = secrets.token_hex(8)
        with self.lock:
            _write_private(self.pair_file, {
                "salt": salt, "hash": _sha(salt + code), "expires": time.time() + PAIR_CODE_TTL_S, "attempts": 0,
            })
        return code

    def pair(self, code: str, name: str = "watch") -> str | None:
        """Returns a new token for the right code; None otherwise. A wrong code counts an attempt."""
        with self.lock:
            p = _read(self.pair_file, None)
            if not p or time.time() > p["expires"] or p["attempts"] >= PAIR_MAX_ATTEMPTS:
                return None
            if not hmac.compare_digest(_sha(p["salt"] + str(code)), p["hash"]):
                p["attempts"] += 1
                _write_private(self.pair_file, p)
                return None
            self.pair_file.unlink(missing_ok=True)  # single use
            token = secrets.token_urlsafe(32)
            tokens = _read(self.tokens_file, [])
            tokens.append({
                "id": secrets.token_hex(4), "hash": _sha(token), "name": str(name)[:40], "created": time.time(),
            })
            _write_private(self.tokens_file, tokens)
            return token

    def check(self, token: str) -> dict | None:
        h = _sha(token)
        for t in _read(self.tokens_file, []):
            if hmac.compare_digest(t["hash"], h):
                return t
        return None

    def list_tokens(self) -> list[dict]:
        return [{k: t[k] for k in ("id", "name", "created")} for t in _read(self.tokens_file, [])]

    def revoke(self, token_id: str) -> bool:
        with self.lock:
            tokens = _read(self.tokens_file, [])
            kept = [t for t in tokens if t["id"] != token_id]
            _write_private(self.tokens_file, kept)
            return len(kept) != len(tokens)


@dataclass
class Job:
    token_id: str
    created: float = field(default_factory=time.time)
    heard: str | None = None
    lang: str | None = None
    sentences: list[dict] = field(default_factory=list)
    done: bool = False
    source: str | None = None
    unavailable: bool = False


class JobPlayer:
    """Stands in for the speaker: each sentence goes into the current job as text plus a WAV."""

    def __init__(self):
        self.job: Job | None = None

    def play(self, audio: np.ndarray, text: str | None = None, on_start=None):
        if text is None or self.job is None:
            return  # the "heard you" cue is the watch's own haptic tap
        from curiosity_pet.server import wav_bytes

        self.job.sentences.append({
            "id": len(self.job.sentences), "text": text,
            "audio": base64.b64encode(wav_bytes(audio, TTS_RATE)).decode(),
        })


@dataclass
class WatchSession:
    pet: object
    player: JobPlayer
    last_active: float = field(default_factory=time.time)
    busy: bool = False


class Hub:
    def __init__(self, engine, auth: WatchAuth):
        self.engine = engine
        self.auth = auth
        self.sessions: dict[str, WatchSession] = {}
        self.jobs: dict[str, Job] = {}
        self.failed: collections.deque = collections.deque()
        self.calls: dict[str, collections.deque] = {}

    # ---------- limits ----------

    def locked_out(self) -> bool:
        cutoff = time.time() - FAILED_AUTH_WINDOW_S
        while self.failed and self.failed[0] < cutoff:
            self.failed.popleft()
        return len(self.failed) >= MAX_FAILED_AUTH

    def fail(self):
        self.failed.append(time.time())

    def over_rate(self, token_id: str) -> bool:
        q = self.calls.setdefault(token_id, collections.deque())
        now = time.time()
        while q and q[0] < now - 60:
            q.popleft()
        q.append(now)
        return len(q) > RATE_PER_MINUTE

    # ---------- sessions and turns ----------

    def session(self, token_id: str) -> WatchSession:
        s = self.sessions.get(token_id)
        now = time.time()
        if s is not None and now - s.last_active > SESSION_IDLE_S and not s.busy:
            s.pet.end_session("idle")
            s = None
        if s is None:
            from curiosity_pet.pipeline import Pet
            from curiosity_pet.riddles import RiddleGame, judge_with_model
            from curiosity_pet.usage import UsageLog

            e = self.engine
            usage = UsageLog(e.store, tag_topic=e.tag_topic, client="watch") if e.store else None
            player = JobPlayer()
            pet = Pet(
                e.asr, e.tts, player, researcher=e.researcher, usage=usage,
                riddles=RiddleGame(store=e.store, judge=judge_with_model),
            )
            s = self.sessions[token_id] = WatchSession(pet=pet, player=player)
        s.last_active = now
        return s

    def start_turn(self, token_id: str, audio: np.ndarray) -> str:
        from curiosity_pet.server import ENGINE_LOCK

        s = self.session(token_id)
        job = Job(token_id=token_id)
        job_id = secrets.token_urlsafe(9)
        self.jobs[job_id] = job
        self.prune()

        def on_question(q, lang):
            job.heard, job.lang = q, lang

        def run():
            try:
                with ENGINE_LOCK:
                    s.player.job = job
                    s.pet.on_question = on_question
                    turn = s.pet.handle_audio(audio, play_cue=False)
                job.heard = job.heard if job.heard is not None else turn.question
                job.lang = job.lang or turn.lang
                job.source, job.unavailable = turn.source, turn.unavailable
                log.info(
                    "watch turn lang=%s looked_up=%s asr_s=%s first_audio_s=%s total_s=%s",
                    turn.lang, turn.looked_up, turn.asr_s, turn.first_audio_s, turn.total_s,
                )
            except Exception as e:  # noqa: BLE001  the watch must get an answer, never a hang
                log.warning("watch turn failed: %s", type(e).__name__)
                job.unavailable = True
            finally:
                s.player.job = None
                s.busy = False
                s.last_active = time.time()
                job.done = True

        s.busy = True
        threading.Thread(target=run, daemon=True).start()
        return job_id

    def end(self, token_id: str):
        s = self.sessions.pop(token_id, None)
        if s is not None:
            s.pet.end_session("end_button")

    def prune(self):
        cutoff = time.time() - TURN_KEEP_S
        for k in [k for k, j in self.jobs.items() if j.created < cutoff and j.done]:
            del self.jobs[k]


def decode_audio(raw: bytes) -> np.ndarray | None:
    """WAV (or anything libsndfile reads) to 16 kHz mono float32; None when it is not audio."""
    import soundfile as sf

    try:
        audio, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001  malformed uploads are the client's problem
        return None
    audio = audio.mean(axis=1)
    if len(audio) == 0 or len(audio) > MAX_AUDIO_S * rate:
        return None
    if rate != ASR_RATE:
        n = int(len(audio) * ASR_RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def create_watch_app(engine, auth: WatchAuth | None = None, allowed_hosts: list[str] | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["127.0.0.1", "localhost", "*.ts.net"])
    hub = app.state.hub = Hub(engine, auth or WatchAuth())

    def deny(status: int) -> Response:
        return JSONResponse({"ok": False}, status_code=status)

    def authed(request: Request) -> dict | Response:
        if hub.locked_out():
            return deny(429)
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return deny(401)
        tok = hub.auth.check(header[7:].strip())
        if tok is None:
            hub.fail()
            return deny(401)
        if hub.over_rate(tok["id"]):
            return deny(429)
        return tok

    @app.post("/watch/pair")
    async def pair(request: Request):
        if hub.locked_out():
            return deny(429)
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            return deny(400)
        token = hub.auth.pair(str(body.get("code", ""))[:12], str(body.get("name", "watch")))
        if token is None:
            hub.fail()
            return deny(401)
        return {"token": token}

    @app.get("/watch/ping")
    def ping(request: Request):
        tok = authed(request)
        if isinstance(tok, Response):
            return tok
        return {"ok": True, "name": config.PERSONA["name"]}

    @app.post("/watch/turn")
    async def turn(request: Request):
        tok = authed(request)
        if isinstance(tok, Response):
            return tok
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > MAX_AUDIO_BYTES:
            return deny(413)
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_AUDIO_BYTES:
                return deny(413)
        s = hub.sessions.get(tok["id"])
        if s is not None and s.busy:
            return deny(409)  # one question at a time per watch
        audio = await asyncio.to_thread(decode_audio, bytes(body))
        if audio is None:
            return deny(400)
        return {"turn_id": hub.start_turn(tok["id"], audio)}

    @app.get("/watch/turn/{job_id}")
    async def poll(request: Request, job_id: str, after: int = -1, wait: float = 10):
        tok = authed(request)
        if isinstance(tok, Response):
            return tok
        job = hub.jobs.get(job_id)
        if job is None or job.token_id != tok["id"]:
            return deny(404)
        deadline = time.time() + max(0.0, min(wait, MAX_WAIT_S))
        while not job.done and len(job.sentences) <= after + 1 and time.time() < deadline:
            await asyncio.sleep(0.05)
        new = [x for x in list(job.sentences) if x["id"] > after]
        return {
            "heard": job.heard, "lang": job.lang, "sentences": new,
            "done": job.done and len(new) == len(job.sentences) - (after + 1),
            "source": job.source, "unavailable": job.unavailable,
        }

    @app.post("/watch/end")
    def end(request: Request):
        tok = authed(request)
        if isinstance(tok, Response):
            return tok
        hub.end(tok["id"])
        return {"ok": True}

    return app


def pair_main():
    """`uv run pet-watch-pair`: print a pairing code for the watch app, or list/revoke paired watches."""
    import argparse
    import datetime

    ap = argparse.ArgumentParser(description="Pair an Apple Watch with the pet")
    ap.add_argument("--list", action="store_true", help="list paired watches")
    ap.add_argument("--revoke", metavar="ID", help="revoke a paired watch")
    args = ap.parse_args()
    auth = WatchAuth()
    if args.list:
        for t in auth.list_tokens():
            print(t["id"], t["name"], datetime.datetime.fromtimestamp(t["created"]).strftime("%Y-%m-%d %H:%M"))
        return
    if args.revoke:
        print("revoked" if auth.revoke(args.revoke) else "no such watch")
        return
    code = auth.new_pair_code()
    print(f"Pairing code: {code}  (valid {PAIR_CODE_TTL_S // 60} minutes, {PAIR_MAX_ATTEMPTS} tries)")
