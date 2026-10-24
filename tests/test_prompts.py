"""系统提示:整段用回答语言写,并明确写出回答语言;含第 4 条硬性约束。"""

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
    # 第 4 条硬性约束:明确是程序,不假装有感受,不要求保密
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
    # 原历史不被修改
    assert len(history[1]["content"]) == 300


def test_system_prompts_are_short():
    # 每轮都要从头预填充,提示长度直接影响首字延迟
    assert len(system_prompt("zh")) < 200
    assert len(system_prompt("en").split()) < 130


def test_cat_persona_is_still_clearly_a_program():
    # 第 4 条硬性约束:形象是猫,但明确是程序,不假装是真猫、不假装有感受
    zh, en = system_prompt("zh"), system_prompt("en")
    assert "英短蓝猫" in zh and "程序" in zh and "不是真猫" in zh
    assert "British Shorthair" in en and "program" in en and "not a real cat" in en
    # "喵"有上限,不是每句都喵
    assert "最多" in zh and "at most once" in en
