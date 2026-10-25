"""System prompt: written entirely in the answer language, states the answer language explicitly, and includes hard constraint 4."""

import re

from curiosity_pet.prompts import build_messages, system_prompt

CJK = re.compile(r"[一-鿿]")


def test_english_prompt_has_no_chinese_and_names_language():
    p = system_prompt("en")
    assert not CJK.search(p)
    assert "English" in p


def test_chinese_prompt_names_language():
    p = system_prompt("zh")
    assert "中文" in p


def test_prompts_state_pet_is_a_program():
    # Hard constraint 4: clearly a program, does not pretend to have feelings, does not ask for secrecy
    assert "程序" in system_prompt("zh")
    assert "program" in system_prompt("en")
    assert "秘密" in system_prompt("zh")
    assert "secret" in system_prompt("en")


def test_prompts_forbid_emoji():
    assert "表情" in system_prompt("zh")
    assert "emoji" in system_prompt("en")


def test_build_messages_appends_language_reminder_to_question():
    msgs = build_messages("Why is the sky blue?", "en", history=[])
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"].startswith("Why is the sky blue?")
    assert "English" in msgs[-1]["content"]


def test_build_messages_keeps_history_between_system_and_question():
    history = [
        {"role": "user", "content": "什么是黑洞?"},
        {"role": "assistant", "content": "黑洞是..."},
    ]
    msgs = build_messages("再简单一点", "zh", history=history)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]


def test_history_keeps_last_two_turns_and_truncates_answers():
    history = []
    for i in range(4):
        history += [
            {"role": "user", "content": f"问题{i}"},
            {"role": "assistant", "content": "长" * 300},
        ]
    msgs = build_messages("再简单一点", "zh", history=history)
    kept = msgs[1:-1]
    assert [m["content"] for m in kept if m["role"] == "user"] == ["问题2", "问题3"]
    assert all(len(m["content"]) <= 123 for m in kept if m["role"] == "assistant")
    # The original history is not modified
    assert len(history[1]["content"]) == 300


def test_system_prompts_are_short():
    # Every turn prefills from scratch, so prompt length directly affects first-token latency
    assert len(system_prompt("zh")) < 200
    assert len(system_prompt("en").split()) < 130


def test_cat_persona_is_still_clearly_a_program():
    # Hard constraint 4: the persona is a cat, but clearly a program, not pretending to be a real cat or to have feelings
    zh, en = system_prompt("zh"), system_prompt("en")
    assert "英短蓝猫" in zh and "程序" in zh and "不是真猫" in zh
    assert "British Shorthair" in en and "program" in en and "not a real cat" in en
    # "meow" is capped, not every sentence ends with one
    assert "最多" in zh and "at most once" in en
