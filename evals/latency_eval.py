"""Stage 1 acceptance: does the pet start speaking within 3 seconds after the child finishes?

This machine has no microphone, so fictional questions are synthesized with Kokoro and fed through the full pipeline as recordings:
VAD segmentation -> ASR -> language detection -> streaming generation -> per-sentence TTS. No playback, timing only.

Speak latency = VAD wait (end of speech to end-of-utterance decision, including the 0.8 s silence threshold) + processing time (decision to first sentence audio synthesized).
Limitation: synthetic speech has an adult voice and standard pronunciation, so it is easier to recognize than real children's recordings; numbers for children's recordings must wait for the stage 0 recordings.

Usage:
    uv run python evals/latency_eval.py --json evals/results/2026-10-23-latency-raw.json
"""

import argparse
import json
import statistics
import unicodedata

import numpy as np

from curiosity_pet import config
from curiosity_pet.asr import ASR
from curiosity_pet.audio import Player
from curiosity_pet.pipeline import Pet
from curiosity_pet.tts import SAMPLE_RATE as TTS_SR
from curiosity_pet.tts import TTS
from curiosity_pet.vad import CHUNK, UtteranceDetector, chunks

QUESTIONS = [
    ("zh", "为什么月亮白天也会出现?"),
    ("zh", "蚂蚁为什么排队走路?"),
    ("zh", "彩虹是怎么来的?"),
    ("en", "Why is the sky blue?"),
    ("en", "How do fish breathe under water?"),
    ("en", "Where does rain come from?"),
    ("mix", "恐龙为什么会 extinct 呢?"),
    ("mix", "Why do 熊猫 eat bamboo all day?"),
]
BUDGET_S = 3.0


def resample(audio, src, dst):
    n = int(len(audio) * dst / src)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(
        np.float32
    )


def norm(s):
    # strip whitespace and all punctuation (including full-width), compare text only
    return "".join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith("P")).lower()


def vad_wait(detector, speech):
    """Feed the speech plus 2 s of silence in chunks; return (end-of-utterance decision time - speech end time, the segmented utterance)."""
    sr = config.MIC_SAMPLE_RATE
    # Trim leading and trailing silence from the synthesized audio to get the true "finished speaking" moment
    voiced = np.flatnonzero(np.abs(speech) > 0.01)
    speech = speech[voiced[0] : voiced[-1] + 1]
    stream = np.concatenate([speech, np.zeros(2 * sr, dtype=np.float32)])
    detector.reset()
    for i, chunk in enumerate(chunks(stream)):
        utt = detector.feed(chunk)
        if utt is not None:
            return (i + 1) * CHUNK / sr - len(speech) / sr, utt
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--json")
    args = ap.parse_args()

    tts, asr = TTS(), ASR()
    pet = Pet(asr, tts, Player(sample_rate=TTS_SR, enabled=False))
    detector = UtteranceDetector()

    clips = []
    for kind, q in QUESTIONS:
        lang = "en" if kind == "en" or q[0].isascii() else "zh"
        clips.append((kind, q, resample(tts.synthesize(q, lang), TTS_SR, config.MIC_SAMPLE_RATE)))

    pet.answer("你好")  # warm-up, not counted
    pet.end_session()

    rows = []
    for kind, q, audio in clips:
        for _ in range(args.runs):
            wait, utt = vad_wait(detector, audio)
            turn = pet.handle_audio(utt)
            pet.end_session()
            rows.append(
                {
                    "kind": kind,
                    "question": q,
                    "heard": turn.question,
                    "asr_exact": norm(turn.question) == norm(q),
                    "lang": turn.lang,
                    "vad_wait_s": wait,
                    "asr_s": turn.asr_s,
                    "first_token_s": turn.first_token_s,
                    "first_sentence_s": turn.first_sentence_s,
                    "first_audio_s": turn.first_audio_s,
                    "tts_first_s": turn.tts_s[0] if turn.tts_s else None,
                    "first_tts_text": turn.sentences[0] if turn.sentences else "",
                    "speak_s": wait + turn.first_audio_s,
                    "answer": turn.answer,
                }
            )

    print("| Type | Question | Recognized | VAD wait | ASR | First token | First sentence | First sentence TTS | Speak (processing) | Speak (total) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['kind']} | {r['question']} | {r['heard']} | {r['vad_wait_s']:.2f} | "
            f"{r['asr_s']:.2f} | {r['first_token_s']:.2f} | {r['first_sentence_s']:.2f} | "
            f"{r['tts_first_s']:.2f} | {r['first_audio_s']:.2f} | {r['speak_s']:.2f} |"
        )
    speak = [r["speak_s"] for r in rows]
    print(
        f"\nSpeak (total) median {statistics.median(speak):.2f}s,max {max(speak):.2f}s,"
        f"{sum(s <= BUDGET_S for s in speak)}/{len(speak)} runs within {BUDGET_S:.0f} s; "
        f"ASR exact {sum(r['asr_exact'] for r in rows)}/{len(rows)}"
    )
    import mlx.core as mx

    print(f"MLX peak memory (ASR + TTS) {mx.get_peak_memory() / 1e9:.2f} GB")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
