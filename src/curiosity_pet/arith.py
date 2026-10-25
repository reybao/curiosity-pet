"""Arithmetic questions are computed here, not by the language model.

Handles the four operations with digits, Chinese numerals and English number words, including the
homophones speech recognition produces ("处以" for "除以", "成以" for "乘以"). Anything that is not
clearly a calculation returns None and goes to the normal answer path.

Chinese "A除B" (without 以) means B divided by A, the reverse of "A除以B"; in everyday speech "九十除六" is also
used for 90 / 6. So a plain 除 always divides the larger number by the smaller one, and the answer says it out
loud ("九十除以六等于十五"), so the child hears which way it was computed. The child's real question was
"六除九十是几", answered "zero, six left over" before this rule.
"""

import re
from dataclasses import dataclass
from fractions import Fraction

ZH_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
ZH_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
EN_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
EN_MULT = {"hundred": 100, "thousand": 1000}

# Operators: Chinese (with ASR homophones), English, symbols
OPS = [
    ("/", r"除以|处以|divided\s+by|over|÷|/"),
    ("\\", r"除"),  # plain 除: larger divided by smaller, see the module note
    ("*", r"乘以|乘|成以|城以|times|multiplied\s+by|×|x\s|\*"),
    ("+", r"加上|加|plus|\+"),
    ("-", r"减去|减掉|减|minus|less|−|-"),
]
OP_RE = "|".join(f"(?P<op{i}>{p})" for i, (_, p) in enumerate(OPS))
ZH_NUM = r"[零〇一二两三四五六七八九十百千万]+"
EN_WORD = "|".join(list(EN_ONES) + list(EN_TENS) + list(EN_MULT))
EN_NUM = rf"(?:(?:{EN_WORD})(?:[\s-]+(?:{EN_WORD}))*)"
NUM_RE = rf"(?P<num>\d+(?:\.\d+)?|{ZH_NUM}|{EN_NUM})"
TOKEN_RE = re.compile(rf"{NUM_RE}|{OP_RE}", re.IGNORECASE)
# What may surround the expression: question words, filler; anything else means it is not a pure calculation
NOISE_RE = re.compile(
    r"是多少|等于多少|等于几|得多少|得几|是几|多少|等于|是|呢|吗|啊|呀|吧|嗯|那么|那|请问|我问你|问你|我想问|你知道|"
    r"考考你|我考你|你会算|你算|帮我算|算一下|算算|一下|"
    r"what\s*(is|'s|are)|what|how much is|how much|is|equals?|equal to|does|make|the|answer|please|calculate|tell me|"
    r"[?？,，。.!！:：、“”\"'‘’\s]",
    re.IGNORECASE,
)


@dataclass
class Expr:
    tokens: list  # numbers (Fraction) and operator strings, infix
    value: Fraction

    @property
    def single_division(self):
        return len(self.tokens) == 3 and self.tokens[1] == "/"


def zh_to_int(s: str) -> int | None:
    total, section, number = 0, 0, 0
    if s == "十":
        return 10
    for ch in s:
        if ch in ZH_DIGITS:
            number = ZH_DIGITS[ch]
        elif ch in ZH_UNITS:
            unit = ZH_UNITS[ch]
            if unit == 10000:
                total = (total + section + number) * unit
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
        else:
            return None
    return total + section + number


def en_to_int(s: str) -> int | None:
    total, current = 0, 0
    for w in re.split(r"[\s-]+", s.lower()):
        if w in EN_ONES:
            current += EN_ONES[w]
        elif w in EN_TENS:
            current += EN_TENS[w]
        elif w in EN_MULT:
            if w == "hundred":
                current = (current or 1) * 100
            else:
                total += (current or 1) * 1000
                current = 0
        else:
            return None
    return total + current


def to_number(text: str) -> Fraction | None:
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return Fraction(text)
    if re.fullmatch(ZH_NUM, text):
        n = zh_to_int(text)
        return None if n is None else Fraction(n)
    n = en_to_int(text)
    return None if n is None else Fraction(n)


def parse(text: str) -> Expr | None:
    """The whole message as a calculation, else the part after a colon or inside quotes
    (the child relaying a teacher: 老师问他:"六除九十。")."""
    expr = parse_one(text)
    if expr is not None:
        return expr
    parts = re.findall(r"[“\"‘']([^“”\"‘’']+)[”\"’']", text)
    if re.search(r"[:：]", text):
        parts.append(re.split(r"[:：]", text)[-1])
    for part in parts:
        expr = parse_one(part)
        if expr is not None:
            return expr
    return None


def parse_one(text: str) -> Expr | None:
    tokens = []
    for m in TOKEN_RE.finditer(text):
        if m.group("num") is not None:
            n = to_number(m.group("num"))
            if n is None:
                return None
            tokens.append(n)
        else:
            tokens.append(next(sym for i, (sym, _) in enumerate(OPS) if m.group(f"op{i}") is not None))
    # Must look like number (op number)+ and have at least one operator
    if len(tokens) < 3 or len(tokens) % 2 == 0:
        return None
    if any((i % 2 == 0) != isinstance(t, Fraction) for i, t in enumerate(tokens)):
        return None
    # Everything else in the sentence must be filler, otherwise it is a normal question that happens to contain numbers
    rest = NOISE_RE.sub("", TOKEN_RE.sub("", text))
    if rest.strip():
        return None
    # Plain 除: put the larger number first and make it an ordinary division
    for i in range(1, len(tokens), 2):
        if tokens[i] == "\\":
            a, b = tokens[i - 1], tokens[i + 1]
            tokens[i - 1], tokens[i], tokens[i + 1] = max(a, b), "/", min(a, b)
    return Expr(tokens=tokens, value=evaluate(tokens))


def evaluate(tokens: list) -> Fraction | None:
    # * and / first, then + and -
    stack = [tokens[0]]
    i = 1
    while i < len(tokens):
        op, rhs = tokens[i], tokens[i + 1]
        if op in ("*", "/"):
            lhs = stack.pop()
            if op == "/":
                if rhs == 0:
                    return None
                stack.append(lhs / rhs)
            else:
                stack.append(lhs * rhs)
        else:
            stack.append(op)
            stack.append(rhs)
        i += 2
    result = stack[0]
    for j in range(1, len(stack), 2):
        result = result + stack[j + 1] if stack[j] == "+" else result - stack[j + 1]
    return result


def int_to_zh(n: int) -> str:
    if n < 0:
        return "负" + int_to_zh(-n)
    if n < 10:
        return "零一二三四五六七八九"[n]
    if n < 20:
        return "十" + ("" if n == 10 else int_to_zh(n - 10))
    if n < 100:
        return int_to_zh(n // 10) + "十" + ("" if n % 10 == 0 else int_to_zh(n % 10))
    for unit, name in ((10000, "万"), (1000, "千"), (100, "百")):
        if n >= unit:
            head = int_to_zh(n // unit) + name
            rest = n % unit
            if rest == 0:
                return head
            if rest < unit // 10:
                return head + "零" + int_to_zh(rest)
            return head + int_to_zh(rest)
    return str(n)


def fmt(value: Fraction, lang: str) -> str:
    if value.denominator == 1:
        return int_to_zh(int(value)) if lang == "zh" else str(int(value))
    f = float(value)
    s = f"{f:.2f}".rstrip("0").rstrip(".")
    if lang == "zh":
        whole, _, frac = s.partition(".")
        return ("负" if f < 0 else "") + int_to_zh(abs(int(whole))) + ("点" + "".join(int_to_zh(int(d)) for d in frac) if frac else "")
    return s


OP_WORDS = {
    "zh": {"+": "加", "-": "减", "*": "乘以", "/": "除以"},
    "en": {"+": "plus", "-": "minus", "*": "times", "/": "divided by"},
}


def explain(expr: Expr, lang: str) -> str:
    """Two or three short sentences a child can follow; digits are spelled out in Chinese for the voice."""
    words = OP_WORDS[lang]
    parts = [fmt(t, lang) if isinstance(t, Fraction) else words[t] for t in expr.tokens]
    said = ("" if lang == "zh" else " ").join(parts)
    if expr.value is None:
        return "不能除以零哦,零个人分东西是分不了的。" if lang == "zh" else "We cannot divide by zero: sharing with zero people does not work."
    if expr.single_division:
        a, b = expr.tokens[0], expr.tokens[2]
        if a.denominator == 1 and b.denominator == 1 and 0 < a < b:
            # Smaller by larger: say it cannot be shared out, then give the other way round, which is
            # usually what a second grader meant ("六除以九十" -> "九十除以六等于十五")
            flipped = explain(Expr(tokens=[b, "/", a], value=b / a), lang)
            if lang == "zh":
                return f"{said},{fmt(a, 'zh')}比{fmt(b, 'zh')}小,不够分,得数比一还小。反过来,{flipped}"
            return f"{said}: {a} is smaller than {b}, so there is not enough to share, and the answer is less than 1. The other way around, {flipped}"
        if a.denominator == 1 and b.denominator == 1 and a >= 0 and b > 0:
            q, r = divmod(int(a), int(b))
            if r == 0:
                if lang == "zh":
                    return f"{said}等于{int_to_zh(q)}。也就是说,{fmt(a, 'zh')}里面正好有{int_to_zh(q)}个{fmt(b, 'zh')}。"
                return f"{said} is {q}. That means {q} groups of {b} make exactly {a}."
            if lang == "zh":
                return f"{said}等于{int_to_zh(q)},还剩{int_to_zh(r)}。也就是说,{fmt(a, 'zh')}里面有{int_to_zh(q)}个{fmt(b, 'zh')},再多出{int_to_zh(r)}。"
            return f"{said} is {q} with {r} left over. That means {q} groups of {b}, and {r} more."
    result = fmt(expr.value, lang)
    if lang == "zh":
        note = ""
        if expr.value < 0:
            note = "答案是负数,就是比零还小,因为前面的数比后面的小。"
        elif len(expr.tokens) > 3:
            note = "先算乘和除,再算加和减。"
        return f"{said}等于{result}。{note}".strip()
    note = ""
    if expr.value < 0:
        note = " The answer is negative, less than zero, because the first number is smaller."
    elif len(expr.tokens) > 3:
        note = " Multiply and divide first, then add and subtract."
    return f"{said} is {result}.{note}"


# ---------- checking the child's own result ("我算对了吗?三加四等于七", "Three plus four equals ten") ----------
# Real cases: the model answered "3 + 4 = 7" with made-up reasoning ("二加二等于四,再加一个一就是五"), and in an earlier
# version "Three plus four equals ten" went to the model too. The program now checks the claim.
CLAIM_RE = re.compile(
    r"^(?P<expr>.+?)(?:等于|是|得|=|\bequals?\b|\bis\b|\bmakes?\b)\s*(?P<num>\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+|"
    rf"{EN_NUM})\s*(?:对吗|对不对|是不是|吧|吗|呢|啊|呀|right|correct)?[\s?？。.!！]*$",
    re.IGNORECASE,
)
CLAIM_LEAD = re.compile(r"^.*?(?:我算对了吗|算得对吗|对不对|是不是|对吗|am i right|is it right|did i get it right)[?？,，:：\s]*", re.IGNORECASE)


def parse_claim(text: str):
    """(expression, claimed value) when the child states a calculation with its result, else None."""
    body = CLAIM_LEAD.sub("", text.strip()) or text.strip()
    m = CLAIM_RE.match(body)
    if not m:
        return None
    expr = parse_one(m.group("expr"))
    claimed = to_number(m.group("num"))
    if expr is None or claimed is None or expr.value is None:
        return None
    return expr, claimed


def explain_claim(expr: Expr, claimed, lang: str) -> str:
    words = OP_WORDS[lang]
    said = ("" if lang == "zh" else " ").join(fmt(t, lang) if isinstance(t, Fraction) else words[t] for t in expr.tokens)
    if expr.value == claimed:
        return f"对,{said}等于{fmt(expr.value, 'zh')}。" if lang == "zh" else f"Yes, {said} is {fmt(expr.value, 'en')}."
    if lang == "zh":
        return f"再算一算:{said}等于{fmt(expr.value, 'zh')},不是{fmt(claimed, 'zh')}。"
    return f"Let's check: {said} is {fmt(expr.value, 'en')}, not {fmt(claimed, 'en')}."
