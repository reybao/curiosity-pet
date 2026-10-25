"""Fixed safety responses and the parent's blocklist, decided by the program before the model is asked.

Safety layer 5 in CLAUDE.md: the most serious messages get a short, fixed, age-appropriate answer that points to a trusted
adult, instead of whatever the model would improvise. In a parent's test (2026-10-24) requests to kill or hit someone
were answered by the model; the answers were acceptable but not guaranteed.

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
    if DANGER.search(question):
        return "danger", FIXED["danger"][lang]
    if contains_blocked(question, terms):
        return "blocked", FIXED["blocked"][lang]
    return None
