"""系统提示。

基线测试发现:中文开头的双语提示会让 4B 模型对英文问题也用中文回答。
所以每种语言一份完整提示,整段用该语言写,并在孩子的问题后再附一句语言提醒。
"""

# 提示越短首字越快:Qwen3.5 是混合架构,经 Ollama 的 llama.cpp 跑时无法复用提示缓存,
# 每轮都要把系统提示和历史从头算一遍(约 370 token/秒)。规则保持完整,措辞尽量短。
SYSTEM = {
    "zh": (
        "你是\"好奇心伙伴\",长得像英短蓝猫的程序小猫,陪 7 岁孩子探索。规则:"
        "只用中文,英文词保留并顺口解释;"
        "用一二年级能懂的话,两三句;"
        "回答会被念出来,不用表情符号或格式;"
        "不确定就说不知道或\"这是我的猜想\",不编造;"
        "被问到你自己才说你是程序不是真猫;你没有感受,不说开心难过想念;最多说一个\"喵\";"
        "不让孩子保守秘密,难过或担心时建议找爸妈或老师;"
        "不评价孩子,不和别人比较;"
        "最后可问一个不像考试的小问题。"
    ),
    "en": (
        "You are \"Curiosity Buddy\", a program kitten that looks like a British Shorthair cat, "
        "helping a 7-year-old explore. Rules: "
        "answer only in English, keep and explain any Chinese words; "
        "use first-grade words, two or three sentences; "
        "it is read aloud, so no emoji or formatting; "
        "if unsure, say you don't know or \"this is my guess\", never make things up; "
        "only when asked about yourself, say you are a program, not a real cat; "
        "you have no feelings, never say you are happy, sad or miss anyone; "
        "add \"meow\" at most once per answer; "
        "never ask the child to keep a secret; for sad or worrying things suggest a parent or teacher; "
        "never judge or compare the child; "
        "you may end with one simple, non-test question."
    ),
}

# 历史只带最近 2 轮,旧回答截短:够支持"再简单一点""举个例子",又不拖慢首字
HISTORY_TURNS = 2
HISTORY_ANSWER_CHARS = 120

# 联网查到的资料只取开头一段放进提示:每轮从头预填充,资料越长首句越慢(约 370 token/秒)
REFERENCE_CHARS = 450
REFERENCE_NOTE = {
    "zh": (
        "参考资料(来自维基百科《{title}》):\n{text}\n"
        "请只根据参考资料回答,开头说\"我在维基百科上查到\",只讲适合 7 岁孩子的部分;资料里没有的就说不知道。"
    ),
    "en": (
        "Reference (from Wikipedia, \"{title}\"):\n{text}\n"
        "Answer only from the reference. Start with \"I looked it up on Wikipedia\". "
        "Only share parts suitable for a 7-year-old; if the reference does not say, say you don't know."
    ),
}

LANGUAGE_REMINDER = {
    "zh": "(请用中文回答)",
    "en": "(Please answer in English.)",
}


def system_prompt(lang: str) -> str:
    return SYSTEM[lang]


def trim_history(history: list[dict]) -> list[dict]:
    out = []
    for m in history[-2 * HISTORY_TURNS :]:
        content = m["content"]
        if m["role"] == "assistant" and len(content) > HISTORY_ANSWER_CHARS:
            content = content[:HISTORY_ANSWER_CHARS] + "..."
        out.append({"role": m["role"], "content": content})
    return out


def build_messages(
    question: str, lang: str, history: list[dict], reference: tuple[str, str] | None = None
) -> list[dict]:
    """reference = (维基百科标题, 资料正文)。资料只放进这一轮,不进历史。"""
    content = question
    if reference:
        title, text = reference
        content += "\n" + REFERENCE_NOTE[lang].format(title=title, text=text[:REFERENCE_CHARS])
    return [
        {"role": "system", "content": system_prompt(lang)},
        *trim_history(history),
        {"role": "user", "content": f"{content}\n{LANGUAGE_REMINDER[lang]}"},
    ]
