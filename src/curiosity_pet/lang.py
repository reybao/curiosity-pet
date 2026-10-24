"""语言判定:按文字占比决定回答语言。

中文按汉字个数计,英文按单词个数计;数字、标点不计。打平或无字时用 fallback
(通常是 ASR 给出的语言标签)。
"""

import re

CJK_CHAR = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
EN_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def detect_language(text: str, fallback: str = "zh") -> str:
    zh = len(CJK_CHAR.findall(text))
    en = len(EN_WORD.findall(text))
    if zh > en:
        return "zh"
    if en > zh:
        return "en"
    return fallback


def from_asr_label(label: str | None) -> str | None:
    """把 Qwen3-ASR 的语言名(如 'Chinese'、'English')转成 zh/en。"""
    if not label:
        return None
    label = label.lower()
    if label.startswith(("chinese", "cantonese", "mandarin")):
        return "zh"
    if label.startswith("english"):
        return "en"
    return None
