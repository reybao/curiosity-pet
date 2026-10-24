"""语音识别:Qwen3-ASR-0.6B 4-bit(mlx-audio),每句自动判定语言。"""

import numpy as np

from curiosity_pet import config
from curiosity_pet.lang import from_asr_label


class ASR:
    def __init__(self, model: str = config.ASR_MODEL):
        from mlx_audio.stt.utils import load

        self.model = load(model)

    def transcribe(self, audio: np.ndarray) -> tuple[str, str | None]:
        """输入 16kHz float32 单声道,返回(文字, zh/en/None)。"""
        result = self.model.generate(audio.astype(np.float32))
        label = result.language
        if isinstance(label, list):
            label = label[0] if label else None
        return result.text.strip(), from_asr_label(label)
