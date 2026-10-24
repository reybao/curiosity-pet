"""放音:后台线程按顺序播放,合成下一句时上一句照常在播。"""

import queue
import threading
import time

import numpy as np


def thinking_cue(sample_rate: int = 24000) -> np.ndarray:
    """VAD 判定说完后立即播放的本地提示音:短促的"喵呜",约 0.35 秒,与 iPad 端 playCue 相同思路。

    音高 520 -> 820 -> 600 Hz,用几个泛音近似锯齿波,不用任何录音素材。
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
                    time.sleep(0)  # 不放音时不占用时长,只保留回调顺序
            finally:
                self.q.task_done()
