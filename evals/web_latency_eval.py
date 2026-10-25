"""Stage 2: speak latency through the web service (WebSocket).

Simulates an iPad: sends synthesized fictional questions to the service at real-time speed (512 samples every 32 ms), padded with silence at the end,
and records the time from "last speech sample sent" to "first sentence audio received", including the server-side VAD wait.
Excludes the Wi-Fi and Tailscale transport between the iPad and the Mac (typically a few to tens of milliseconds on a LAN).

Start the server first: uv run pet-server
Usage:    uv run python evals/web_latency_eval.py [--url ws://127.0.0.1:8730/ws]
"""

import argparse
import asyncio
import json
import statistics
import time

import numpy as np
import websockets

QUESTIONS = [
    ("zh", "为什么月亮白天也会出现?"),
    ("zh", "蚂蚁为什么排队走路?"),
    ("zh", "彩虹是怎么来的?"),
    ("en", "Why is the sky blue?"),
    ("en", "How do fish breathe under water?"),
    ("en", "Where does rain come from?"),
    ("zh", "恐龙为什么会 extinct 呢?"),
    ("en", "Why do 熊猫 eat bamboo all day?"),
]
CHUNK = 512
SR = 16000
BUDGET_S = 3.0


def synthesize_questions():
    from curiosity_pet.tts import TTS, trim_silence

    tts = TTS()
    out = []
    for lang, q in QUESTIONS:
        a = trim_silence(tts.synthesize(q, lang))
        a16 = np.interp(np.linspace(0, len(a) - 1, int(len(a) * SR / 24000)), np.arange(len(a)), a)
        out.append((q, (np.clip(a16, -1, 1) * 32767).astype("<i2")))
    return out


async def one_turn(ws, pcm):
    """Send and receive in parallel: sending runs at real-time speed and stops as soon as the server decides the utterance is over (state=thinking)."""
    stream = np.concatenate([pcm, np.zeros(int(1.5 * SR), dtype="<i2")])
    t = {"speech_end": None, "first_audio": None}
    thinking = asyncio.Event()
    heard = {"text": ""}

    async def sender():
        t0 = time.perf_counter()
        for i in range(0, len(stream), CHUNK):
            if thinking.is_set():
                return
            await asyncio.sleep(max(0, t0 + i / SR - time.perf_counter()))
            await ws.send(stream[i : i + CHUNK].tobytes())
            if t["speech_end"] is None and i + CHUNK >= len(pcm):
                t["speech_end"] = time.perf_counter()

    async def receiver():
        while True:
            m = await ws.recv()
            if isinstance(m, bytes):
                t["first_audio"] = t["first_audio"] or time.perf_counter()
                continue
            msg = json.loads(m)
            if msg == {"type": "state", "state": "thinking"}:
                thinking.set()
            elif msg["type"] == "heard":
                heard["text"] = msg["text"]
            elif msg["type"] == "done":
                return

    await asyncio.gather(sender(), receiver())
    await ws.send(json.dumps({"type": "playback_done"}))
    while json.loads(await ws.recv()) != {"type": "state", "state": "listening"}:
        pass
    latency = t["first_audio"] - t["speech_end"] if t["first_audio"] else None
    return heard["text"], latency


async def main_async(url):
    clips = synthesize_questions()
    rows = []
    origin = "http://" + url.split("//", 1)[1].split("/", 1)[0]
    async with websockets.connect(url, origin=origin, max_size=None) as ws:
        assert json.loads(await ws.recv())["state"] == "listening"
        for runs in range(2):
            for q, pcm in clips:
                heard, latency = await one_turn(ws, pcm)
                rows.append((q, heard, latency))
                print(f"{latency:5.2f}s  {q}  ->  {heard}")
    lat = [r[2] for r in rows if r[2] is not None]
    print(
        f"\nSpeak (end of speech to first sentence audio) median {statistics.median(lat):.2f}s,max {max(lat):.2f}s,"
        f"{sum(x <= BUDGET_S for x in lat)}/{len(lat)} runs within {BUDGET_S:.0f} s"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8730/ws")
    asyncio.run(main_async(ap.parse_args().url))


if __name__ == "__main__":
    main()
