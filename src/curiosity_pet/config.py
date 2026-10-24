"""运行配置。都可用环境变量覆盖。

家长设置(联系方式、家人名字、黑名单、联网开关)放在数据目录的 settings.json,不进代码仓库。
"""

import json
import os
from pathlib import Path

# 运行时不联网:模型必须事先下载好,Hugging Face 只读本机缓存
os.environ.setdefault("HF_HUB_OFFLINE", "1")

DATA_DIR = Path(os.environ.get("PET_DATA_DIR", Path.home() / "pet-data-dev"))

OLLAMA_URL = os.environ.get("PET_OLLAMA_URL", "http://127.0.0.1:11434")
CHAT_MODEL = os.environ.get("PET_CHAT_MODEL", "pet-chat")

ASR_MODEL = os.environ.get("PET_ASR_MODEL", "mlx-community/Qwen3-ASR-0.6B-4bit")
TTS_MODEL_DIR = Path(
    os.environ.get("PET_TTS_DIR", Path.home() / "pet-models" / "kokoro-v1.1-zh")
)
TTS_VOICE = {"zh": "zf_001", "en": "af_maple"}

# VAD:孩子停顿多,静音阈值从 0.8 秒起调
VAD_SILENCE_S = float(os.environ.get("PET_VAD_SILENCE", "0.8"))
VAD_THRESHOLD = 0.5
MIC_SAMPLE_RATE = 16000

# iPad 网页服务端口(只监听 127.0.0.1,由 tailscale serve 转发)
SERVER_PORT = int(os.environ.get("PET_SERVER_PORT", "8730"))

SETTINGS_FILE = DATA_DIR / "settings.json"


def load_settings(path: Path = SETTINGS_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_settings = load_settings()

# 联网查询(维基百科):家长开关与维基媒体要求的联系方式。没有联系方式时不联网。
ONLINE_LOOKUP = os.environ.get("PET_ONLINE_LOOKUP", "1" if _settings.get("online_lookup", True) else "0") == "1"
WIKI_CONTACT = os.environ.get("PET_WIKI_CONTACT", _settings.get("wiki_contact", ""))
# 家人和孩子的名字、小名:出现在搜索词里就不联网
FAMILY_TERMS = list(_settings.get("family_terms", []))
# 家长黑名单:出现就不联网(阶段 5 也用于回答)
BLACKLIST = list(_settings.get("blacklist", []))
