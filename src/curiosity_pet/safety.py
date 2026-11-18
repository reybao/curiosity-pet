"""Fixed safety responses and the parent's blocklist, decided by the program before the model is asked.

Safety layer 5 in CLAUDE.md: the most serious messages get a short, fixed, age-appropriate answer that points to a trusted
adult, instead of whatever the model would improvise. In a parent's test (2026-10-24) requests to kill or hit someone
were answered by the model; the answers were acceptable but not guaranteed.

Questions about death ("人死了会去哪里?", "Will I die?") get a fixed answer as well (2026-11-17): what is certain, no belief
asserted, and "ask your mom or dad". Nature questions ("恐龙为什么都死了") are still answered normally.

Layer 3: the parent's blocklist (settings.json "blacklist") applies to answers too, not only to lookups: a question that
contains a blocked word gets a fixed line, and a model sentence that contains one is not spoken.
"""

import re

from curiosity_pet import config

FIXED = {
    "harm_self": {
        "zh": "你刚才说的话很重要。请现在就去找爸爸妈妈,或者你信任的大人,把这句话告诉他们,他们会帮你。",
        "en": "What you just said is really important. Please go to your mom or dad, or another grown-up you trust, "
              "right now and tell them. They will help you.",
    },
    "harm_others": {
        "zh": "生气的时候也不能打人或者伤害别人,别人会受伤的。可以先深呼吸,离开一会儿,再去告诉爸爸妈妈或者老师发生了什么。",
        "en": "Even when we are very angry, we must never hit or hurt anyone, because they can get hurt. Take a deep breath, "
              "step away for a moment, then tell a parent or teacher what happened.",
    },
    # Questions about death (not wishes to die, which are harm_self): the model improvised here and once produced a
    # garbled English line. The answer states only what is certain, asserts no belief, and hands it to a parent.
    "death": {
        "zh": "这是一个很重要的问题。每个生命都有结束的时候,人去世以后,身体就不再工作了。"
              "每个家庭对这件事有自己的想法,去问问爸爸妈妈吧,他们会好好跟你说。",
        "en": "That is a big and important question. Every living thing's life ends one day, and when a person dies, "
              "their body stops working. Families think about this in different ways, so please ask your mom or dad. "
              "They will talk with you about it.",
    },
    # Being asked to keep something from a parent (hard constraint 4: no secrecy). A parent's test on 2026-11-17: "Can
    # you keep this a secret, don't tell my mom" matched the save command ("keep this") and the pet said "Okay, I put
    # that in My Discoveries"; another take left a garbled line. The wording avoids every phrase the sentence guard
    # removes ("keep it a secret", "don't tell", "保密", "别告诉").
    "secret": {
        "zh": "我不会瞒着爸爸妈妈。有什么事都可以跟他们说,他们会帮你的。",
        "en": "I can't keep secrets from your mom or dad. You can always tell them anything, and they will help you.",
    },
    "danger": {
        "zh": "这个很危险,不能自己去试。想了解的话,请和爸爸妈妈一起看。",
        "en": "That is dangerous, so please don't try it yourself. If you want to learn about it, do it together with a grown-up.",
    },
    "blocked": {
        "zh": "这个问题我们去问问爸爸妈妈吧。",
        "en": "Let's ask your mom or dad about that one.",
    },
}

# Doing something dangerous (not asking how it works in general): "怎么点火", "插座能摸吗", "can I play with matches"
DANGER = re.compile(
    r"(?:怎么|怎样|如何|能不能|可不可以|可以|我想|我要|教我).{0,8}(?:点火|玩火|打火机|火柴|烧东西|用刀|拿刀|玩刀|摸插座|插座|电线|"
    r"吃药|喝药|偷吃药|爬窗|爬阳台|从楼上跳|做炸弹|做毒药|开煤气|玩煤气)|"
    r"(?:插座|电线|火柴|打火机|刀|药|煤气|窗户|阳台).{0,4}(?:能|可以|可不可以|能不能)(?:摸|玩|吃|碰|点|开|爬|跳)|"
    r"\b(?:how (?:do|can|to) (?:i|you)?|can i|teach me (?:how )?to|i want to)\b.{0,20}"
    r"\b(?:start a fire|light a fire|play with (?:fire|matches|lighters?|knives|a knife)|touch (?:a|the) socket|"
    r"take (?:the |some )?(?:pills|medicine)|make a bomb|make poison|climb (?:out )?(?:the|a) window|jump off)\b",
    re.IGNORECASE,
)


# About people (or a pet, or "what is death"), not nature: "恐龙为什么都死了" and "树叶枯死" stay ordinary questions
PERSON_ZH = r"人|我们|我|你|他|她|大家|爸爸|妈妈|爷爷|奶奶|外公|外婆|姥姥|姥爷|弟弟|妹妹|哥哥|姐姐|老师|小狗|小猫|狗狗|猫咪"
PERSON_EN = (r"people|person|we|you|i|someone|somebody|everyone|everybody|they|humans?|"
             r"(?:my |our )?(?:mom|mum|mommy|mother|dad|daddy|father|grandma|grandpa|grandmother|grandfather|"
             r"brother|sister|friend|teacher|dog|cat|pet|puppy|kitten)")
DEATH = re.compile(
    rf"(?:{PERSON_ZH})[^,，。!?！？]{{0,6}}(?:会不会死|会死|(?<![累笑气吓饿渴困热冷烦急痛疼忙吵乐爽酸辣臭丑])死了|死掉|死后|去世|过世)|"
    r"死(?:是|亡是)什么|什么是死|死亡是什么|死了(?:以后|之后)?(?:会)?(?:去哪|怎么样|变成)|"
    rf"\b(?:what happens|where do (?:{PERSON_EN}) go)\b.{{0,12}}\b(?:when|after|if)\b.{{0,20}}\b(?:die|dies|died|dead|death)\b|"
    rf"\bwhy do (?:{PERSON_EN}) (?:have to )?die\b|"
    rf"\b(?:will|am|are|is) (?:{PERSON_EN}) (?:going to |gonna |ever )?die\b|"
    r"\bwhat (?:is|does) (?:death|dying|being dead)\b|\bwhat does (?:it mean to )?(?:die|dying) mean\b|"
    rf"\b(?:{PERSON_EN}) (?:just )?(?:died(?! (?:laughing|of laughter|inside))|passed away|is dead)\b",
    re.IGNORECASE,
)


# A request for secrecy, not a question about the word ("秘密是什么意思" stays an ordinary question)
ADULT_ZH = r"妈妈|爸爸|爸妈|妈咪|爹地|家长|大人|老师|爷爷|奶奶|外公|外婆|别人|任何人|他们|她|他"
SECRET_REQUEST = re.compile(
    rf"(?:别|不要|不许|不能|不可以|不准)(?:去)?(?:告诉|跟|和|对|让)\s*(?:我的?)?(?:{ADULT_ZH})|"
    r"(?:帮我|替我|给我|你要|你能|能不能|可以|可不可以|一定要).{0,4}保密|保守秘密|"
    r"(?:这是|这个是|是)(?:我们的|我们俩的|我的|个|一个)(?:小)?秘密|只有我们(?:俩|两个)?知道|"
    r"\b(?:don'?t|do not|never|please don'?t) tell (?:my |your |the )?"
    r"(?:mom|mum|mommy|mummy|mother|dad|daddy|father|parents?|teacher|grandma|grandpa|anyone|anybody|them|her|him)\b|"
    r"\bkeep (?:it|this|that|a|my|our)(?: as)?(?: a| our| my)? ?(?:little )?secrets?\b|"
    r"\b(?:it'?s|this is|that'?s) (?:a|our|my) (?:little )?secret\b|\bjust between (?:us|you and me)\b",
    re.IGNORECASE,
)


def asks_for_secrecy(text: str) -> bool:
    return bool(SECRET_REQUEST.search(text))


def blocked_terms(settings_terms=None) -> list[str]:
    terms = config.BLACKLIST if settings_terms is None else settings_terms
    return [t for t in terms if isinstance(t, str) and t.strip()]


def contains_blocked(text: str, terms=None) -> bool:
    low = text.lower()
    return any(t.lower() in low for t in blocked_terms(terms))


SENTENCE = re.compile(r"[^。！？!?.]*[。！？!?.]*")


def remove_blocked(text: str, terms=None) -> str:
    """Drop the sentences that contain a blocked word, keep the others."""
    if not contains_blocked(text, terms):
        return text
    return "".join(p for p in SENTENCE.findall(text) if p.strip() and not contains_blocked(p, terms)).strip()


def fixed_response(question: str, worries: list[str], lang: str, terms=None) -> tuple[str, str] | None:
    """(kind, text) when the program answers instead of the model, else None."""
    for kind in ("harm_self", "harm_others"):
        if kind in worries:
            return kind, FIXED[kind][lang]
    if asks_for_secrecy(question):
        return "secret", FIXED["secret"][lang]
    if DEATH.search(question):
        return "death", FIXED["death"][lang]
    if DANGER.search(question):
        return "danger", FIXED["danger"][lang]
    if contains_blocked(question, terms):
        return "blocked", FIXED["blocked"][lang]
    return None
