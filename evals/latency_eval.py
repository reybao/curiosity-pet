"""阶段 1 验收:孩子说完到宠物开口是否在 3 秒内。

本机没有麦克风,所以用 Kokoro 把虚构问题合成为语音,当作录音喂进完整流程:
VAD 断句 -> ASR -> 语言判定 -> 流式生成 -> 逐句 TTS。不放音,只计时。

开口延迟 = VAD 等待(说完到判定结束,含 0.8 秒静音阈值)+ 处理时间(判定结束到第一句音频合成完)。
局限:合成语音是成人音色、发音标准,比孩子的真实录音容易识别;孩子录音的数字要等阶段 0 的录音。

用法:
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
    # 去掉空白和所有标点(含全角),只比文字
    return "".join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith("P")).lower()


def vad_wait(detector, speech):
    """把语音加 2 秒静音按块喂入,返回(判定结束时刻 - 语音结束时刻, 截出的整句)。"""
    sr = config.MIC_SAMPLE_RATE
    # 去掉合成音频首尾的静音,得到真实的"说完"时刻
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

    pet.answer("你好")  # 预热,不计入
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

    print("| 类型 | 问题 | 识别结果 | VAD 等待 | 识别 | 首字 | 首句 | 首句合成 | 开口(处理) | 开口(总) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['kind']} | {r['question']} | {r['heard']} | {r['vad_wait_s']:.2f} | "
            f"{r['asr_s']:.2f} | {r['first_token_s']:.2f} | {r['first_sentence_s']:.2f} | "
            f"{r['tts_first_s']:.2f} | {r['first_audio_s']:.2f} | {r['speak_s']:.2f} |"
        )
    speak = [r["speak_s"] for r in rows]
    print(
        f"\n开口(总)中位数 {statistics.median(speak):.2f}s,最大 {max(speak):.2f}s,"
        f"{sum(s <= BUDGET_S for s in speak)}/{len(speak)} 次在 {BUDGET_S:.0f} 秒内;"
        f"识别完全正确 {sum(r['asr_exact'] for r in rows)}/{len(rows)}"
    )
    import mlx.core as mx

    print(f"MLX 峰值内存(ASR + TTS){mx.get_peak_memory() / 1e9:.2f} GB")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
