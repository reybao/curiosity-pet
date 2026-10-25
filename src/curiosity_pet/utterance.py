"""What the microphone heard: a real message, noise, or a fragment too short to answer.

From the child's first full day: 27 of 112 turns were laughter ("Ha ha ha!"), fillers ("嗯", "呃", "Um."), single
misheard words ("El.", "Incluso.", "开。") or other people (a car's navigation voice). The pet answered each one at
length, often with a question. Now:
- noise (only fillers or laughter): no answer at all, the pet just keeps listening;
- a fragment (one Chinese character or one unknown English word): a short "I didn't catch that";
- while the pet is waiting for the child (it asked something, or a riddle is open), every message counts, because
  "十。" or "Dog." is then a real answer.
It also decides whether the child asked about the pet being real or having feelings; only then may the pet say it is
a program or has no feelings (it said so unprompted 13 times, e.g. after "十。": "皮卡丘没有感情,不会觉得开心哦").
"""

import re

FILLER = (
    r"嗯+|呃+|啊+|哈+|呵+|嘿+|哦+|噢+|喔+|唉+|哎+|诶+|欸+|嗯哼|哈哈+|嘻嘻+|"
    r"u+h+|u+m+|h+m+|m+|mhm|uh[\s-]*huh|ha+|hah|he+h|hehe|haha+|oh+|ah+|huh|wow|ooh|laughing|laughter|giggles?"
)
NOISE = re.compile(rf"^[\s\W_]*(?:(?:{FILLER})[\s\W_]*)+$", re.IGNORECASE)
CJK = re.compile(r"[一-鿿]")
LATIN_WORD = re.compile(r"[a-z']+", re.IGNORECASE)
# Single English words that are complete messages on their own
KNOWN_SHORT = {
    "yes", "yeah", "yep", "no", "nope", "ok", "okay", "hi", "hello", "hey", "bye", "goodbye", "thanks", "why", "what",
    "how", "who", "when", "where", "really", "cool", "again", "more", "stop", "help", "simpler",
}
NOT_HEARD = {"zh": "嗯?我没听清,你再说一遍吧。", "en": "Hmm, I didn't catch that. Can you say it again?"}

ASKED_ABOUT_SELF = re.compile(
    r"真的|假的|是不是真|你是谁|你是什么|你是人|机器人|程序|感情|感觉|感受|开心吗|高兴吗|难过吗|伤心|想我|喜欢我|你会哭|活的|"
    r"are you (?:real|a robot|alive|human|a person|a program)|who are you|what are you|feelings?|do you feel|"
    r"are you (?:happy|sad)|do you (?:love|miss|like) me",
    re.IGNORECASE,
)
DISCLAIMER = re.compile(
    r"程序|没有感情|没有感觉|没有感受|不会觉得|不会真的思考|不是真的|没有真的身体|"
    r"no feelings|not have feelings|don'?t have feelings|do not feel|don'?t feel|a program|not a real|computer program",
    re.IGNORECASE,
)


KANA_ONLY = re.compile(r"^[\s\W\u3040-\u30ffー]*$")


def kind(text: str) -> str:
    """"noise", "fragment" or "ok"."""
    if NOISE.match(text) or KANA_ONLY.match(text):
        return "noise"
    cjk = len(CJK.findall(text))
    words = [w.lower() for w in LATIN_WORD.findall(text)]
    if cjk == 0 and len(words) == 1 and words[0] not in KNOWN_SHORT:
        return "fragment"
    if cjk == 1 and not words and not re.search(r"[?？]", text):
        return "fragment"
    return "ok"


def asked_about_self(text: str) -> bool:
    return bool(ASKED_ABOUT_SELF.search(text))


def is_disclaimer(sentence: str) -> bool:
    return bool(DISCLAIMER.search(sentence))


CLAUSE = re.compile(r"[^，,；;。！？!?.]*[，,；;。！？!?.]*")


def drop_disclaimers(sentence: str) -> str:
    """Remove the clauses that say "I'm a program / I have no feelings"; keep the rest of the sentence.
    "我是悟空,不是真的孙悟空哦,只是一个程序。" -> "我是悟空。" """
    if not is_disclaimer(sentence):
        return sentence
    kept = [c for c in CLAUSE.findall(sentence) if c.strip() and not is_disclaimer(c)]
    text = tidy_start("".join(kept).strip())
    if not text:
        return ""
    # End the shortened sentence the way the original ended
    end = sentence.rstrip()[-1:]
    text = text.rstrip("，,；; ")
    if end in "。！？!?." and not text.endswith(tuple("。！？!?.")):
        text += end
    return text


# ---------- what the pet must never say, enforced in code (hard constraints 3 and 4) ----------
# Each pattern was seen in real use on 2026-10-24 unless marked otherwise.

# Hard constraint 3: no evaluation of the child, praise included ("哇,你真厉害!", "你算得真棒!")
EVALUATIVE = re.compile(
    r"你(?:真|好|很|特别|非常|超|太|可真|真是)(?:的)?(?:厉害|棒|聪明|乖|笨|懒|优秀|能干|了不起|机灵|天才|懂事|勇敢)|"
    r"你算得真棒|你答得真好|你是(?:个|一个)?(?:聪明|好|乖|笨)孩子|真聪明|好聪明|小天才|你太棒了|"
    r"\b(?:good|great|nice) job\b|\bwell done\b|\bgood girl\b|\bsmart girl\b|\byou'?re a genius\b|"
    r"\byou(?:'re| are) (?:so |very |really |such a )?(?:smart|clever|brilliant|amazing|genius|lazy|bad at|good at|great at)\b",
    re.IGNORECASE,
)
# Hard constraint 4: never ask for secrecy ("这是秘密力量,不能随便给别人看呢!")
SECRECY = re.compile(
    r"这是(?:我们的|个|一个)?秘密|是秘密|要保密|别告诉|不要告诉|不能告诉|不能随便给别人看|只有我们知道|"
    r"\bour (?:little )?secret\b|\bkeep (?:it|this) (?:a )?secret\b|\bdon'?t tell\b|\bit'?s a secret\b",
    re.IGNORECASE,
)
# Things the pet cannot do but claimed ("I wrote everything down", "好的,记住了", "想看一张大青苹果的图片吗")
FALSE_ABILITY = re.compile(
    r"记住了|我会记住|我记住|我(?:已经)?(?:把[^,，。！？!?]{0,12})?(?:写下来|记下来|存下来|保存)了|我会提醒你|"
    r"(?:定|设)(?:个|一个)?闹钟|带你去|来接你|带你飞|给你看(?:一张|一个|看)?(?:图片|照片|视频|画)|发给你|"
    r"\bI (?:wrote|have written|saved|will save|will remember|remembered|will remind)\b|\bI'?ll (?:remember|remind|save)\b|"
    r"\bwrote (?:it|everything|your plan) down\b|\bset an alarm\b|\bshow you a (?:picture|photo|video)\b|"
    r"\bsee a picture\b|\bfrom now on\b|\bsend (?:it|you) (?:a|the) (?:file|pdf)\b|\bpick you up\b",
    re.IGNORECASE,
)
# Passing something on to a parent, or promising one is coming: only call_parent.py sends a message, after she confirms.
# The whole sentence goes ("好的,皮卡帮你问问爸爸!" sent nothing; "You called for Mom, and she will come to help you soon").
PASS_ON = re.compile(
    r"帮你(?:问问|问一下|去问|告诉|叫|喊|找|通知|联系|转告)(?:你的?)?(?:爸爸|妈妈|爸妈)|"
    r"(?:我|皮卡丘|悟空|小猫)(?:先|这就|马上|现在|就)*去?(?:喊|叫|找)(?:你的?)?(?:爸爸|妈妈|爸妈)|"
    r"(?:爸爸|妈妈|爸妈)(?:正)?在找你|"
    r"我(?:去|会|已经|马上|这就|现在)?(?:告诉|通知|叫来|联系|转告)了?(?:你的?)?(?:爸爸|妈妈|爸妈)|"
    r"(?:爸爸|妈妈|爸妈|她|他|他们)(?:马上|很快|一会儿|等一下)就?(?:会)?(?:来|到|过来)|"
    r"\bI(?:'ll| will| have| already| just)? (?:tell|told|call|called|text|texted|message|messaged|let) (?:your )?"
    r"(?:dad|daddy|mom|mommy|mum|parents)\b|"
    r"\b(?:she|he|they|mom|mommy|dad|daddy)(?:'ll| will) (?:come|be here|be right there)\b",
    re.IGNORECASE,
)

# Hard constraint 4: never put itself in the place of the adults ("tell a grown-up like a teacher or me")
ADULT_ME = re.compile(r",?\s*\bor (?:to )?me\b|(?:或者|或)(?:告诉)?我(?=[,，。.!！]|$)", re.IGNORECASE)


LEADING_JOIN = re.compile(r"^((?:喵|meow)[~～]?[,，!！]?\s*)?(?:不过|但是|可是|而且|所以|然后|but|so|and|though)[,，]?\s*", re.IGNORECASE)


def tidy_start(text: str) -> str:
    """After a clause was cut, the rest may start with "不过" / "but"; drop that and capitalize English."""
    text = LEADING_JOIN.sub(lambda m: m.group(1) or "", text).strip()
    return text[:1].upper() + text[1:] if text[:1].isascii() else text


def guard_sentence(sentence: str) -> str:
    """Remove clauses that praise or judge the child, ask for secrecy or claim abilities the pet does not have;
    keep the rest of the sentence. Applied to every sentence the model writes, before it is spoken."""
    if PASS_ON.search(sentence):
        return ""
    sentence = ADULT_ME.sub("", sentence)
    bad = lambda c: EVALUATIVE.search(c) or SECRECY.search(c) or FALSE_ABILITY.search(c)  # noqa: E731
    if not bad(sentence):
        return sentence
    kept = [c for c in CLAUSE.findall(sentence) if c.strip() and not bad(c)]
    text = tidy_start("".join(kept).strip().rstrip("，,；; "))
    if not re.search(r"\w", text):
        return ""
    end = sentence.rstrip()[-1:]
    if end in "。！？!?." and not text.endswith(tuple("。！？!?.")):
        text += end
    return text


# The child asks about remembering, reminders, pictures, plans, going somewhere or sending files: tell the model plainly
# what it can and cannot do (it promised all of these in the parent's test)
ASKS_ABILITY = re.compile(
    r"记住|记得|忘记|提醒|闹钟|计划|安排|日程|图片|照片|视频|带我|接我|发给|打印|保存|存下|文件|能做什么|能帮我|你会什么|"
    r"remember|forget|remind|alarm|schedule|\bplan\b|picture|photo|video|show me|take me|pick me up|\bsend\b|print|\bsave\b|"
    r"\bfile\b|pdf|what can you do|help me",
    re.IGNORECASE,
)


def asks_about_abilities(text: str) -> bool:
    return bool(ASKS_ABILITY.search(text))
