"""Command-line voice loop (stage 1).

    uv run pet                  # microphone, ends automatically when speech stops (VAD)
    uv run pet --ptt            # push-to-talk fallback: Enter to start, Enter again to stop
    uv run pet --wav q1.wav     # use a recording instead of the microphone
    uv run pet --text           # type the question, tests generation and synthesis only
    uv run pet --no-play        # no playback (for evals)

Say goodbye ("再见") or press Ctrl+C to finish.
"""

import argparse
import queue
import sys

import numpy as np

from curiosity_pet import config
from curiosity_pet.vad import CHUNK, UtteranceDetector, chunks



def print_turn(turn):
    if turn.unavailable:
        print("  [本地模型不可用]")
    ms = lambda v: "-" if v is None else f"{v:.2f}s"  # noqa: E731
    print(
        f"  [{turn.lang}] 识别 {ms(turn.asr_s)} | 首字 {ms(turn.first_token_s)} | "
        f"首句 {ms(turn.first_sentence_s)} | 开口 {ms(turn.first_audio_s)}"
    )


def load_audio_16k(path):
    from mlx_audio.stt.utils import load_audio

    audio = load_audio(path, sr=config.MIC_SAMPLE_RATE)
    return np.array(audio, dtype=np.float32)


def mic_utterances(detector):
    import sounddevice as sd

    if not any(d["max_input_channels"] > 0 for d in sd.query_devices()):
        sys.exit("没有找到麦克风。Mac mini 没有内置麦克风,请接 USB 麦克风或耳机,或用 --wav / --text。")
    q: queue.Queue = queue.Queue()
    with sd.InputStream(
        samplerate=config.MIC_SAMPLE_RATE,
        channels=1,
        blocksize=CHUNK,
        dtype="float32",
        callback=lambda data, *_: q.put(data[:, 0].copy()),
    ):
        print("我在听,说吧...")
        while True:
            utterance = detector.feed(q.get())
            if utterance is not None:
                yield utterance
                # During an answer the microphone picks up the pet's own voice, so clear the backlog before listening again
                while not q.empty():
                    q.get_nowait()
                detector.reset()
                print("我在听...")


def ptt_utterances():
    import sounddevice as sd

    while True:
        input("按回车开始说话...")
        frames = []
        with sd.InputStream(
            samplerate=config.MIC_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=lambda data, *_: frames.append(data[:, 0].copy()),
        ):
            input("说完按回车...")
        if frames:
            yield np.concatenate(frames)


def wav_utterances(paths, detector):
    """Feed a recording to the VAD as if it were a microphone stream, padding silence at the end to simulate real sentence detection."""
    for p in paths:
        audio = load_audio_16k(p)
        tail = np.zeros(int(2 * config.MIC_SAMPLE_RATE), dtype=np.float32)
        detector.reset()
        for chunk in chunks(np.concatenate([audio, tail])):
            utterance = detector.feed(chunk)
            if utterance is not None:
                print(f"\n[{p}]")
                yield utterance
                break
        else:
            print(f"\n[{p}] 没有检测到说话")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Curiosity Pet: command-line voice loop")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ptt", action="store_true", help="push-to-talk (Enter to start/stop)")
    src.add_argument("--wav", nargs="+", help="use recording files instead of the microphone")
    src.add_argument("--text", action="store_true", help="type the question")
    ap.add_argument("--no-play", action="store_true", help="no playback")
    args = ap.parse_args(argv)

    from curiosity_pet.audio import Player
    from curiosity_pet.pipeline import Pet, is_goodbye
    from curiosity_pet.tts import SAMPLE_RATE, TTS

    print("加载模型...")
    tts = TTS()
    asr = None
    if not args.text:
        from curiosity_pet.asr import ASR

        asr = ASR()
    player = Player(sample_rate=SAMPLE_RATE, enabled=not args.no_play)
    pet = Pet(
        asr,
        tts,
        player,
        on_sentence=lambda s: print(f"  宠物: {s}"),
        on_question=lambda q, lang: print(f"  孩子: {q}"),
    )

    def run(turn_fn):
        turn = turn_fn()
        player.wait()
        print_turn(turn)
        return turn

    try:
        if args.text:
            while True:
                q = input("\n你: ").strip()
                if not q:
                    continue
                turn = run(lambda: pet.answer(q))
                if is_goodbye(q):
                    break
            return
        if args.wav:
            source = wav_utterances(args.wav, UtteranceDetector())
        elif args.ptt:
            source = ptt_utterances()
        else:
            source = mic_utterances(UtteranceDetector())
        for audio in source:
            turn = run(lambda a=audio: pet.handle_audio(a))
            if is_goodbye(turn.question):
                break
    except KeyboardInterrupt:
        print()
    finally:
        pet.end_session()
        print("下次见。")


if __name__ == "__main__":
    main()
