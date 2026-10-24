"""iPad 网页服务(阶段 2):FastAPI 托管静态页面,WebSocket 传语音。

只监听 127.0.0.1,由 `tailscale serve` 提供 HTTPS 并转发,未登录 Tailscale 的设备访问不到。
另外校验 Host(防 DNS 重绑定)和 WebSocket 的 Origin(防其他网页连进来)。

协议(/ws):
  iPad -> 服务:二进制帧 = 16kHz 单声道 PCM16;JSON:
      {"type": "text", "text": ...}        打字提问(调试用)
      {"type": "ptt_start"} / {"type": "ptt_end"}   按住说话兜底
      {"type": "playback_done"}             iPad 播完,回到在听
      {"type": "end_session"}               结束这次探索,清空会话历史
  服务 -> iPad:JSON:
      {"type": "state", "state": "listening|thinking|speaking"}
      {"type": "heard", "text": ..., "lang": ...}
      {"type": "sentence", "id": n, "text": ...}   紧跟一个二进制帧:4 字节编号 + 24kHz PCM16
      {"type": "done", "timings": {...}, "unavailable": bool}
      {"type": "session_ended"}

半双工:宠物在想和在说时不听,收到的音频直接丢弃,避免把自己的声音当成提问。
不记录孩子的话:日志只写耗时,不写问题和回答文字(launchd 会把输出写进日志文件,硬性约束第 2 条)。
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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from curiosity_pet import config
from curiosity_pet.pipeline import Pet
from curiosity_pet.vad import CHUNK

log = logging.getLogger("curiosity_pet.server")

WEB_DIR = Path(__file__).parent / "web"
DEFAULT_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "*.ts.net"]
TTS_SAMPLE_RATE = 24000
TIMING_KEYS = ("asr_s", "first_token_s", "first_sentence_s", "first_audio_s", "total_s")

# MLX 模型不是线程安全的,同一时间只跑一轮
ENGINE_LOCK = threading.Lock()
_current: "Session | None" = None


@dataclass
class Engine:
    asr: object
    tts: object
    make_detector: Callable[[], object]
    researcher: object | None = None  # 联网查询,None 表示不联网


def load_engine() -> Engine:
    from curiosity_pet.asr import ASR
    from curiosity_pet.tts import TTS
    from curiosity_pet.vad import UtteranceDetector

    asr, tts = ASR(), TTS()
    # 预热:Kokoro 每种语言的管道第一次用时才建(实测首个英文回答开口慢 1.5 秒),ASR 第一次也慢
    tts.synthesize("你好。", "zh")
    tts.synthesize("Hello.", "en")
    asr.transcribe(np.zeros(16000, dtype=np.float32))
    from curiosity_pet.lookup import Researcher
    from curiosity_pet.store import Store

    researcher = Researcher(store=Store())
    if researcher.enabled and not researcher.contact:
        log.warning("联网查询已开启但没有设置 PET_WIKI_CONTACT(维基百科要求的联系方式),暂不联网")
    return Engine(asr=asr, tts=tts, make_detector=UtteranceDetector, researcher=researcher)


def pcm16_to_float(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class WebPlayer:
    """替代本机放音:把每句音频和文字发给 iPad,由 iPad 播放并高亮。"""

    def __init__(self, send):
        self.send = send
        self.next_id = 0
        self.started = False

    def new_turn(self):
        self.started = False

    def play(self, audio: np.ndarray, text: str | None = None, on_start=None):
        if text is None:
            return  # 提示音由 iPad 本地播放
        if not self.started:
            self.started = True
            self.send({"type": "state", "state": "speaking"})
        sid = self.next_id
        self.next_id += 1
        self.send({"type": "sentence", "id": sid, "text": text})
        self.send(struct.pack("<I", sid) + float_to_pcm16(audio))


class Session:
    def __init__(self, engine: Engine, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.player = WebPlayer(self._send_threadsafe)
        self.pet = Pet(
            engine.asr,
            engine.tts,
            self.player,
            on_question=lambda q, lang: self._send_threadsafe(
                {"type": "heard", "text": q, "lang": lang}
            ),
            researcher=engine.researcher,
        )
        self.detector = engine.make_detector()
        self.state = "listening"
        self.pending = np.zeros(0, dtype=np.float32)
        self.ptt_frames: list[np.ndarray] | None = None
        self.task: asyncio.Task | None = None

    def _send_threadsafe(self, item):
        self.loop.call_soon_threadsafe(self.outbox.put_nowait, item)

    def send(self, item):
        self.outbox.put_nowait(item)

    def set_state(self, state):
        self.state = state
        self.send({"type": "state", "state": state})

    def on_audio(self, raw: bytes):
        if self.state != "listening":
            return
        audio = pcm16_to_float(raw)
        if self.ptt_frames is not None:
            self.ptt_frames.append(audio)
            return
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
        elif kind == "ptt_start" and self.state == "listening":
            self.ptt_frames = []
        elif kind == "ptt_end" and self.ptt_frames is not None:
            frames, self.ptt_frames = self.ptt_frames, None
            if frames:
                self.start_turn("audio", np.concatenate(frames))
        elif kind == "playback_done" and self.state == "speaking":
            self.detector.reset()
            self.set_state("listening")
        elif kind == "end_session":
            # 说到一半结束也直接回到在听;iPad 端会停掉剩下的音频
            self.ptt_frames = None
            if self.state == "speaking":
                self.state = "listening"
            self.pet.end_session()
            self.send({"type": "session_ended"})

    def start_turn(self, kind, payload):
        self.set_state("thinking")
        self.player.new_turn()
        self.task = asyncio.create_task(self._turn(kind, payload))

    async def _turn(self, kind, payload):
        def run():
            with ENGINE_LOCK:
                if kind == "audio":
                    return self.pet.handle_audio(payload, play_cue=False)
                return self.pet.answer(payload)

        turn = await asyncio.to_thread(run)
        # 线程里排队的消息都在 outbox 中,done 排在它们之后
        timings = {k: getattr(turn, k) for k in TIMING_KEYS}
        # 只记耗时、语言、是否联网及原因,不记问题、搜索词和回答
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
        if turn.sentences:
            self.state = "speaking"  # 等 iPad 播完发 playback_done
        else:
            self.set_state("listening")


def current_session() -> "Session | None":
    return _current


def create_app(engine: Engine | None = None, allowed_hosts: list[str] | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or DEFAULT_ALLOWED_HOSTS)
    app.state.engine = engine
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        global _current
        origin = urlparse(ws.headers.get("origin", "")).netloc
        if not origin or origin != ws.headers.get("host"):
            await ws.close(code=1008)
            return
        if app.state.engine is None:
            app.state.engine = await asyncio.to_thread(load_engine)
        await ws.accept()

        session = Session(app.state.engine, asyncio.get_running_loop())
        _current = session  # 只有一个孩子用;新连接(如刷新页面)接替旧的
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
            # 把剩下的消息发完再关
            while not session.outbox.empty():
                await asyncio.sleep(0.01)
            send_task.cancel()
            session.pet.end_session()

    return app


def main():
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="好奇心伙伴 iPad 网页服务")
    ap.add_argument("--port", type=int, default=config.SERVER_PORT)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print("加载模型...")
    app = create_app(load_engine())
    # 只监听本机,由 tailscale serve 转发
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
