"""System prompts.

Baseline testing found that a bilingual prompt starting in Chinese makes the 4B model answer English questions in Chinese too.
So each language gets a complete prompt written entirely in that language, plus a language reminder after the child's question.
"""

import re

from curiosity_pet import config

# The shorter the prompt, the faster the first token: Qwen3.5 is a hybrid architecture and cannot reuse the prompt cache under Ollama's llama.cpp,
# so the system prompt and history are recomputed from scratch every turn (about 370 tokens/s). Keep the rules complete and the wording short.
# Templates; {name}, {look}, {style}, {not_real}, {sound} come from the persona (config.PERSONA, set by the active skin).
SYSTEM_TEMPLATE = {
    "zh": (
        "你是\"{name}\"{look},陪 7 岁孩子探索。{style}规则:"
        "只用中文,英文词保留并顺口解释;"
        "用一二年级能懂的话,两三句;"
        "回答会被念出来,不用表情符号或格式;"
        "不确定就说不知道或\"这是我的猜想\",不编造;"
        "只有被问到你是不是真的,才说你是程序,不是{not_real};不说自己开心难过想念;最多说一个\"{sound}\";"
        "不让孩子保守秘密;"
        "不评价孩子,不比较。"
    ),
    "en": (
        "You are \"{name}\"{look}, helping a 7-year-old explore. {style}Rules: "
        "answer only in English, keep and explain any Chinese words; "
        "use first-grade words, two or three sentences; "
        "it is read aloud, so no emoji or formatting; "
        "if unsure, say you don't know or \"this is my guess\", never make things up; "
        "only when asked whether you are real, say you are a program, not {not_real}; "
        "never say you are happy, sad or miss anyone; "
        "add \"{sound}\" at most once per answer; "
        "never ask the child to keep a secret; "
        "never judge or compare the child."
    ),
}


def render_system(lang: str, persona: dict) -> str:
    look = persona["look"][lang]
    look = ("," if lang == "zh" else ", ") + look if look else ""
    style = persona.get("style", {}).get(lang, "")
    # The skin's speaking tone, e.g. "像少年悟空一样直爽、有精神"
    style = (f"说话{style}。" if lang == "zh" else f"Talk {style}. ") if style else ""
    return SYSTEM_TEMPLATE[lang].format(
        name=persona["name"][lang], look=look, style=style, not_real=persona["not_real"][lang],
        sound=persona["sound"][lang],
    )


# Rendered with the active persona; evals and tests import this
SYSTEM = {lang: render_system(lang, config.PERSONA) for lang in ("zh", "en")}

HISTORY_TURNS = 2
HISTORY_ANSWER_CHARS = 120

# Only the opening paragraph of looked-up material goes into the prompt: it is prefilled from scratch each turn, so longer material slows the first sentence (about 370 tokens/s)
REFERENCE_CHARS = 450
REFERENCE_NOTE = {
    "zh": (
        "参考资料(来自{source}《{title}》):\n{text}\n"
        "如果资料回答了问题,就照资料讲,开头说\"我在{source}里查到\";如果资料和问题无关,就用你自己知道的回答,"
        "不要提资料。只讲适合 7 岁孩子的部分,不确定的细节说不知道。"
    ),
    "en": (
        "Reference (from {source}, \"{title}\"):\n{text}\n"
        "If the reference answers the question, use it and start with \"I found it in {source}\"; if it is not about "
        "the question, answer from what you know and do not mention the reference. Only share parts suitable for a "
        "7-year-old; for uncertain details say you don't know."
    ),
}

# Per-turn instructions appended to the child's message. Whether a follow-up question is allowed is
# decided by followup.FollowUpPolicy; the "talk to a parent" line appears only when the program detects distress.
ASK_NOTE = {
    "zh": {True: "(最后可以问一个不像考试的小问题)", False: "(不要提问,不要反问,说完就停)"},
    "en": {True: "(You may end with one simple, non-test question.)", False: "(Do not ask any question; stop when done.)"},
}
CARE_NOTE = {
    "zh": "(孩子在说难过或害怕的事:先温和地接住,说这样的感觉是正常的,再建议告诉爸爸妈妈或老师;不追问细节,不说教)",
    "en": "(The child is sharing something sad or scary: respond gently, say the feeling is normal, suggest telling a parent or teacher; do not probe for details, do not lecture)",
}

# No material was found for a question about specific people, works or events: the pet says it is
# guessing (spoken by the program as the first sentence) and the model is told not to invent details
GUESS_NOTE = {
    "zh": "(没有查到资料。只说你有把握的,不确定的细节直接说不知道,不要编人名、情节或数字)",
    "en": "(No material was found. Say only what you are sure of; for uncertain details say you don't know; never invent names, events or numbers.)",
}
GUESS_SPOKEN = {"zh": "我不太确定,这是我的猜想。", "en": "I'm not sure, this is my guess."}

# What the pet can and cannot do, added when the child asks about abilities (remember, remind, pictures, plans ...)
ABILITY_NOTE = {
    "zh": "(你能做的:陪她聊天、回答问题、查小图书馆、讲故事、猜谜语、算数;她说\"我喜欢…\"你会记住她的兴趣;她说\"收藏\"会把刚才的问答"
          "放进\"我的发现\"。你做不到:记住聊天内容、定闹钟或到时提醒、"
          "给她看图片或视频、保存或发送文件、带她去哪里。被问到就诚实说做不到,可以建议请爸爸妈妈帮忙,不要假装做到了)",
    "en": "(What you can do: talk, answer questions, look things up in your library, tell stories, riddles, arithmetic; "
          "remember interests she tells you (\"I like ...\"); keep the last question and answer in My Discoveries when she "
          "says \"save this\". What you cannot do: remember what was said in chats, set alarms or reminders, show pictures or videos, save or send files, "
          "take her anywhere. If asked, say honestly you cannot and suggest asking a parent; never pretend you did it.)",
}

# Character facts (skin.json "card"), only when the child asks about the character or its world. Fixes mix-ups
# seen in real use, e.g. Goku "knowing 72 transformations" (that is the Monkey King of Journey to the West).
CHARACTER_NOTE = {
    "zh": "(你的角色资料,相关时自然地用,不要整段背出来:{card})",
    "en": "(About your character; use it naturally when relevant, do not recite it: {card})",
}
ABOUT_CHARACTER = re.compile(
    r"你是谁|你叫什么|你会什么|你有什么本领|你的本领|本事|绝招|招式|你的朋友|你的师父|你的老师|你的家|你住在|你从哪|你几岁|你多大|"
    r"你喜欢|你爱吃|你最喜欢|你怕|讲讲你|说说你|你的故事|讲.{0,4}故事|"
    r"who are you|your name|what can you do|your (?:friends?|teacher|home|story|family|favorite)|tell me (?:a story|about you)|"
    r"do you like|where do you live|how old are you|are you strong",
    re.IGNORECASE,
)


def character_note(question: str, lang: str, persona: dict, keywords) -> str | None:
    card = persona.get("card", {}).get(lang, "")
    if not card:
        return None
    q = question.lower()
    if ABOUT_CHARACTER.search(question) or any(k and k.lower() in q for k in keywords):
        return CHARACTER_NOTE[lang].format(card=card)
    return None


# The child poses a riddle: the pet guesses; it never answers with a riddle of its own
CHILD_RIDDLE_NOTE = {
    "zh": "(孩子在给你出谜语或脑筋急转弯。认真想,用\"我猜是……\"说出一个答案和简短理由,最后只问一句\"我猜对了吗?\";不要问别的,不要反过来出题)",
    "en": "(The child is giving you a riddle. Think, then say \"My guess is ...\" with a short reason, and end with only \"Am I right?\" Ask nothing else and do not give a riddle back.)",
}
CHILD_RIDDLE_REPLY_NOTE = {
    "zh": "(孩子在说你刚才猜得对不对,或告诉你答案。猜对了就说\"我猜对啦\";猜错了就再猜一次或请她公布答案;她说出答案就夸她的谜语有意思;不要出新题,不要问别的)",
    "en": "(The child is saying whether your guess was right or telling the answer. If you were right, say \"I got it!\"; if wrong, guess once more or ask for the answer; if she tells it, say her riddle was a good one. Do not give a new riddle or ask anything else.)",
}

LANGUAGE_REMINDER = {
    "zh": "(请用中文回答)",
    "en": "(Please answer in English.)",
}


def system_prompt(lang: str, persona: dict | None = None) -> str:
    """Rendered for the active skin at call time, so switching skins takes effect on the next turn."""
    return render_system(lang, config.PERSONA if persona is None else persona)


def trim_history(history: list[dict]) -> list[dict]:
    out = []
    for m in history[-2 * HISTORY_TURNS :]:
        content = m["content"]
        if m["role"] == "assistant" and len(content) > HISTORY_ANSWER_CHARS:
            content = content[:HISTORY_ANSWER_CHARS] + "..."
        out.append({"role": m["role"], "content": content})
    return out


def build_messages(
    question: str,
    lang: str,
    history: list[dict],
    reference: tuple[str, str] | None = None,
    ask: bool = False,
    care: bool = False,
    guess: bool = False,
    date_note: str | None = None,
    source: str | None = None,
    note: str | None = None,
) -> list[dict]:
    """reference = (Wikipedia title, material text), used for this turn only, not kept in history.
    ask: a follow-up question is allowed this turn. care: the child expressed distress."""
    content = question
    if reference:
        title, text = reference
        label = source or ("维基百科" if lang == "zh" else "Wikipedia")
        content += "\n" + REFERENCE_NOTE[lang].format(source=label, title=title, text=text[:REFERENCE_CHARS])
    if date_note:
        content += "\n" + date_note
    if guess and not reference:
        content += "\n" + GUESS_NOTE[lang]
    if care:
        content += "\n" + CARE_NOTE[lang]
    if note:
        content += "\n" + note
    content += "\n" + ASK_NOTE[lang][bool(ask) and not care]
    return [
        {"role": "system", "content": system_prompt(lang)},
        *trim_history(history),
        {"role": "user", "content": f"{content}\n{LANGUAGE_REMINDER[lang]}"},
    ]
