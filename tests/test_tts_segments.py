"""英文回答中的中文词要交给中文音色,否则会被念成 "Chinese letter"。"""

from curiosity_pet.tts import segments


def test_english_with_chinese_word_is_split():
    assert segments("Pandas, or 熊猫, eat bamboo.", "en") == [
        ("en", "Pandas, or"),
        ("zh", "熊猫"),
        ("en", ", eat bamboo."),
    ]


def test_pure_english_is_one_segment():
    assert segments("The sky is blue.", "en") == [("en", "The sky is blue.")]


def test_chinese_answer_is_not_split():
    # 中文 G2P 自带英文处理
    s = "恐龙 extinct 的意思是灭绝。"
    assert segments(s, "zh") == [("zh", s)]
