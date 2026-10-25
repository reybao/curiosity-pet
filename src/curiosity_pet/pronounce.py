"""Pronunciation fixes applied just before speech synthesis; the text shown on the iPad stays as written.

Found by the parent in real use:
- English "Pika" was read as the animal pika ("pie-ka"), and "Pikachu" was unknown to the English G2P. Both get
  explicit phonemes in misaki's link syntax, [word](/phonemes/), which the Kokoro pipeline passes to the G2P.
- Japanese kana and Korean hangul inside an answer ("用日语写是“クリリン”") cannot be voiced by the Chinese or English
  G2P (they came out as silence), so they are removed from the voice text together with the quotes or brackets
  around them. English names the G2P does not know (Vegeta, Bulma) are read by the espeak fallback (tts.py).
- Chinese polyphones: "很长很长" was read zhǎng (grow) instead of cháng (long), and the 传 in "凡人修仙传" chuán
  instead of zhuàn (a story or biography in a title). The G2P reads a lone 长 as zhǎng and a lone 传 as chuán, so a
  lone character in a cháng / zhuàn position is swapped for a homophone (常, 赚) for the voice only. Compound words the
  G2P already reads right (长城, 长颈鹿, 成长, 校长, 水浒传, 传说, 流传) are left alone.
"""

import re

EN_PHONEMES = {"pikachu": "pˈikətʃu", "pika": "pˈikə"}
EN_WORDS = re.compile(r"(?<![\w\[/])(" + "|".join(EN_PHONEMES) + r")(?![\w\]])", re.IGNORECASE)


def fix_en(text: str) -> str:
    return EN_WORDS.sub(lambda m: f"[{m.group(1)}](/{EN_PHONEMES[m.group(1).lower()]}/)", text)


# A lone 长 after these reads cháng ("很长", "太长了", "又长又细", "腿好长")
DEGREE = {
    "很", "太", "好", "真", "多", "最", "更", "特别", "非常", "那么", "这么", "超", "挺", "有点", "有点儿", "不", "越来越",
    "比较", "又", "也", "还", "够", "这样", "那样", "极", "老",
}
# ... unless it is followed by what makes it zhǎng, to grow ("又长高了", "长大", "长出叶子", "长得像")
GROW_NEXT = {"大", "高", "出", "出来", "出去", "胖", "成", "得", "满", "个子", "牙"}
# These follow either meaning: zhǎng ("长了", "长在树上") unless a degree word comes first ("太长了")
GROW_WEAK = {"了", "在", "着", "过", "到", "起来", "回来"}
# Multi-character words the G2P reads with zhǎng although they mean long
CHANG_WORDS = {"长时间": "常时间", "多长": "多常", "太长": "太常", "很长": "很常", "好长": "好常"}
# A lone 传 after these is the verb chuán ("我传给你", "然后传球")
PASS_PREV = {
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "快", "再", "来", "去", "都", "也", "还", "会", "能", "要",
    "不", "没", "别", "把", "被", "给", "往", "向", "互相", "然后", "就", "又", "一直", "正在", "在", "可以", "会不会",
}
# What may follow a title ending in 传
TITLE_NEXT = {"》", "里", "中", "里面", "的", "讲", "是", "说", "吗", "呢", "吧", "啊", "呀", "这", "那", "和", "跟", "很"}
PUNCT = re.compile(r"^[\s。.!！?？,，;；:：、“”\"'‘’）)》]+$")


def _tokens(text: str) -> list[tuple[str, str]]:
    import jieba.posseg as pseg

    out = []
    for t in pseg.cut(text):
        # jieba sometimes joins 传 with the next word ("修仙/传里"); split it back
        if len(t.word) == 2 and t.word[0] == "传" and t.word[1] in "里中":
            out += [("传", "n"), (t.word[1], "f")]
        else:
            out.append((t.word, t.flag))
    return out


def _is_chang(prev: str, nxt: tuple[str, str] | None) -> bool:
    if nxt is not None and nxt[0] in GROW_NEXT:
        return False
    if prev in DEGREE:
        return True
    if nxt is not None and nxt[0] in GROW_WEAK:
        return False
    if nxt is None or PUNCT.match(nxt[0]):
        return True  # "头发长。"
    return nxt[1].startswith("n")  # "长鼻子", "长裙子"


def _is_zhuan(prev: tuple[str, str] | None, nxt: tuple[str, str] | None) -> bool:
    if nxt is not None and nxt[0] == "》":
        return True
    if prev is None or prev[0] in PASS_PREV or PUNCT.match(prev[0]):
        return False
    if prev[0] in ("前", "后", "外", "正", "别", "自", "列"):
        return True  # 前传, 后传, 外传 ...
    if not (prev[1].startswith("n") or prev[1] in ("f", "x")):
        return False
    return nxt is None or bool(PUNCT.match(nxt[0])) or nxt[0] in TITLE_NEXT


def fix_zh(text: str) -> str:
    if "长" not in text and "传" not in text:
        return text
    toks = _tokens(text)
    out = []
    for i, (word, flag) in enumerate(toks):
        prev = toks[i - 1] if i > 0 else None
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if word == "长" and _is_chang(prev[0] if prev else "", nxt):
            word = "常"
        elif word == "传" and _is_zhuan(prev, nxt):
            word = "赚"
        elif word in CHANG_WORDS:
            word = CHANG_WORDS[word]
        out.append(word)
    return "".join(out)


UNREADABLE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+")
EMPTY_WRAP = re.compile(r"[“\"「『（(《‘'][\s,，、]*[”\"」』）)》’']")


def strip_unreadable(text: str) -> str:
    if not UNREADABLE.search(text):
        return text
    text = EMPTY_WRAP.sub("", UNREADABLE.sub("", text))
    return re.sub(r"\s{2,}", " ", text).strip()


def fix(text: str, lang: str) -> str:
    text = strip_unreadable(text)
    return fix_zh(text) if lang == "zh" else fix_en(text)
