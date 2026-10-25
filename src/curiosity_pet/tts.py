"""Speech synthesis: Kokoro-82M v1.1-zh (mlx-audio), switching between Chinese and English voices by answer language.

Weights are converted locally from the official repo by scripts/convert_kokoro.py.
Chinese in v1.1-zh needs misaki's 1.1 G2P, while mlx-audio builds the 1.0 one by default, so it is replaced here.
"""

import re

import numpy as np

from curiosity_pet import config
from curiosity_pet.pronounce import fix, fix_en

SAMPLE_RATE = 24000
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
JOIN_GAP_S = 0.06
LANG_CODE = {"zh": "z", "en": "a"}


class TTS:
    def __init__(self, model_dir=config.TTS_MODEL_DIR, voices=config.TTS_VOICE):
        from misaki import en, zh
        from mlx_audio.tts.utils import load_model

        self.model = load_model(str(model_dir))
        self.model_dir = model_dir
        self.speed = 1.0
        self.catch_re: dict = {}  # per language: the catchphrase to replace in speech
        self.catch_audio: dict = {}  # per language: the audio that replaces it (a recorded clip, or a pitched voice)
        self.catch_version = 0
        self.set_voices(voices)
        # English words inside Chinese answers go through this G2P; unknown names (Vegeta, Bulma) need the espeak
        # fallback, which the English pipeline already uses, or they are silent
        try:
            from misaki import espeak

            fallback = espeak.EspeakFallback(british=False)
        except Exception:  # noqa: BLE001  espeak missing: unknown words stay silent, as before
            fallback = None
        en_g2p = en.G2P(trf=False, british=False, fallback=fallback)
        zh_pipeline = self.model._get_pipeline("z")
        zh_pipeline.g2p = zh.ZHG2P(version="1.1", en_callable=lambda s: en_g2p(fix_en(s))[0])

    def set_voices(self, voices: dict, speed: float = 1.0):
        """Voices per language (names of converted files in model_dir/voices) and speed; the active skin chooses them."""
        self.voice_path = {
            lang: str(self.model_dir / "voices" / f"{name}.safetensors") for lang, name in voices.items()
        }
        self.speed = speed

    def set_catchphrase(self, words: dict | None = None, audio: dict | None = None):
        """Speak the character's catchphrase ("皮卡", "Pika") with a sound of its own instead of the TTS voice."""
        from curiosity_pet.textclean import sound_pattern

        audio = audio or {}
        self.catch_re = {lang: sound_pattern([w]) for lang, w in (words or {}).items() if w and lang in audio}
        self.catch_audio = audio
        self.catch_version += 1

    def synthesize(self, text: str, lang: str, speed: float | None = None) -> np.ndarray:
        pattern = self.catch_re.get(lang)
        m = pattern.search(text) if pattern else None
        if m is None:
            return self.synthesize_voice(text, lang, speed)
        gap = np.zeros(int(0.08 * SAMPLE_RATE), dtype=np.float32)
        parts = []
        before, after = text[: m.start()].strip(), text[m.end():].lstrip(" ,，、!！.。~～").strip()
        if re.search(r"\w", before):
            parts += [trim_silence(self.synthesize_voice(before, lang, speed)), gap]
        parts.append(self.catch_audio[lang])
        if re.search(r"\w", after):
            parts += [gap, trim_silence(self.synthesize_voice(after, lang, speed))]
        return np.concatenate(parts).astype(np.float32)

    def synthesize_voice(self, text: str, lang: str, speed: float | None = None) -> np.ndarray:
        speed = self.speed if speed is None else speed
        segs = segments(text, lang)
        parts = []
        for seg_lang, seg in segs:
            audio = np.concatenate([
                np.array(r.audio, dtype=np.float32)
                for r in self.model.generate(
                    text=fix(seg, seg_lang), voice=self.voice_path[seg_lang], lang_code=LANG_CODE[seg_lang], speed=speed
                )
            ] or [np.zeros(0, dtype=np.float32)])
            # Kokoro adds silence at the start and end of each segment, which causes an audible pause when segments are joined (measured: enough for the VAD to think the speaker finished), so trim before joining
            parts.append(trim_silence(audio) if len(segs) > 1 else audio)
        if len(parts) == 1:
            return parts[0]
        gap = np.zeros(int(JOIN_GAP_S * SAMPLE_RATE), dtype=np.float32)
        return np.concatenate([x for p in parts for x in (p, gap)][:-1])


def pitch_up(audio: np.ndarray, factor: float) -> np.ndarray:
    """Higher and shorter, like a sped-up tape (a squeaky, Pikachu-like "pika" from a normal voice)."""
    if factor == 1.0 or len(audio) < 2:
        return audio
    positions = np.arange(0, len(audio) - 1, factor)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def load_clip(path, rate: int = SAMPLE_RATE) -> np.ndarray:
    """A short recorded sound (wav, mp3, m4a ...) as mono float32 at the TTS rate, trimmed and normalized."""
    import subprocess
    import tempfile
    from pathlib import Path

    import soundfile as sf

    path = Path(path)
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001  formats libsndfile cannot read (m4a): convert with macOS afconvert
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "clip.wav"
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(path), str(wav)], check=True, capture_output=True)
            data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != rate:
        mono = np.interp(np.arange(0, len(mono), sr / rate), np.arange(len(mono)), mono).astype(np.float32)
    mono = trim_silence(mono, threshold=0.02)[: rate * 3]  # at most 3 seconds
    peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
    return (mono * (0.8 / peak)).astype(np.float32) if peak > 0 else mono


def trim_silence(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    voiced = np.flatnonzero(np.abs(audio) > threshold)
    if len(voiced) == 0:
        return audio[:0]
    return audio[voiced[0] : voiced[-1] + 1]


def segments(text: str, lang: str) -> list[tuple[str, str]]:
    """Chinese words inside an English answer go to the Chinese voice, otherwise the English G2P reads them as "Chinese letter".

    Chinese answers need no splitting: the v1.1 Chinese G2P handles English itself.
    """
    if lang != "en" or not CJK_RUN.search(text):
        return [(lang, text)]
    out = []
    pos = 0
    for m in CJK_RUN.finditer(text):
        before = text[pos : m.start()].strip()
        if before:
            out.append(("en", before))
        out.append(("zh", m.group()))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        out.append(("en", tail))
    return out
