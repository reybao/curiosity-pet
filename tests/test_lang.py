"""Language detection: the pet answers in the language the child asked in; for mixed speech, the majority language wins."""

import pytest

from curiosity_pet.lang import detect_language


@pytest.mark.parametrize(
    "text, expected",
    [
        ("为什么月亮白天也会出现?", "zh"),
        ("Why is the sky blue?", "en"),
        ("How do fish breathe under water?", "en"),
        # Mixed: mostly Chinese characters
        ("为什么 dinosaurs 会 extinct?", "zh"),
        ("恐龙为什么会 extinct 呢?", "zh"),
        # Mixed: mostly English words
        ("Why do 熊猫 eat bamboo all day?", "en"),
        ("What is a 黑洞 made of?", "en"),
        # Digits and punctuation do not count
        ("1 加 1 等于几?", "zh"),
        ("What is 100 plus 200?", "en"),
    ],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_empty_text_uses_fallback():
    assert detect_language("", fallback="en") == "en"
    assert detect_language("???", fallback="zh") == "zh"


def test_asr_label_breaks_ties():
    # 1 Chinese character vs 1 English word: on a tie, use the detector's language
    assert detect_language("好 OK", fallback="en") == "en"
    assert detect_language("好 OK", fallback="zh") == "zh"
