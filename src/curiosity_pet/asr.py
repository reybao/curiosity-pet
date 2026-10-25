"""Speech recognition: Qwen3-ASR-0.6B 4-bit (mlx-audio), detecting the language of each utterance automatically."""

import numpy as np

from curiosity_pet import config
from curiosity_pet.lang import from_asr_label


class ASR:
    def __init__(self, model: str = config.ASR_MODEL):
        from mlx_audio.stt.utils import load

        self.model = load(model)

    def transcribe(self, audio: np.ndarray) -> tuple[str, str | None]:
        """Takes 16 kHz float32 mono audio, returns (text, zh/en/None)."""
        result = self.model.generate(audio.astype(np.float32))
        label = result.language
        if isinstance(label, list):
            label = label[0] if label else None
        return result.text.strip(), from_asr_label(label)
