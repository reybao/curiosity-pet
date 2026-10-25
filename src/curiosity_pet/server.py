"""iPad web service (stage 2): FastAPI serves the static page, and a WebSocket carries the voice.

Listens on 127.0.0.1 only; `tailscale serve` provides HTTPS and forwards to it, so devices not signed in to Tailscale cannot reach it.
It also checks the Host header (against DNS rebinding) and the WebSocket Origin (so other web pages cannot connect).

Protocol (/ws):
  iPad -> service: binary frame = 16kHz mono PCM16; JSON:
      {"type": "text", "text": ...}        typed question (for debugging)
      {"type": "start"}                     the child pressed the button: start listening
      {"type": "playback_done"}             iPad finished playing, return to listening
      {"type": "end_session"}               the child pressed stop: cancel any running turn, clear history, go idle
  service -> iPad: JSON:
      {"type": "state", "state": "idle|listening|thinking|speaking"}
      {"type": "heard", "text": ..., "lang": ...}
      {"type": "sentence", "id": n, "text": ...}   followed by one binary frame: 4-byte id + 24kHz PCM16
      {"type": "done", "timings": {...}, "unavailable": bool}
      {"type": "session_ended"}

HTTP besides the page: /skin.json (active skin), /skins.json and /skins/<id>/thumb.png (the skin picker),
POST /skin {"id": ...} (switch skin; same-origin only; ends a running exploration), /cue.wav?lang=zh|en (the sound played
when the pet has heard the child: the skin's own audio file, else its catchphrase in its voice; 404 for the built-in kitten,
whose "meow" the page synthesizes itself).

Half-duplex: the pet does not listen while thinking or speaking; incoming audio is simply dropped, so it does not mistake its own voice for a question.
The child's words are not logged: logs record timings only, never question or answer text (launchd writes output to a log file; hard constraint 2).
"""

import asyncio
import json
import logging
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import numpy as np
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from curiosity_pet import config
from curiosity_pet.pipeline import Pet
from curiosity_pet.riddles import RiddleGame, judge_with_model
from curiosity_pet.usage import UsageLog
from curiosity_pet.vad import CHUNK

log = logging.getLogger("curiosity_pet.server")

WEB_DIR = Path(__file__).parent / "web"
DEFAULT_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "*.ts.net"]
TTS_SAMPLE_RATE = 24000
TIMING_KEYS = ("asr_s", "first_token_s", "first_sentence_s", "first_audio_s", "total_s")

# The MLX model is not thread-safe, so only one turn runs at a time
ENGINE_LOCK = threading.Lock()
_current: "Session | None" = None


@dataclass
class Engine:
    asr: object
    tts: object
    make_detector: Callable[[], object]
    researcher: object | None = None  # web lookup; None means offline
    store: object | None = None  # usage-record database; None means no recording
    tag_topic: Callable[[str, str], str | None] | None = None  # tags a question with a topic afterwards (local model)
    guard: object | None = None  # guard.Guard when settings.json turns it on
    guard_answers: bool = False


def load_engine() -> Engine:
    from curiosity_pet.asr import ASR
    from curiosity_pet.tts import TTS
    from curiosity_pet.vad import UtteranceDetector

    asr, tts = ASR(), TTS()
    apply_skin_voice(tts)
    # Warm-up: Kokoro builds each language's pipeline on first use (measured: the first English answer starts 1.5 s late), and the first ASR call is slow too
    tts.synthesize("你好。", "zh")
    tts.synthesize("Hello.", "en")
    asr.transcribe(np.zeros(16000, dtype=np.float32))
    from curiosity_pet.lookup import Researcher
    from curiosity_pet.store import Store

    store = Store()
    store.close_stale_sessions()  # a session left open by a client that went away (the watch) is over
    researcher = Researcher(store=store)
    if researcher.enabled and not researcher.contact:
        log.warning("Web lookup is enabled but PET_WIKI_CONTACT (the contact info Wikipedia requires) is not set; staying offline")
    from curiosity_pet import guard as guard_mod

    guard_mode = guard_mod.mode()
    guard = None
    if guard_mode != "off":
        try:
            guard = guard_mod.Guard()
        except Exception as e:  # noqa: BLE001  without mlx-lm or the model the pet still runs, without layer 2
            log.warning("guard not loaded: %s", type(e).__name__)
    return Engine(
        asr=asr, tts=tts, make_detector=UtteranceDetector, researcher=researcher, store=store,
        tag_topic=tag_topic_with_model, guard=guard, guard_answers=guard is not None and guard_mode == "all",
    )


def apply_skin_voice(tts, skin: dict | None = None, skin_dir: Path | None = None):
    """The active skin's voice, speed and catchphrase sound. The catchphrase ("皮卡", "Pika") is spoken with the
    skin's own clip (its "cue" file, e.g. a recording the parent provides) or, with "sound_pitch", with the TTS voice
    pitched up; without either it is plain TTS."""
    from curiosity_pet.tts import load_clip, pitch_up, trim_silence

    skin = config.SKIN if skin is None else skin
    skin_dir = config.SKIN_DIR if skin_dir is None else skin_dir
    tts.set_voices(config.skin_voices(skin), config.skin_speed(skin))
    if not hasattr(tts, "set_catchphrase"):
        return
    tts.set_catchphrase()
    if not skin:
        return
    words = config.resolve_persona(skin)["sound"]
    audio = {}
    clip = safe_skin_file(skin_dir, skin.get("cue"))
    if clip is not None:
        try:
            sound = load_clip(clip)
            audio = {"zh": sound, "en": sound}
        except Exception as e:  # noqa: BLE001  a broken clip must not stop the pet
            log.warning("skin cue could not be read: %s", type(e).__name__)
    elif skin.get("sound_pitch"):
        try:
            factor = min(2.0, max(1.0, float(skin["sound_pitch"])))
        except (TypeError, ValueError):
            factor = 1.0
        for lang in ("zh", "en"):
            word = words[lang] + "!" if lang == "zh" else words[lang].capitalize() + "!"
            audio[lang] = pitch_up(trim_silence(tts.synthesize_voice(word, lang)), factor)
    tts.set_catchphrase(words if audio else None, audio)


def tag_topic_with_model(question: str, lang: str) -> str | None:
    """Tag a question with a topic afterwards, reusing the web lookup's classification prompt; only the local model is called."""
    from curiosity_pet.lookup import TOPICS, rewrite_with_model

    topic = rewrite_with_model(question, lang).get("topic")
    return topic if topic in TOPICS else None


def pcm16_to_float(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class WebPlayer:
    """Replaces local playback: sends each sentence's audio and text to the iPad, which plays and highlights it."""

    def __init__(self, send):
        self.send = send  # send(item, generation)
        self.next_id = 0
        self.started = False
        self.cancelled = False
        self.generation = 0

    def new_turn(self, generation: int = 0):
        self.started = False
        self.cancelled = False
        self.generation = generation

    def cancel(self):
        self.cancelled = True  # drop whatever the running turn still produces

    def play(self, audio: np.ndarray, text: str | None = None, on_start=None):
        if text is None or self.cancelled:
            return  # the cue sound is played locally by the iPad
        if not self.started:
            self.started = True
            self.send({"type": "state", "state": "speaking"}, self.generation)
        sid = self.next_id
        self.next_id += 1
        self.send({"type": "sentence", "id": sid, "text": text}, self.generation)
        self.send(struct.pack("<I", sid) + float_to_pcm16(audio), self.generation)


class Session:
    def __init__(self, engine: Engine, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.player = WebPlayer(self._send_from_turn)
        usage = UsageLog(engine.store, tag_topic=engine.tag_topic, client="ipad") if engine.store else None
        self.pet = Pet(
            engine.asr,
            engine.tts,
            self.player,
            on_question=lambda q, lang: self._send_from_turn(
                {"type": "heard", "text": q, "lang": lang}, self.player.generation
            ),
            researcher=engine.researcher,
            usage=usage,
            riddles=RiddleGame(store=engine.store, judge=judge_with_model),
            guard=engine.guard,
            guard_answers=engine.guard_answers,
        )
        self.detector = engine.make_detector()
        self.state = "listening"
        self.pending = np.zeros(0, dtype=np.float32)
        self.task: asyncio.Task | None = None
        self.generation = 0  # bumped on stop; a turn whose generation is stale is discarded
        self.end_after_playback = False  # the pet said goodbye or wrapped up: idle once the iPad has played it
        self.cancel: threading.Event | None = None

    def _send_from_turn(self, item, generation: int):
        """Messages from a turn's thread. The check runs on the event loop, in order with stop_session: a sentence
        that a stopped turn was already sending is dropped there, instead of arriving after "idle" (it did, rarely)."""
        self.loop.call_soon_threadsafe(self._put_if_current, item, generation)

    def _put_if_current(self, item, generation: int):
        if generation == self.generation:
            self.outbox.put_nowait(item)

    def send(self, item):
        self.outbox.put_nowait(item)

    def set_state(self, state):
        self.state = state
        self.send({"type": "state", "state": state})

    def on_audio(self, raw: bytes):
        if self.state != "listening":
            return
        audio = pcm16_to_float(raw)
        self.pending = np.concatenate([self.pending, audio])
        while len(self.pending) >= CHUNK:
            chunk, self.pending = self.pending[:CHUNK], self.pending[CHUNK:]
            utterance = self.detector.feed(chunk)
            if utterance is not None:
                self.pending = np.zeros(0, dtype=np.float32)
                self.start_turn("audio", utterance)
                return

    def on_message(self, msg: dict):
        kind = msg.get("type")
        if kind == "text" and self.state == "listening":
            self.start_turn("text", str(msg.get("text", ""))[:500])
        elif kind == "start":
            # Idempotent: the page may send it again after a reconnect
            if self.state == "idle":
                self.detector.reset()
                self.pending = np.zeros(0, dtype=np.float32)
                self.set_state("listening")
            elif self.state == "listening":
                self.set_state("listening")
        elif kind == "playback_done" and self.state == "speaking":
            self.detector.reset()
            if self.end_after_playback:
                self.end_after_playback = False
                self.state = "idle"
                self.send({"type": "session_ended"})
                self.send({"type": "state", "state": "idle"})
            else:
                self.set_state("listening")
        elif kind == "end_session":
            self.stop_session("end_button")

    def stop_session(self, reason: str):
        """The child pressed stop (or left): cancel a running turn, forget the conversation, go idle.

        A turn that is still generating keeps its thread briefly, but its output is dropped and its
        result ignored because its generation is stale. Before this, a stop during thinking or speaking
        left the server waiting for playback_done forever, ignoring every later question.
        """
        self.generation += 1
        if self.cancel is not None:
            self.cancel.set()
        self.player.cancel()
        self.detector.reset()
        self.pending = np.zeros(0, dtype=np.float32)
        self.state = "idle"
        self.pet.end_session(reason)
        self.send({"type": "session_ended"})
        self.send({"type": "state", "state": "idle"})

    def start_turn(self, kind, payload):
        self.set_state("thinking")
        self.cancel = threading.Event()
        self.task = asyncio.create_task(self._turn(kind, payload, self.generation, self.cancel))

    async def _turn(self, kind, payload, generation, cancel):
        def run():
            with ENGINE_LOCK:
                # Reset the player only once the previous turn's thread has released the lock, so a
                # sentence it was still synthesizing cannot leak into this turn
                self.player.new_turn(generation)
                if kind == "audio":
                    return self.pet.handle_audio(payload, play_cue=False, cancel=cancel)
                return self.pet.answer(payload, cancel=cancel)

        turn = await asyncio.to_thread(run)
        if generation != self.generation or turn.cancelled:
            return  # the child pressed stop while this turn was running
        # Messages queued from the thread are all in the outbox; done comes after them
        timings = {k: getattr(turn, k) for k in TIMING_KEYS}
        # Log only timings, language, whether the web was used and why; never questions, search terms or answers
        log.info(
            "turn lang=%s looked_up=%s reason=%s %s",
            turn.lang,
            turn.looked_up,
            turn.lookup_reason or "-",
            " ".join(f"{k}={v}" for k, v in timings.items()),
        )
        self.send(
            {"type": "done", "timings": timings, "unavailable": turn.unavailable, "source": turn.source}
        )
        self.end_after_playback = turn.ended
        if turn.sentences:
            self.state = "speaking"  # wait for the iPad to send playback_done
        else:
            self.set_state("listening")


def current_session() -> "Session | None":
    return _current


SKIN_STATES = ("idle", "listening", "thinking", "speaking")
SKIN_FILE_TYPES = {".png", ".webp", ".jpg", ".jpeg", ".gif", ".wav", ".mp3", ".m4a", ".aac"}


def safe_skin_file(skin_dir: Path | None, name) -> Path | None:
    """A file directly inside the skin folder, never outside it."""
    if skin_dir is None or not isinstance(name, str) or "/" in name or "\\" in name or ".." in name:
        return None
    path = Path(skin_dir) / name
    return path if path.suffix.lower() in SKIN_FILE_TYPES and path.is_file() else None


def skin_manifest(skin_dir: Path | None, skin_id: str | None = None) -> dict:
    """What the page needs to know about the active skin; only images that exist are listed."""
    skin = config.load_skin(skin_dir)
    persona = config.resolve_persona(skin)
    cue = "/cue.wav" if skin_dir is not None and skin else None
    images = skin.get("images") if isinstance(skin.get("images"), dict) else {}
    found = {state: f"/skin/{images[state]}" for state in SKIN_STATES if safe_skin_file(skin_dir, images.get(state))}
    if "idle" not in found:
        return {"default": True, "id": skin_id, "name": persona["name"], "cue": cue}
    return {"default": False, "id": skin_id, "name": persona["name"], "images": found, "cue": cue}


DEFAULT_ICON = WEB_DIR / "icon.png"
ICON_BG = (253, 246, 236, 255)
_icon_cache: dict[str, bytes] = {}
_cue_cache: dict[tuple, bytes] = {}


def trim_cue(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    """Cut Kokoro's leading and trailing silence so the cue sounds the moment the child stops talking."""
    voiced = np.flatnonzero(np.abs(audio) > threshold)
    if len(voiced) == 0:
        return audio
    return audio[max(0, voiced[0] - 240) : voiced[-1] + 1200]


def wav_bytes(audio: np.ndarray, rate: int = TTS_SAMPLE_RATE) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(float_to_pcm16(audio))
    return buf.getvalue()


def home_icon(skin_dir: Path | None) -> bytes:
    """512x512 PNG for the home screen: the skin's idle picture on the page background, else the built-in cat icon."""
    from io import BytesIO

    from PIL import Image

    if skin_dir is None:
        return DEFAULT_ICON.read_bytes()
    idle = Path(skin_dir) / "idle.png"
    key = f"{idle}:{idle.stat().st_mtime if idle.is_file() else 0}"
    if key not in _icon_cache:
        if idle.is_file():
            art = Image.open(idle).convert("RGBA")
            # A full-body figure is tiny at icon size: keep the head and shoulders (upper part of the art)
            bbox = art.getbbox() or (0, 0, *art.size)
            x0, y0, x1, y1 = bbox
            art = art.crop((x0, y0, x1, y0 + int((y1 - y0) * 0.62)))
            art.thumbnail((460, 460))
            canvas = Image.new("RGBA", (512, 512), ICON_BG)
            canvas.paste(art, ((512 - art.size[0]) // 2, (512 - art.size[1]) // 2 + 8), art)
            buf = BytesIO()
            canvas.save(buf, "PNG")
            _icon_cache[key] = buf.getvalue()
        else:
            _icon_cache[key] = DEFAULT_ICON.read_bytes()
    return _icon_cache[key]


def create_app(
    engine: Engine | None = None, allowed_hosts: list[str] | None = None, skin_dir: Path | None = None
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or DEFAULT_ALLOWED_HOSTS)
    app.state.engine = engine
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    fixed_dir = Path(skin_dir) if skin_dir is not None else None  # tests pin one skin folder

    def current_dir() -> Path | None:
        return fixed_dir if fixed_dir is not None else config.SKIN_DIR

    def current_persona() -> dict:
        return config.resolve_persona(config.load_skin(current_dir()))

    def same_origin(headers) -> bool:
        origin = urlparse(headers.get("origin", "")).netloc
        return bool(origin) and origin == headers.get("host")

    # Private artwork lives in the data directory, never in the repo
    @app.get("/skin/{name}")
    def skin_file(name: str):
        path = safe_skin_file(current_dir(), name)
        return FileResponse(path) if path else Response(status_code=404)

    @app.get("/skin.json")
    def skin_json():
        return skin_manifest(current_dir(), None if fixed_dir is not None else config.SKIN_ID)

    @app.get("/skins.json")
    def skins_json():
        skins = [] if fixed_dir is not None else config.list_skins(active=config.SKIN_ID)
        return {
            "active": None if fixed_dir is not None else config.SKIN_ID,
            "skins": [
                {"id": sk["id"], "name": sk["persona"]["name"],
                 "thumb": "/static/icon.png" if sk["dir"] is None else f"/skins/{sk['id']}/thumb.png"}
                for sk in skins
            ],
        }

    @app.get("/skins/{skin_id}/thumb.png")
    def skin_thumb(skin_id: str):
        if not any(sk["id"] == skin_id for sk in config.list_skins(active=config.SKIN_ID)):
            return Response(status_code=404)
        return Response(home_icon(config.skin_dir_for(skin_id)), media_type="image/png")

    @app.post("/skin")
    async def choose_skin(request: Request):
        if fixed_dir is not None or not same_origin(request.headers):
            return Response(status_code=403)
        try:
            skin_id = str((await request.json()).get("id", ""))
        except (ValueError, AttributeError):
            return Response(status_code=400)
        session = current_session()
        if session is not None and session.state != "idle":
            session.stop_session("skin_change")
        if not config.activate_skin(skin_id):
            return Response(status_code=404)
        engine = app.state.engine
        if engine is not None and hasattr(engine.tts, "set_voices"):
            def locked_apply():
                with ENGINE_LOCK:
                    apply_skin_voice(engine.tts)

            await asyncio.to_thread(locked_apply)
        return {"ok": True, "active": config.SKIN_ID}

    @app.get("/cue.wav")
    async def cue(lang: str = "zh"):
        lang = "en" if lang == "en" else "zh"
        skin_dir = current_dir()
        skin = config.load_skin(skin_dir)
        if skin_dir is None or not skin:
            return Response(status_code=404)  # the kitten: the page synthesizes its meow
        own = safe_skin_file(skin_dir, skin.get("cue"))
        if own:
            return FileResponse(own)
        engine = app.state.engine
        if engine is None:
            return Response(status_code=503)
        sound = config.resolve_persona(skin)["sound"][lang]
        key = (str(skin_dir), lang, sound, getattr(engine.tts, "voice_path", {}).get(lang), getattr(engine.tts, "speed", 1.0),
               getattr(engine.tts, "catch_version", 0))
        if key not in _cue_cache:
            def synth():
                with ENGINE_LOCK:
                    return engine.tts.synthesize(sound.capitalize() + "!", lang)

            _cue_cache[key] = wav_bytes(trim_cue(await asyncio.to_thread(synth)))
        return Response(_cue_cache[key], media_type="audio/wav")

    @app.middleware("http")
    async def no_cache(request, call_next):
        # Safari keeps old copies of home-screen web apps; make every response revalidate
        # (StaticFiles still answers 304 via ETag, so this stays cheap).
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/")
    def index():
        # The tab title and home-screen name are the pet's English name (default "Curiosity Buddy")
        app_name = current_persona()["name"]["en"]
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("{{APP_NAME}}", app_name)
        return HTMLResponse(html)

    @app.get("/manifest.webmanifest")
    def manifest():
        app_name = current_persona()["name"]["en"]
        return Response(
            json.dumps({
                "name": app_name, "short_name": app_name, "start_url": "/", "display": "standalone",
                "background_color": "#fdf6ec", "theme_color": "#fdf6ec", "orientation": "any",
                "icons": [{"src": "/apple-touch-icon.png", "sizes": "512x512", "type": "image/png"}],
            }),
            media_type="application/manifest+json",
        )

    @app.get("/apple-touch-icon.png")
    def touch_icon():
        return Response(home_icon(current_dir()), media_type="image/png")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        global _current
        if not same_origin(ws.headers):
            await ws.close(code=1008)
            return
        if app.state.engine is None:
            app.state.engine = await asyncio.to_thread(load_engine)
        await ws.accept()

        session = Session(app.state.engine, asyncio.get_running_loop())
        _current = session  # Only one child uses it; a new connection (e.g. a page refresh) replaces the old one
        session.send({"type": "state", "state": "listening"})

        async def sender():
            while True:
                item = await session.outbox.get()
                if isinstance(item, bytes):
                    await ws.send_bytes(item)
                else:
                    await ws.send_text(json.dumps(item, ensure_ascii=False))

        send_task = asyncio.create_task(sender())
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                if m.get("bytes") is not None:
                    session.on_audio(m["bytes"])
                elif m.get("text") is not None:
                    try:
                        session.on_message(json.loads(m["text"]))
                    except json.JSONDecodeError:
                        pass
        except WebSocketDisconnect:
            pass
        finally:
            if session.task:
                await asyncio.gather(session.task, return_exceptions=True)
            # Send the remaining messages before closing
            while not session.outbox.empty():
                await asyncio.sleep(0.01)
            send_task.cancel()
            if session.state != "idle":
                session.stop_session("disconnect")

    return app


def main():
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="Curiosity Pet iPad web service")
    ap.add_argument("--port", type=int, default=config.SERVER_PORT)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print("Loading models...")
    engine = load_engine()
    app = create_app(engine)

    from curiosity_pet.watch_api import WATCH_PORT, create_watch_app

    # Both listen on localhost only and share the loaded models: tailscale serve forwards the iPad port
    # (tailnet only); tailscale funnel publishes the watch port, which has the watch endpoints and nothing else
    servers = [
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")),
        uvicorn.Server(uvicorn.Config(create_watch_app(engine), host="127.0.0.1", port=WATCH_PORT, log_level="warning")),
    ]

    async def serve_all():
        await asyncio.gather(*(s.serve() for s in servers))

    asyncio.run(serve_all())


if __name__ == "__main__":
    main()
