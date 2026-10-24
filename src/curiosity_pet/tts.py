"""语音合成:Kokoro-82M v1.1-zh(mlx-audio),按回答语言切换中文或英文音色。

权重由 scripts/convert_kokoro.py 从官方仓库本机转换。
v1.1-zh 的中文需要 misaki 的 1.1 版 G2P,mlx-audio 默认建的是 1.0 版,这里替换掉。
"""

import re

import numpy as np

from curiosity_pet import config

SAMPLE_RATE = 24000
CJK_RUN = re.compile(r"[一-鿿]+")
JOIN_GAP_S = 0.06
LANG_CODE = {"zh": "z", "en": "a"}


class TTS:
    def __init__(self, model_dir=config.TTS_MODEL_DIR, voices=config.TTS_VOICE):
        from misaki import en, zh
        from mlx_audio.tts.utils import load_model

        self.model = load_model(str(model_dir))
        self.voice_path = {
            lang: str(model_dir / "voices" / f"{name}.safetensors") for lang, name in voices.items()
        }
        en_g2p = en.G2P(trf=False, british=False, fallback=None)
        zh_pipeline = self.model._get_pipeline("z")
        zh_pipeline.g2p = zh.ZHG2P(version="1.1", en_callable=lambda s: en_g2p(s)[0])

    def synthesize(self, text: str, lang: str, speed: float = 1.0) -> np.ndarray:
        segs = segments(text, lang)
        parts = []
        for seg_lang, seg in segs:
            audio = np.concatenate([
                np.array(r.audio, dtype=np.float32)
                for r in self.model.generate(
                    text=seg, voice=self.voice_path[seg_lang], lang_code=LANG_CODE[seg_lang], speed=speed
                )
            ] or [np.zeros(0, dtype=np.float32)])
            # Kokoro 每段首尾自带静音,多段拼接时会出现明显停顿(实测足以让 VAD 误判说完),裁掉再拼
            parts.append(trim_silence(audio) if len(segs) > 1 else audio)
        if len(parts) == 1:
            return parts[0]
        gap = np.zeros(int(JOIN_GAP_S * SAMPLE_RATE), dtype=np.float32)
        return np.concatenate([x for p in parts for x in (p, gap)][:-1])


def trim_silence(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    voiced = np.flatnonzero(np.abs(audio) > threshold)
    if len(voiced) == 0:
        return audio[:0]
    return audio[voiced[0] : voiced[-1] + 1]


def segments(text: str, lang: str) -> list[tuple[str, str]]:
    """英文回答里的中文词交给中文音色念,否则英文 G2P 会读成 "Chinese letter"。

    中文回答不用切:v1.1 中文 G2P 自带英文处理。
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
