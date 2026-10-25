"""Cleanup before TTS: strip emoji and Markdown symbols, keep normal text and punctuation."""

from curiosity_pet.textclean import clean_for_speech


def test_removes_emoji():
    assert clean_for_speech("鳃帮它们呼吸!🐠💧") == "鳃帮它们呼吸!"
    assert clean_for_speech("Big space rock! ☄️ Wow 😊") == "Big space rock! Wow"


def test_removes_markdown():
    assert clean_for_speech("**月亮**不会发光") == "月亮不会发光"
    assert clean_for_speech("- 第一点") == "第一点"
    assert clean_for_speech("# Title") == "Title"


def test_keeps_normal_text():
    s = "月亮反射太阳的光,所以白天也能看到。"
    assert clean_for_speech(s) == s
    assert clean_for_speech("It's 3.5 km away.") == "It's 3.5 km away."


def test_empty_after_cleaning():
    assert clean_for_speech("😊🐜") == ""


def test_meow_limiter_keeps_only_the_first_meow():
    from curiosity_pet.textclean import MeowLimiter

    m = MeowLimiter()
    assert m("我是程序小猫,没有真的身体喵。") == "我是程序小猫,没有真的身体喵。"
    assert m("我不会难过喵。") == "我不会难过。"
    assert m("有事找爸爸妈妈喵!") == "有事找爸爸妈妈!"


def test_meow_limiter_english():
    from curiosity_pet.textclean import MeowLimiter

    m = MeowLimiter()
    assert m("No, I am not a real cat. Meow.") == "No, I am not a real cat. Meow."
    assert m("Meow. I can talk to you.") == "I can talk to you."
    assert m("Cats purr, meow!") == "Cats purr!"


def test_meow_limiter_leaves_other_words_alone():
    from curiosity_pet.textclean import MeowLimiter

    m = MeowLimiter()
    assert m("猫咪叫起来是喵喵的声音吗?") == "猫咪叫起来是喵喵的声音吗?"  # the first one is kept
    assert m("homeowner") == "homeowner"
