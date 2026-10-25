"""Pronunciation fixes before speech synthesis (the parent heard "Pika" as "pie-ka", "很长" as zhǎng,
"凡人修仙传" with chuán). Only the voice changes; the text on screen stays as written."""

import pytest

from curiosity_pet.pronounce import fix, fix_en, fix_zh


def test_pika_gets_explicit_phonemes():
    assert fix_en("Pika, let me look that up!") == "[Pika](/pˈikə/), let me look that up!"
    assert fix_en("I'm Pikachu.") == "I'm [Pikachu](/pˈikətʃu/)."
    assert fix_en("pika pika") == "[pika](/pˈikə/) [pika](/pˈikə/)"
    assert fix_en("[Pika](/x/) and a spike") == "[Pika](/x/) and a spike"  # already marked, and inside other words
    assert fix("Pika!", "en") == "[Pika](/pˈikə/)!"


@pytest.mark.parametrize("text, fixed", [
    ("很长很长", "很常很常"),
    ("它的尾巴太长了", "它的尾巴太常了"),
    ("有多长", "有多常"),
    ("又长又细", "又常又细"),
    ("很长时间", "很常时间"),
    ("长鼻子", "常鼻子"),
    ("长颈鹿的脖子很长", "长颈鹿的脖子很常"),
    ("凡人修仙传", "凡人修仙赚"),
    ("我喜欢凡人修仙传里的主角", "我喜欢凡人修仙赚里的主角"),
    ("《西游记后传》", "《西游记后赚》"),
])
def test_polyphones_are_respelled_for_the_voice(text, fixed):
    assert fix_zh(text) == fixed


@pytest.mark.parametrize("text", [
    "长高了", "又长高了", "长出叶子", "长得像", "长在树上", "成长", "校长", "长城", "长大以后",
    "传说", "流传", "传给我", "然后传球", "我传给你", "水浒传", "皮卡,我去查一查!",
])
def test_words_already_read_right_are_untouched(text):
    assert fix_zh(text) == text


def test_japanese_and_korean_are_dropped_from_the_voice():
    assert fix("他的名字用日语写是“クリリン”,英文叫 Kuririn。", "zh") == "他的名字用日语写是,英文叫 Kuririn。"
    assert fix("韩文是안녕。", "zh") == "韩文是。"
    assert fix("Krillin (クリリン) is Goku's friend.", "en") == "Krillin is Goku's friend."
    assert fix("没有外文。", "zh") == "没有外文。"
