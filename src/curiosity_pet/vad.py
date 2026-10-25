"""Sentence segmentation: Silero VAD detects where an utterance starts and ends.

Children pause a lot when speaking, so tune the silence threshold starting from 0.8 s (config.VAD_SILENCE_S).
Audio is fed in blocks of 512 samples (32 ms at 16 kHz).
"""

import numpy as np
import torch
from silero_vad import VADIterator, load_silero_vad

from curiosity_pet import config

CHUNK = 512
PRE_ROLL_S = 0.3  # audio kept from before the detected start, so the first word is not cut off
MAX_UTTERANCE_S = 30


class UtteranceDetector:
    def __init__(
        self,
        silence_s: float = config.VAD_SILENCE_S,
        threshold: float = config.VAD_THRESHOLD,
        sample_rate: int = config.MIC_SAMPLE_RATE,
    ):
        self.sr = sample_rate
        self.vad = VADIterator(
            load_silero_vad(),
            threshold=threshold,
            sampling_rate=sample_rate,
            min_silence_duration_ms=int(silence_s * 1000),
            speech_pad_ms=100,
        )
        self.pre_roll: list[np.ndarray] = []
        self.speech: list[np.ndarray] | None = None
        self.samples_seen = 0

    def reset(self):
        self.vad.reset_states()
        self.pre_roll = []
        self.speech = None

    @property
    def in_speech(self) -> bool:
        return self.speech is not None

    def feed(self, chunk: np.ndarray) -> np.ndarray | None:
        """Feed one block of audio; return the whole utterance (float32, 16 kHz) when it ends, otherwise None."""
        assert len(chunk) == CHUNK, len(chunk)
        self.samples_seen += CHUNK
        event = self.vad(torch.from_numpy(chunk.astype(np.float32)))

        if self.speech is None:
            self.pre_roll.append(chunk)
            max_pre = int(PRE_ROLL_S * self.sr / CHUNK)
            self.pre_roll = self.pre_roll[-max_pre:]
            if event and "start" in event:
                self.speech = list(self.pre_roll)
                self.pre_roll = []
            return None

        self.speech.append(chunk)
        too_long = len(self.speech) * CHUNK > MAX_UTTERANCE_S * self.sr
        if (event and "end" in event) or too_long:
            utterance = np.concatenate(self.speech)
            self.reset()
            return utterance
        return None


def chunks(audio: np.ndarray):
    """Split audio into the whole blocks the VAD needs, zero-padding a final partial block."""
    pad = (-len(audio)) % CHUNK
    audio = np.concatenate([audio, np.zeros(pad, dtype=np.float32)])
    for i in range(0, len(audio), CHUNK):
        yield audio[i : i + CHUNK]
