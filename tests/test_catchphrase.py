"""The character's catchphrase spoken with a sound of its own (a recorded clip, or the voice pitched up),
so Pikachu's "皮卡" can sound like Pikachu. Tested without loading the speech model."""

import numpy as np
import soundfile as sf

from curiosity_pet.tts import TTS, load_clip, pitch_up


def fake_tts():
    t = TTS.__new__(TTS)  # skip loading the model
    t.catch_re, t.catch_audio, t.catch_version, t.speed = {}, {}, 0, 1.0
    t.said = []

    def voice(text, lang, speed=None):
        t.said.append(text)
        return np.full(100, 0.5, dtype=np.float32)

    t.synthesize_voice = voice
    return t


def test_catchphrase_is_replaced_by_its_sound():
    t = fake_tts()
    clip = np.full(7, -0.9, dtype=np.float32)
    t.set_catchphrase({"zh": "皮卡", "en": "pika"}, {"zh": clip, "en": clip})
    out = t.synthesize("皮卡,我去查一查!", "zh")
    assert t.said == ["我去查一查!"] and (out == -0.9).sum() == 7
    t.said.clear()
    t.synthesize("Pika! Let me look that up!", "en")
    assert t.said == ["Let me look that up!"]


def test_the_name_pikachu_is_not_touched():
    t = fake_tts()
    clip = np.zeros(5, dtype=np.float32)
    t.set_catchphrase({"zh": "皮卡", "en": "pika"}, {"zh": clip, "en": clip})
    t.synthesize("我是皮卡丘。", "zh")
    t.synthesize("I am Pikachu.", "en")
    assert t.said == ["我是皮卡丘。", "I am Pikachu."]


def test_no_catchphrase_sound_means_plain_voice():
    t = fake_tts()
    t.set_catchphrase()
    t.synthesize("皮卡,我去查一查!", "zh")
    assert t.said == ["皮卡,我去查一查!"]


def test_pitch_up_is_higher_and_shorter():
    sr = 24000
    tone = np.sin(2 * np.pi * 200 * np.arange(sr) / sr).astype(np.float32)
    up = pitch_up(tone, 1.5)
    assert abs(len(up) - sr / 1.5) < 2
    crossings = np.sum(np.diff(np.sign(up)) != 0) / (len(up) / sr) / 2
    assert 280 < crossings < 320  # 200 Hz becomes about 300 Hz


def test_load_clip_resamples_trims_and_normalizes(tmp_path):
    sr = 44100
    sound = np.concatenate([np.zeros(sr // 2), 0.2 * np.sin(np.arange(sr // 2) / 5), np.zeros(sr // 2)])
    sf.write(tmp_path / "pika.wav", np.stack([sound, sound], axis=1), sr)
    clip = load_clip(tmp_path / "pika.wav")
    assert abs(len(clip) - 12000) < 600  # half a second at 24 kHz, silence trimmed
    assert abs(float(np.max(np.abs(clip))) - 0.8) < 0.01
