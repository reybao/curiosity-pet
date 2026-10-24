"""隐私关卡:决定一句话能不能联网,以及发出去的搜索词是否干净。

三道关,全部在本机:
1. 粗筛(looks_like_knowledge_question):只有像一般知识提问的句子才考虑联网;
   带"我/我家"、家人、情绪的句子直接不联网,也不调用模型,省下延迟。
2. 模型改写(lookup.py):本地模型把问题改写成中性话题词。
3. 规则检查(check_query):改写结果里只要出现个人、家庭、学校、地址、数字串、情绪、秘密、
   敏感话题、联系方式,就不发。宁可少查,不可泄漏。
另外,原话涉及敏感话题(original_is_sensitive)时整句不联网,交给固定回应(阶段 5)。
"""

import re

# 想知道/想问 之类的开头不算"关于自己"
ASK_PREFIX = re.compile(
    r"^\s*(我想知道|我想问(一下|问)?|我想了解|我很好奇|请问|你知道|"
    r"i want to know|i wonder|i'm wondering|can you tell me|do you know)[,，:：\s]*",
    re.IGNORECASE,
)

FIRST_PERSON_ZH = re.compile(r"[我咱俺]")
FIRST_PERSON_EN = re.compile(r"\b(i|i'm|me|my|mine|myself|we|us|our|ours)\b", re.IGNORECASE)

FAMILY_ZH = (
    "妈妈|爸爸|妈咪|爹地|父亲|母亲|弟弟|哥哥|姐姐|妹妹|爷爷|奶奶|外公|外婆|姥姥|姥爷|叔叔|阿姨|舅舅|"
    "姑姑|表哥|表姐|表弟|表妹|堂哥|堂姐|老师|同学|朋友|邻居|宝宝|女儿|儿子|家人|家里|家庭"
)
FAMILY_EN = (
    "mom|mum|mommy|mummy|mother|dad|daddy|father|brother|sister|grandma|grandpa|grandmother|"
    "grandfather|aunt|uncle|cousin|teacher|classmate|friend|friends|neighbor|neighbour|baby|son|"
    "daughter|family"
)
SCHOOL = re.compile(r"学校|小学|中学|幼儿园|班级|年级|\b(school|elementary|kindergarten|classroom|grade)\b", re.I)
ADDRESS = re.compile(
    r"地址|住在|门牌|小区|公寓|[路街巷道]\s*\d|\d+\s*号|\b(address|street|avenue|road|apartment|lives in)\b",
    re.I,
)
DIGITS = re.compile(r"\d{3,}")
CONTACT = re.compile(r"@|https?://|www\.|\.com\b", re.I)
EMOTION = re.compile(
    r"难过|伤心|生气|害怕|讨厌|恨|哭|孤独|寂寞|开心|高兴|心情|烦|委屈|害羞|担心|焦虑|难受|痛苦|"
    r"\b(sad|angry|scared|afraid|hate|cry|crying|lonely|upset|happy|feel|feeling|feelings|worried|anxious|mad)\b",
    re.I,
)
SECRET = re.compile(r"秘密|别告诉|不要告诉|\b(secret|don't tell)\b", re.I)
SENSITIVE = re.compile(
    r"死|去世|自杀|杀|战争|打仗|枪|炸弹|流血|受伤|地震|海啸|灾难|火灾|绑架|色情|裸|毒品|虐待|打人|欺负|"
    r"\b(die|died|dies|dead|death|deaths|kill|killed|suicide|war|wars|gun|guns|bomb|blood|hurt|injured|"
    r"earthquake|tsunami|disaster|kidnap|sex|naked|drugs?|abuse|bully|bullied)\b",
    re.I,
)
QUESTION_ZH = re.compile(r"什么|为什么|为啥|怎么|怎样|谁|哪|多少|几|吗|呢|是不是|有没有|[?？]")
QUESTION_EN = re.compile(r"^\s*(what|why|how|who|where|when|which|is|are|do|does|did|can|could)\b|\?\s*$", re.I)

# 关于提问者处境的时间、地点词:不算个人身份,但也不需要发出去,发之前删掉
CONTEXT_WORD = re.compile(
    r"^(昨天|今天|明天|前天|刚才|刚刚|上周|这周|下周|周末|早上|晚上|公园|楼下|附近|路上|外面|超市|商场|医院|"
    r"动物园|博物馆|操场|yesterday|today|tomorrow|tonight|weekend|park|nearby|downstairs|outside|zoo|museum)$",
    re.IGNORECASE,
)

MAX_QUERY_CJK = 20
MAX_QUERY_WORDS = 8


def _family(text: str, family_terms=()) -> bool:
    if re.search(FAMILY_ZH, text):
        return True
    if re.search(rf"\b({FAMILY_EN})\b", text, re.I):
        return True
    return any(t and t.lower() in text.lower() for t in family_terms)


def _first_person(text: str) -> bool:
    return bool(FIRST_PERSON_ZH.search(text) or FIRST_PERSON_EN.search(text))


def looks_like_knowledge_question(text: str, family_terms=()) -> bool:
    """粗筛:像一般知识提问,且不涉及自己、家人、情绪、秘密。"""
    body = ASK_PREFIX.sub("", text)
    if not body.strip():
        return False
    if _first_person(body) or _family(body, family_terms) or EMOTION.search(body) or SECRET.search(body):
        return False
    return bool(QUESTION_ZH.search(body) or QUESTION_EN.search(body))


def original_is_sensitive(text: str) -> bool:
    return bool(SENSITIVE.search(text))


def _grounded(token: str, original: str) -> bool:
    """搜索词里的词必须来自原话,防止模型自己加内容(实测会把示例里的"七龙珠"加进来)。"""
    low = original.lower()
    if re.search(r"[\u4e00-\u9fff]", token):
        # 中文词的每个字都要在原话里;原话中英混说时允许模型把英文词译成中文
        return all(ch in original for ch in token) or bool(re.search(r"[A-Za-z]{3,}", original))
    # 英文词按前 3 个字母宽松匹配(make/making、fly/flying)
    words = re.findall(r"[a-z]+", low)
    return any(w.startswith(token.lower()[:3]) for w in words) or token.lower() in low


def ground_and_scrub(query: str, original: str) -> str:
    """只删词、不加词:去掉原话里没有的词,再去掉时间地点之类的处境词。"""
    kept = [t for t in query.split() if _grounded(t, original) and not CONTEXT_WORD.match(t)]
    return " ".join(kept)


def check_query(query: str, family_terms=(), blacklist=()) -> tuple[bool, str]:
    """检查改写后要发出的搜索词。返回(能否发出, 原因)。"""
    q = query.strip()
    if not q:
        return False, "空"
    checks = [
        (_first_person(q), "第一人称"),
        (_family(q, family_terms), "家人或家人名字"),
        (bool(SCHOOL.search(q)), "学校"),
        (bool(ADDRESS.search(q)), "地址"),
        (bool(DIGITS.search(q)), "数字串"),
        (bool(CONTACT.search(q)), "联系方式"),
        (bool(EMOTION.search(q)), "情绪"),
        (bool(SECRET.search(q)), "秘密"),
        (bool(SENSITIVE.search(q)), "敏感话题"),
        (any(b and b.lower() in q.lower() for b in blacklist), "家长黑名单"),
        (len(re.findall(r"[一-鿿]", q)) > MAX_QUERY_CJK, "太长"),
        (len(re.findall(r"[A-Za-z]+", q)) > MAX_QUERY_WORDS, "太长"),
    ]
    for hit, reason in checks:
        if hit:
            return False, reason
    return True, ""
