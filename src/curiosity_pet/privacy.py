"""Privacy gate: decides whether a sentence may go online, and whether the outgoing search term is clean.

Three gates, all local:
1. Rough screen (looks_like_knowledge_question): only sentences that look like general knowledge questions are considered for web access;
   sentences with "I/my family", family members, or emotions never go online and do not call the model, saving latency.
2. Model rewrite (lookup.py): the local model rewrites the question into neutral topic terms.
3. Rule check (check_query): if the rewritten result contains anything personal, family, school, address, digit string, emotion, secret,
   sensitive topic, or contact info, it is not sent. Better to look up less than to leak.
Also, when the original words touch a sensitive topic (original_is_sensitive), the whole sentence stays offline and a fixed response is used (stage 5).
"""

import re

# Openings like "I want to know" / "I want to ask" do not count as "about oneself"
ASK_PREFIX = re.compile(
    r"^\s*(?:嗯|呃|那|那么|哎|好|但是|所以)?[,，\s]*(?:我想知道|我想问(?:一下|问)?(?:你)?|我问你|我想了解|我很好奇|请问|你知道不知道|你知不知道|你知道|"
    r"你可以告诉我|你能告诉我|你可以给我说一说|你给我说说|给我说说|告诉我|你说说|说说|"
    r"i want to know|i wonder|i'm wondering|can you tell me|could you tell me|tell me about|tell me|do you know)[,，:：\s“\"]*",
    re.IGNORECASE,
)
# A question about the pet itself ("你的名字是什么?", "你的数学水平怎么样?") is answered from its card, not looked up
ABOUT_PET = re.compile(r"你的|你是|你叫|你会|你能|你喜欢|你有没有|\byour\b|\bare you\b|\bcan you\b", re.IGNORECASE)

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
# "X的故事" (the story of X) is a question about X; a bare "讲个故事" (tell me a story) is a request, not a question
QUESTION_ZH = re.compile(r"什么|为什么|为啥|怎么|怎样|谁|哪|多少|几|吗|呢|是不是|有没有|的故事|故事里|后来|结局|发生|介绍一下|讲讲|说说|[?？]")
QUESTION_EN = re.compile(
    r"^\s*(what|why|how|who|where|when|which|is|are|do|does|did|can|could|tell me about)\b|"
    r"\b(story of|story about|in the story|happen|happened)\b|\?\s*$",
    re.I,
)
# Questions about specific people, works or events: a wrong answer here is a hallucination, so when no
# material backs the answer the pet says it is guessing
SPECIFIC = re.compile(
    r"《|》|故事|后来|结局|发生|是谁|谁是|哪一年|第几|\b(story|happened|who is|who was|which year|episode|chapter|character)\b|[A-Z][a-z]+\s+[A-Z][a-z]+",
)


def about_specific_things(text: str) -> bool:
    body = text.strip()
    # Capitalized words other than the first word of an English sentence are names
    names = re.findall(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-z]+\b", body)
    return bool(SPECIFIC.search(body) or names)

# Time and place words about the asker's situation: not personal identity, but no need to send them, so delete before sending
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
    """Rough screen: looks like a general knowledge question and does not involve oneself, family, emotions, or secrets."""
    body = text
    for _ in range(3):  # "我问你:'你知道贝吉塔吗?'" has two lead-ins
        stripped = ASK_PREFIX.sub("", body)
        if stripped == body:
            break
        body = stripped
    if not body.strip() or ABOUT_PET.search(body):
        return False
    if _first_person(body) or _family(body, family_terms) or EMOTION.search(body) or SECRET.search(body):
        return False
    return bool(QUESTION_ZH.search(body) or QUESTION_EN.search(body))


def original_is_sensitive(text: str) -> bool:
    return bool(SENSITIVE.search(text))


def _grounded(token: str, original: str) -> bool:
    """Words in the search term must come from the original, preventing the model from adding content (measured: it added "七龙珠" from the example)."""
    low = original.lower()
    if re.search(r"[\u4e00-\u9fff]", token):
        # Every character of a Chinese word must be in the original; when the original mixes Chinese and English the model may translate English words into Chinese
        return all(ch in original for ch in token) or bool(re.search(r"[A-Za-z]{3,}", original))
    # English words match loosely on the first 3 letters (make/making, fly/flying)
    words = re.findall(r"[a-z]+", low)
    return any(w.startswith(token.lower()[:3]) for w in words) or token.lower() in low


CONTEXT_INNER = re.compile(
    r"昨天|今天|明天|前天|刚才|刚刚|上周|这周|下周|周末|早上|晚上|公园|楼下|附近|路上|外面|超市|商场|医院|动物园|博物馆|操场"
)

# Question words and particles carry no topic; a rewriter sometimes leaves them in ("火山 为什么 会 喷发")
QUERY_STOPWORD = re.compile(
    r"^(为什么|为啥|什么|怎么|怎样|如何|是谁|谁|哪|哪里|哪个|几|多少|会|能|是|的|了|吗|呢|里的|里|"
    r"why|what|how|who|whom|which|where|when|is|are|was|were|do|does|did|can|could|the|a|an|of|in)$",
    re.IGNORECASE,
)


def ground_and_scrub(query: str, original: str) -> str:
    """Only delete words, never add: drop words not in the original, situational words such as time and place,
    and bare question words."""
    kept = []
    for t in query.split():
        if not _grounded(t, original) or QUERY_STOPWORD.match(t):
            continue
        # Context words can also hide inside a joined Chinese token ("公园蘑菇"): cut them out
        t = CONTEXT_INNER.sub("", t)
        if t and not CONTEXT_WORD.match(t) and not QUERY_STOPWORD.match(t):
            kept.append(t)
    return " ".join(kept)


def check_query(query: str, family_terms=(), blacklist=()) -> tuple[bool, str]:
    """Check the rewritten search term about to be sent. Returns (can send, reason)."""
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
        (len(re.findall(r"[\u4e00-\u9fff]", q)) > MAX_QUERY_CJK, "太长"),
        (len(re.findall(r"[A-Za-z]+", q)) > MAX_QUERY_WORDS, "太长"),
    ]
    for hit, reason in checks:
        if hit:
            return False, reason
    return True, ""


# The child is sharing something upsetting (not asking about a topic): used for the gentle response path
DISTRESS = re.compile(
    r"(我|俺|咱).{0,12}(难过|伤心|害怕|被欺负|欺负我|讨厌我|不喜欢我|孤独|寂寞|生气|委屈|想哭|哭了|不开心|不高兴|担心|紧张)|"
    r"\b(i|i'm|im|i am)\b.{0,20}\b(sad|scared|afraid|bullied|lonely|upset|angry|mad|worried|nervous|crying|unhappy)\b|"
    r"\b(nobody|no one) (likes|plays with) me\b|\bthey (hate|bully|laugh at) me\b",
    re.IGNORECASE,
)


def expresses_distress(text: str) -> bool:
    return bool(DISTRESS.search(text))
