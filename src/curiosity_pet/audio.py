"""Playback: a background thread plays in order, so the previous sentence keeps playing while the next is synthesized."""

import queue
import threading
import time

import numpy as np


def thinking_cue(sample_rate: int = 24000) -> np.ndarray:
    """Local cue sound played right after the VAD decides the child is done: a short "meow", about 0.35 s, same idea as playCue on the iPad side.

    Pitch 520 -> 820 -> 600 Hz, approximating a sawtooth wave with a few harmonics; no recorded material is used.
    """
    n = int(0.35 * sample_rate)
    t = np.arange(n) / sample_rate
    f = np.interp(t, [0, 0.12, 0.35], [520, 820, 600])
    phase = 2 * np.pi * np.cumsum(f) / sample_rate
    wave = sum(np.sin(k * phase) / k for k in range(1, 6))
    env = np.interp(t, [0, 0.04, 0.2, 0.35], [0, 1, 1, 0])
    return (0.12 * wave * env).astype(np.float32)


class Player:
    def __init__(self, sample_rate: int = 24000, enabled: bool = True):
        self.sr = sample_rate
        self.enabled = enabled
        self.q: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def play(self, audio: np.ndarray, text: str | None = None, on_start=None):
        self.q.put((audio, on_start))

    def wait(self):
        self.q.join()

    def _run(self):
        import sounddevice as sd

        while True:
            audio, on_start = self.q.get()
            try:
                if on_start:
                    on_start()
                if self.enabled and len(audio):
                    sd.play(audio, self.sr)
                    sd.wait()
                elif len(audio):
                    time.sleep(0)  # When not playing, take no time; only preserve callback order
            finally:
                self.q.task_done()
