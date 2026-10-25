"""Several skins with a picker: the built-in kitten plus DATA_DIR/skin-<id>/ folders.

The parent's request: with Goku active the pet must not meow; each skin has its own catchphrase, tone,
voice and "I heard you" cue (kitten: meow, Pikachu: pika, Goku: his own), and a button on the page switches skins.
"""

import json
import shutil

import numpy as np
import pytest
from fastapi.testclient import TestClient

from curiosity_pet import config, server
from curiosity_pet.lookup import filler
from curiosity_pet.pipeline import Pet, farewell
from curiosity_pet.prompts import system_prompt

GOKU = {"name": {"zh": "悟空", "en": "Goku"}, "sound": {"zh": "嘿", "en": "hey"},
        "style": {"zh": "像少年悟空一样直爽、有精神", "en": "like young Goku: cheerful and direct"},
        "voice": {"zh": "zm_020", "en": "no_such_voice"}, "speed": 1.1,
        "images": {"idle": "idle.png"}}
PIKA = {"name": {"zh": "皮卡丘", "en": "Pikachu"}, "sound": {"zh": "皮卡", "en": "pika"},
        "images": {"idle": "idle.png"}, "cue": "pika.wav"}


@pytest.fixture
def skins():
    """Two skin folders in the test data directory; the active skin and settings are restored afterwards."""
    data = config.DATA_DIR
    made = []
    for sid, manifest in (("goku", GOKU), ("pika", PIKA)):
        d = data / f"skin-{sid}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "skin.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        from PIL import Image

        Image.new("RGBA", (100, 140), (200, 120, 0, 255)).save(d / "idle.png")
        made.append(d)
    (data / "skin-pika" / "pika.wav").write_bytes(server.wav_bytes(np.zeros(100, dtype=np.float32)))
    (data / "skin-bad").mkdir(exist_ok=True)  # no skin.json: not offered
    before = config.SETTINGS_FILE.read_text(encoding="utf-8") if config.SETTINGS_FILE.exists() else None
    yield data
    config.activate_skin(config.DEFAULT_SKIN_ID, save=False)
    for d in made + [data / "skin-bad"]:
        shutil.rmtree(d)
    if before is None:
        config.SETTINGS_FILE.unlink(missing_ok=True)
    else:
        config.SETTINGS_FILE.write_text(before, encoding="utf-8")


# ---------- config ----------


def test_kitten_first_then_skin_folders(skins):
    ids = [s["id"] for s in config.list_skins()]
    assert ids == ["cat", "goku", "pika"]
    assert config.list_skins()[1]["persona"]["name"]["zh"] == "悟空"


def test_choose_skin_from_settings_with_fallbacks(tmp_path):
    assert config.choose_skin_id({}, tmp_path) == "cat"
    legacy = tmp_path / "skin"
    legacy.mkdir()
    (legacy / "skin.json").write_text("{}", encoding="utf-8")
    assert config.choose_skin_id({}, tmp_path) == "skin"  # older single-folder setup keeps working
    other = tmp_path / "skin-pika"
    other.mkdir()
    (other / "skin.json").write_text("{}", encoding="utf-8")
    assert config.choose_skin_id({"skin": "pika"}, tmp_path) == "pika"
    assert config.choose_skin_id({"skin": "missing"}, tmp_path) == "skin"
    assert [s["id"] for s in config.list_skins(tmp_path)] == ["cat", "pika"]  # legacy listed only while active
    assert [s["id"] for s in config.list_skins(tmp_path, active="skin")] == ["cat", "pika", "skin"]


def test_switching_changes_catchphrase_tone_and_is_remembered(skins):
    assert filler("zh") == "喵,我去查一查!"
    assert config.activate_skin("goku")
    assert filler("zh") == "嘿,我去查一查!" and farewell("zh") == "好的,下次见,嘿!"
    zh = system_prompt("zh")
    assert '你是"悟空"' in zh and "说话像少年悟空一样直爽、有精神。" in zh and "喵" not in zh
    assert "Talk like young Goku: cheerful and direct." in system_prompt("en")
    assert json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))["skin"] == "goku"
    assert not config.activate_skin("nope") and config.SKIN_ID == "goku"
    assert config.activate_skin("cat")
    assert filler("zh") == "喵,我去查一查!"


def test_each_character_has_its_own_tone():
    assert "说话温柔、好奇。" in system_prompt("zh", config.resolve_persona({}))  # the kitten
    custom = config.resolve_persona({"name": {"zh": "皮皮", "en": "Pippi"}})
    assert "说话" not in system_prompt("zh", custom)[:30] and custom["card"]["zh"] == ""  # no kitten traits on others


def test_character_card_only_when_asked_about_the_character(skins):
    from curiosity_pet.prompts import character_note

    goku = dict(GOKU, card={"zh": "你是《七龙珠》里的少年悟空,会龟派气功,不会七十二变。", "en": "You are young Goku."},
                card_keywords=["七龙珠", "龟派气功", "Dragon Ball"])
    persona, words = config.resolve_persona(goku), config.card_keywords(goku)
    assert "悟空" in words and "Goku" in words
    for q in ["你会什么本领?", "给我讲个故事", "你喜欢吃什么?", "龟派气功厉害吗?", "Who are you?"]:
        assert character_note(q, "zh", persona, words), q
    for q in ["彩虹是怎么来的?", "为什么天空是蓝色的?"]:
        assert character_note(q, "zh", persona, words) is None, q
    assert "不会七十二变" in character_note("你会什么本领?", "zh", persona, words)


def test_character_phrases_override_fixed_lines(skins):
    skin = {"name": {"zh": "悟空"}, "sound": {"zh": "嘿"},
            "phrases": {"farewell": {"zh": "好嘞,下次再一起冒险,嘿!"}, "not_heard": {"zh": "嗯?俺没听清,再说一遍!"}}}
    assert config.phrase("farewell", "zh", "x", skin) == "好嘞,下次再一起冒险,嘿!"
    assert config.phrase("filler", "zh", "默认", skin) == "默认"
    (skins / "skin-goku" / "skin.json").write_text(json.dumps({**GOKU, **{"phrases": skin["phrases"]}}, ensure_ascii=False), encoding="utf-8")
    config.activate_skin("goku", save=False)
    assert farewell("zh") == "好嘞,下次再一起冒险,嘿!"
    tts = FakeTTS()
    Pet(asr=None, tts=tts, player=FakePlayer()).answer("Incluso.")
    assert tts.spoken == [("en", "Hmm, I didn't catch that."), ("en", "Can you say it again?")]


def test_skin_voice_only_when_the_voice_file_exists(tmp_path):
    (tmp_path / "zm_020.safetensors").write_bytes(b"x")
    assert config.skin_voices(GOKU, tmp_path) == {"zh": "zm_020", "en": config.TTS_VOICE["en"]}
    assert config.skin_voices({}, tmp_path) == config.TTS_VOICE
    assert config.skin_speed(GOKU) == 1.1 and config.skin_speed({"speed": 9}) == 1.4 and config.skin_speed({"speed": "x"}) == 1.0


class FakeTTS:
    def __init__(self):
        self.voices, self.speed, self.spoken = None, 1.0, []
        self.voice_path = {}

    def set_voices(self, voices, speed=1.0):
        self.voices, self.speed = voices, speed
        self.voice_path = dict(voices)

    def synthesize(self, text, lang, speed=None):
        self.spoken.append((lang, text))
        return np.concatenate([np.zeros(500), np.full(2400, 0.3), np.zeros(500)]).astype(np.float32)


class FakePlayer:
    def play(self, audio, text=None, on_start=None):
        pass


def test_goodbye_uses_the_active_skin(skins):
    config.activate_skin("goku", save=False)
    tts = FakeTTS()
    Pet(asr=None, tts=tts, player=FakePlayer()).answer("拜拜")
    assert tts.spoken == [("zh", "好的,下次见,嘿!")]


# ---------- server ----------


class FakeDetector:
    def reset(self):
        pass

    def feed(self, chunk):
        return None


def client(tts=None):
    engine = server.Engine(asr=None, tts=tts or FakeTTS(), make_detector=FakeDetector)
    return TestClient(server.create_app(engine, allowed_hosts=["testserver"]))


ORIGIN = {"origin": "http://testserver"}


def test_picker_lists_skins_with_thumbnails(skins):
    c = client()
    m = c.get("/skins.json").json()
    assert m["active"] == "cat"
    assert [(s["id"], s["name"]["zh"]) for s in m["skins"]] == [("cat", "好奇心伙伴"), ("goku", "悟空"), ("pika", "皮卡丘")]
    assert m["skins"][0]["thumb"] == "/static/icon.png"
    thumb = c.get("/skins/goku/thumb.png")
    assert thumb.status_code == 200 and thumb.content[:4] == b"\x89PNG"
    assert c.get("/skins/../thumb.png").status_code == 404 and c.get("/skins/nope/thumb.png").status_code == 404


def test_switching_skin_over_http(skins):
    tts = FakeTTS()
    c = client(tts)
    assert c.post("/skin", json={"id": "goku"}).status_code == 403  # other pages cannot switch it
    assert c.post("/skin", json={"id": "nope"}, headers=ORIGIN).status_code == 404
    r = c.post("/skin", json={"id": "goku"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["active"] == "goku"
    assert c.get("/skin.json").json()["id"] == "goku"
    assert c.get("/skin/idle.png").status_code == 200
    assert "<title>Goku</title>" in c.get("/").text
    assert tts.speed == 1.1 and tts.voices["en"] == config.TTS_VOICE["en"]


def test_cue_per_skin(skins):
    tts = FakeTTS()
    c = client(tts)
    assert c.get("/cue.wav").status_code == 404  # kitten: the page plays its synthesized meow
    c.post("/skin", json={"id": "goku"}, headers=ORIGIN)
    r = c.get("/cue.wav?lang=zh")
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    assert tts.spoken[-1] == ("zh", "嘿!")
    c.get("/cue.wav?lang=en")
    assert tts.spoken[-1] == ("en", "Hey!")
    c.post("/skin", json={"id": "pika"}, headers=ORIGIN)
    own = c.get("/cue.wav")
    assert own.status_code == 200 and own.content == (skins / "skin-pika" / "pika.wav").read_bytes()


def test_switching_stops_a_running_exploration(skins):
    c = client()
    with c.websocket_connect("/ws", headers=ORIGIN) as ws:
        assert ws.receive_json() == {"type": "state", "state": "listening"}
        c.post("/skin", json={"id": "pika"}, headers=ORIGIN)
        assert ws.receive_json() == {"type": "session_ended"}
        assert ws.receive_json() == {"type": "state", "state": "idle"}


def test_who_are_you_is_answered_from_the_card_without_a_guess_marker(skins, monkeypatch):
    from curiosity_pet import pipeline

    (skins / "skin-pika" / "skin.json").write_text(json.dumps(
        {**PIKA, "card": {"zh": "你是《宝可梦》里的皮卡丘。", "en": "You are Pikachu."}}, ensure_ascii=False), encoding="utf-8")
    config.activate_skin("pika", save=False)
    sent = []
    monkeypatch.setattr(pipeline, "stream_chat", lambda msgs: sent.append(msgs[-1]["content"]) or iter(["我是皮卡丘!"]))
    tts = FakeTTS()
    turn = Pet(asr=None, tts=tts, player=FakePlayer()).answer("你是谁?")
    assert "你是《宝可梦》里的皮卡丘" in sent[-1] and not turn.guessed
    assert tts.spoken == [("zh", "我是皮卡丘!")]
