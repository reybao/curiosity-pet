"""语言判定:宠物用孩子提问的语言回答,中英混说以占比多的语言为主。"""

import pytest

from curiosity_pet.lang import detect_language


@pytest.mark.parametrize(
    "text, expected",
    [
        ("为什么月亮白天也会出现?", "zh"),
        ("Why is the sky blue?", "en"),
        ("How do fish breathe under water?", "en"),
        # 混说:中文字多
        ("为什么 dinosaurs 会 extinct?", "zh"),
        ("恐龙为什么会 extinct 呢?", "zh"),
        # 混说:英文词多
        ("Why do 熊猫 eat bamboo all day?", "en"),
        ("What is a 黑洞 made of?", "en"),
        # 数字和标点不计入
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
    # 中文 1 个字对英文 1 个词,打平时用识别器给的语言
    assert detect_language("好 OK", fallback="en") == "en"
    assert detect_language("好 OK", fallback="zh") == "zh"
