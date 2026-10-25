"""Language detection: pick the answer language by the share of text in each language.

Chinese is counted by characters, English by words; digits and punctuation are ignored. On a tie or when there is no text, use fallback
(usually the language label from ASR).
"""

import re

CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
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
    """Convert a Qwen3-ASR language name (e.g. 'Chinese', 'English') to zh/en."""
    if not label:
        return None
    label = label.lower()
    if label.startswith(("chinese", "cantonese", "mandarin")):
        return "zh"
    if label.startswith("english"):
        return "en"
    return None
