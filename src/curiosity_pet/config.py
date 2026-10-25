"""Runtime configuration. Everything can be overridden by environment variables.

Parent settings (contact info, family names, blacklist, web lookup switch) live in settings.json in the data directory, not in the code repository.
"""

import json
import os
from pathlib import Path

# No network at runtime: models must be downloaded beforehand; Hugging Face reads only the local cache
os.environ.setdefault("HF_HUB_OFFLINE", "1")

DATA_DIR = Path(os.environ.get("PET_DATA_DIR", Path.home() / "pet-data-dev"))

OLLAMA_URL = os.environ.get("PET_OLLAMA_URL", "http://127.0.0.1:11434")
CHAT_MODEL = os.environ.get("PET_CHAT_MODEL", "pet-chat")  # settings.json "chat_model" may override below

ASR_MODEL = os.environ.get("PET_ASR_MODEL", "mlx-community/Qwen3-ASR-0.6B-4bit")
TTS_MODEL_DIR = Path(
    os.environ.get("PET_TTS_DIR", Path.home() / "pet-models" / "kokoro-v1.1-zh")
)
TTS_VOICE = {"zh": "zf_001", "en": "af_maple"}

# VAD: children pause a lot, so tune the silence threshold starting from 0.8 s
VAD_SILENCE_S = float(os.environ.get("PET_VAD_SILENCE", "0.8"))
VAD_THRESHOLD = 0.5
MIC_SAMPLE_RATE = 16000

# iPad web server port (listens on 127.0.0.1 only, forwarded by tailscale serve)
SERVER_PORT = int(os.environ.get("PET_SERVER_PORT", "8730"))

SETTINGS_FILE = DATA_DIR / "settings.json"


def load_settings(path: Path = SETTINGS_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_settings = load_settings()

# Main model: pet-chat (4B) by default; the parent can switch to pet-chat-9b in settings.json ("chat_model")
if "PET_CHAT_MODEL" not in os.environ and _settings.get("chat_model"):
    CHAT_MODEL = str(_settings["chat_model"])
# Model for the short JSON jobs (classify and rewrite a question, tag a topic, judge a riddle answer).
# Defaults to the main model: loading a second model next to the 9B and the speech models does not fit in
# 16 GB (measured: swap 11.6 GB, lookup turns 11 to 15 s).
HELPER_MODEL = os.environ.get("PET_HELPER_MODEL", str(_settings.get("helper_model", CHAT_MODEL)))

# Context-aware intent judgment before the handlers (router.py); off until the replay evaluation shows it is better
ROUTER = bool(_settings.get("router", False))

# An exploration wraps up on its own after this many minutes (CLAUDE.md: 10 to 15; the pet never tries to keep the child)
WRAP_UP_MINUTES = float(_settings.get("wrap_up_minutes", 15))

# Web lookup (Wikipedia): the parent switch and the contact info Wikimedia requires. No contact info means no web access.
ONLINE_LOOKUP = os.environ.get("PET_ONLINE_LOOKUP", "1" if _settings.get("online_lookup", True) else "0") == "1"
WIKI_CONTACT = os.environ.get("PET_WIKI_CONTACT", _settings.get("wiki_contact", ""))
# Names and nicknames of family and child: if one appears in the search terms, do not go online
FAMILY_TERMS = list(_settings.get("family_terms", []))
# Parent blacklist: if a term appears, do not go online (stage 5 also uses it for answers)
BLACKLIST = list(_settings.get("blacklist", []))

# Private skins: artwork and persona text in the data directory (never in the repo).
# Each skin is a folder DATA_DIR/skin-<id>/ with skin.json and images; the built-in kitten is the skin "cat".
# The active skin is settings.json "skin"; older setups have a single DATA_DIR/skin/ folder, used when "skin" is unset.
# skin.json may set, each as {"zh":..., "en":...}: name, look (optional), not_real, sound (the catchphrase),
# style (speaking tone, always in the prompt), card (character facts, added only when the child asks about the
# character or its world), voice (TTS voice names); plus card_keywords (words that bring in the card), phrases (the
# character's own fixed lines), speed (TTS speed) and cue (an audio file played when the pet has heard the child).
LEGACY_SKIN_DIR = DATA_DIR / "skin"
DEFAULT_SKIN_ID = "cat"
DEFAULT_PERSONA = {
    "name": {"zh": "好奇心伙伴", "en": "Curiosity Buddy"},
    "look": {"zh": "长得像英短蓝猫的程序小猫", "en": "a program kitten that looks like a British Shorthair cat"},
    "not_real": {"zh": "真猫", "en": "a real cat"},
    "sound": {"zh": "喵", "en": "meow"},
    "style": {"zh": "温柔、好奇", "en": "gently and curiously"},
    "card": {
        "zh": "你是一只长得像英国短毛蓝猫的程序小猫:蓝灰色的毛,圆圆的铜色眼睛,脖子上有会变色的项圈灯。"
              "你特别好奇,爱问为什么,喜欢晒太阳、看窗外的小鸟。说话温柔、慢慢的,像好朋友一样。",
        "en": "You are a program kitten that looks like a British Shorthair: blue-grey fur, round copper eyes, and a collar "
              "light that changes color. You are very curious, love asking why, and like sunshine and watching birds "
              "outside the window. You talk gently and slowly, like a good friend.",
    },
}
DEFAULT_CARD_KEYWORDS = ["猫", "小猫", "cat", "kitten"]
SKIN_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def load_skin(skin_dir: Path | None = LEGACY_SKIN_DIR) -> dict:
    if skin_dir is None:
        return {}
    try:
        data = json.loads((Path(skin_dir) / "skin.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, NotADirectoryError, json.JSONDecodeError):
        return {}


def resolve_persona(skin: dict) -> dict:
    """Merge skin text over the defaults, per key and per language.

    When the skin sets a name but no look, the look is dropped (the pet just says "I am <name>") and
    not_real defaults to "a real <name>", so the program rule still names the character.
    """
    custom_name = "name" in skin
    persona = {}
    for key, default in DEFAULT_PERSONA.items():
        value = skin.get(key)
        value = value if isinstance(value, dict) else {}
        if key in ("look", "style", "card") and custom_name and key not in skin:
            persona[key] = {"zh": "", "en": ""}  # the kitten's description does not fit another character
            continue
        if key == "not_real" and custom_name and "not_real" not in skin:
            name = {**default, **skin["name"]} if isinstance(skin["name"], dict) else default
            persona[key] = {"zh": f"真的{name.get('zh', '')}", "en": f"a real {name.get('en', '')}"}
            continue
        persona[key] = {**default, **{k: str(v) for k, v in value.items() if k in default}}
    return persona


def card_keywords(skin: dict | None = None) -> list[str]:
    """Words that bring the character card into the prompt: the skin's list plus its names."""
    skin = SKIN if skin is None else skin
    words = skin.get("card_keywords") if isinstance(skin.get("card_keywords"), list) else ([] if "name" in skin else DEFAULT_CARD_KEYWORDS)
    names = resolve_persona(skin)["name"].values()
    return [str(w) for w in [*words, *names] if str(w).strip()]


def phrase(name: str, lang: str, default: str, skin: dict | None = None) -> str:
    """A fixed line in the character's own words (skin.json "phrases"), else the default."""
    skin = SKIN if skin is None else skin
    phrases = skin.get("phrases") if isinstance(skin.get("phrases"), dict) else {}
    value = phrases.get(name, {}).get(lang) if isinstance(phrases.get(name), dict) else None
    return str(value) if value else default


def skin_voices(skin: dict, voices_dir: Path | None = None) -> dict:
    """TTS voices for a skin: its "voice" names where the converted voice file exists, else the defaults."""
    voices_dir = voices_dir or (TTS_MODEL_DIR / "voices")
    chosen = dict(TTS_VOICE)
    wanted = skin.get("voice") if isinstance(skin.get("voice"), dict) else {}
    for lang, name in wanted.items():
        if lang in chosen and isinstance(name, str) and (voices_dir / f"{name}.safetensors").is_file():
            chosen[lang] = name
    return chosen


def skin_speed(skin: dict) -> float:
    try:
        return min(1.4, max(0.7, float(skin.get("speed", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def skin_dir_for(skin_id: str, data_dir: Path | None = None) -> Path | None:
    """Folder of a skin, or None for the built-in kitten. "skin" is the older single-folder setup."""
    data_dir = data_dir or DATA_DIR
    if skin_id == DEFAULT_SKIN_ID:
        return None
    return data_dir / "skin" if skin_id == "skin" else data_dir / f"skin-{skin_id}"


def list_skins(data_dir: Path | None = None, active: str | None = None) -> list[dict]:
    """Every skin the page can offer: the built-in kitten first, then each skin-<id> folder with a skin.json.
    The older single "skin" folder is listed only while it is the active one."""
    data_dir = data_dir or DATA_DIR
    found = [{"id": DEFAULT_SKIN_ID, "dir": None}]
    for d in sorted(data_dir.glob("skin-*")):
        sid = d.name[len("skin-"):]
        if d.is_dir() and sid and set(sid) <= SKIN_ID_CHARS and (d / "skin.json").is_file():
            found.append({"id": sid, "dir": d})
    if active == "skin" and (data_dir / "skin" / "skin.json").is_file():
        found.append({"id": "skin", "dir": data_dir / "skin"})
    for s in found:
        s["persona"] = resolve_persona(load_skin(s["dir"]))
    return found


def choose_skin_id(settings: dict, data_dir: Path | None = None) -> str:
    data_dir = data_dir or DATA_DIR
    wanted = settings.get("skin")
    if isinstance(wanted, str) and any(s["id"] == wanted for s in list_skins(data_dir)):
        return wanted
    if (data_dir / "skin" / "skin.json").is_file():
        return "skin"
    return DEFAULT_SKIN_ID


SKIN_ID = choose_skin_id(_settings)
SKIN_DIR = skin_dir_for(SKIN_ID)
SKIN = load_skin(SKIN_DIR)
PERSONA = resolve_persona(SKIN)


def activate_skin(skin_id: str, save: bool = True) -> bool:
    """Switch the active skin for the whole process (persona, prompts, voice); optionally remember it in settings.json.
    Modules read config.PERSONA / config.SKIN at call time, so the next sentence already uses the new skin."""
    global SKIN_ID, SKIN_DIR, SKIN, PERSONA
    if not any(s["id"] == skin_id for s in list_skins(active=SKIN_ID)):
        return False
    SKIN_ID, SKIN_DIR = skin_id, skin_dir_for(skin_id)
    SKIN = load_skin(SKIN_DIR)
    PERSONA = resolve_persona(SKIN)
    if save:
        settings = load_settings()
        settings["skin"] = skin_id
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
