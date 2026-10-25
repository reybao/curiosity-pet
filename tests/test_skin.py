"""Private skin: artwork and persona text live in the data directory, never in the repo.

With no skin directory everything falls back to the built-in cat. With one, the page gets the
images and the prompts, filler and catchphrase limiter use the configured persona.
"""

import json

import numpy as np
from fastapi.testclient import TestClient

from curiosity_pet import config, server
from curiosity_pet.lookup import filler
from curiosity_pet.pipeline import farewell
from curiosity_pet.prompts import system_prompt
from curiosity_pet.textclean import MeowLimiter

PIKA = {
    "name": {"zh": "皮皮", "en": "Pippi"},
    "sound": {"zh": "皮卡", "en": "pika"},
    "images": {"idle": "idle.png", "listening": "listening.png", "speaking": "missing.png"},
}


def write_skin(tmp_path, manifest=PIKA, files=("idle.png", "listening.png")):
    d = tmp_path / "skin"
    d.mkdir()
    (d / "skin.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    for f in files:
        (d / f).write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return d


# ---------- config ----------


def test_missing_skin_dir_gives_default_persona(tmp_path):
    assert config.load_skin(tmp_path / "nope") == {}
    persona = config.resolve_persona({})
    assert persona["sound"] == {"zh": "喵", "en": "meow"}
    assert "英短蓝猫" in persona["look"]["zh"]


def test_skin_overrides_only_the_keys_it_sets(tmp_path):
    skin = config.load_skin(write_skin(tmp_path, {"sound": {"zh": "皮卡"}}))
    persona = config.resolve_persona(skin)
    assert persona["sound"] == {"zh": "皮卡", "en": "meow"}  # en falls back
    assert persona["name"]["zh"] == "好奇心伙伴"


def test_broken_skin_json_is_ignored(tmp_path):
    d = tmp_path / "skin"
    d.mkdir()
    (d / "skin.json").write_text("{not json", encoding="utf-8")
    assert config.load_skin(d) == {}


# ---------- persona in prompts and speech ----------


def test_prompts_use_the_name_and_keep_the_program_rule():
    # The owner wants the pet to simply say "I am <name>"; only when asked whether it is real
    # does it say it is a program (hard constraint 4)
    persona = config.resolve_persona(PIKA)
    zh, en = system_prompt("zh", persona), system_prompt("en", persona)
    assert '你是"皮皮"' in zh and "长得像" not in zh and "英短蓝猫" not in zh
    assert "不是真的皮皮" in zh and "程序" in zh and "最多说一个\"皮卡\"" in zh
    assert 'You are "Pippi"' in en and "looks like" not in en and "British" not in en
    assert "not a real Pippi" in en and "program" in en and "add \"pika\" at most once" in en


def test_optional_look_is_included_when_set():
    persona = config.resolve_persona({**PIKA, "look": {"zh": "一只黄色小精灵", "en": "a yellow sprite"}})
    assert '你是"皮皮",一只黄色小精灵,' in system_prompt("zh", persona)
    assert 'You are "Pippi", a yellow sprite,' in system_prompt("en", persona)


def test_default_prompts_are_unchanged_without_skin():
    assert system_prompt("zh") == system_prompt("zh", config.resolve_persona({}))


def test_filler_and_farewell_use_the_sound():
    persona = config.resolve_persona(PIKA)
    assert filler("zh", persona) == "皮卡,我去查一查!"
    assert filler("en", persona) == "Pika, let me look that up!"
    assert farewell("zh", persona) == "好的,下次见,皮卡!"
    assert farewell("en", persona) == "Okay, see you next time. Pika!"
    assert filler("zh") == "喵,我去查一查!"


def test_limiter_keeps_one_configured_sound():
    m = MeowLimiter(sounds=["皮卡", "pika"])
    assert m("我是程序小伙伴皮卡。") == "我是程序小伙伴皮卡。"
    assert m("黑洞很大皮卡。") == "黑洞很大。"
    m2 = MeowLimiter(sounds=["皮卡", "pika"])
    assert m2("Pika! Black holes are big, pika.") == "Pika! Black holes are big."


# ---------- server ----------


def make_client(tmp_path, skin_dir):
    engine = server.Engine(asr=None, tts=None, make_detector=lambda: None)
    return TestClient(server.create_app(engine, allowed_hosts=["testserver"], skin_dir=skin_dir))


def test_no_skin_dir_means_default(tmp_path):
    c = make_client(tmp_path, tmp_path / "nope")
    m = c.get("/skin.json").json()
    assert m["default"] is True and m["cue"] is None  # the kitten: the page synthesizes its own meow
    assert c.get("/skin/idle.png").status_code == 404


def test_skin_manifest_lists_only_existing_images_and_serves_them(tmp_path):
    c = make_client(tmp_path, write_skin(tmp_path))
    m = c.get("/skin.json").json()
    assert m["default"] is False
    assert m["name"] == {"zh": "皮皮", "en": "Pippi"}
    assert m["images"] == {"idle": "/skin/idle.png", "listening": "/skin/listening.png"}  # missing.png dropped
    assert c.get("/skin/idle.png").status_code == 200
    assert c.get("/skin.json").headers["cache-control"] == "no-cache"


def test_skin_manifest_without_idle_image_is_default(tmp_path):
    c = make_client(tmp_path, write_skin(tmp_path, {"images": {"listening": "l.png"}}, files=("l.png",)))
    assert c.get("/skin.json").json()["default"] is True


def test_skin_files_outside_the_directory_are_not_served(tmp_path):
    (tmp_path / "secret.txt").write_text("x")
    c = make_client(tmp_path, write_skin(tmp_path))
    assert c.get("/skin/../secret.txt").status_code in (400, 404)


def test_pcm_helpers_still_work():
    assert server.pcm16_to_float(np.zeros(2, dtype="<i2").tobytes()).tolist() == [0.0, 0.0]


# ---------- app name and home-screen icon ----------


def test_default_name_and_icon(tmp_path):
    c = make_client(tmp_path, tmp_path / "nope")
    page = c.get("/").text
    assert "<title>Curiosity Buddy</title>" in page and 'content="Curiosity Buddy"' in page
    assert "{{APP_NAME}}" not in page and "好奇心伙伴" not in page
    m = c.get("/manifest.webmanifest").json()
    assert m["name"] == "Curiosity Buddy" and m["icons"][0]["src"] == "/apple-touch-icon.png"
    icon = c.get("/apple-touch-icon.png")
    assert icon.status_code == 200 and icon.headers["content-type"] == "image/png"
    assert icon.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_skin_name_and_icon_come_from_the_skin(tmp_path):
    from PIL import Image

    d = write_skin(tmp_path, files=())
    Image.new("RGBA", (300, 400), (255, 0, 0, 255)).save(d / "idle.png")
    (d / "listening.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    c = make_client(tmp_path, d)
    assert "<title>Pippi</title>" in c.get("/").text
    assert c.get("/manifest.webmanifest").json()["short_name"] == "Pippi"
    icon = Image.open(__import__("io").BytesIO(c.get("/apple-touch-icon.png").content))
    assert icon.size == (512, 512) and icon.getpixel((256, 256))[:3] == (255, 0, 0)
    assert icon.getpixel((2, 2))[:3] == (253, 246, 236)  # page background, no transparency around the art
