"""What the pet may remember (CLAUDE.md "Memory and data model"): interests the child states herself, and discoveries she
asks to keep. Nothing else; no free text about her, no chat history.

- Interest cards: only from the child's own words ("我喜欢恐龙", "I love space"), only from a fixed list of topics, visible
  ("你记得我喜欢什么?" -> "我记得你喜欢恐龙和太空"), and removable by her ("我不喜欢恐龙了") or the parent (pet-log).
- My Discoveries: "收藏这个" / "save this" keeps the last question and what the pet said, until deleted.
The parent asked in a test "do you have memory about me? will you remember?"; before this the honest answer was no.
"""

import re

# Fixed list (whitelist enum): topic -> (zh name, en name, words that name it)
INTERESTS = {
    "dinosaurs": ("恐龙", "dinosaurs", r"恐龙|霸王龙|三角龙|dinosaurs?|t-?rex"),
    "space": ("太空", "space", r"太空|宇宙|星星|星球|月亮|火箭|宇航员|space|planets?|stars?|rockets?|astronauts?|the moon"),
    "ocean": ("大海", "the ocean", r"大海|海洋|鲸鱼|鲨鱼|海豚|章鱼|ocean|sea|whales?|sharks?|dolphins?|octopus"),
    "animals": ("动物", "animals", r"动物|小狗|小猫|兔子|熊猫|老虎|狮子|马|animals?|dogs?|cats?|puppies|kittens|bunnies|pandas?|tigers?|lions?|horses?"),
    "bugs": ("小虫子", "bugs", r"虫子|昆虫|蚂蚁|蝴蝶|瓢虫|蜜蜂|bugs?|insects?|ants?|butterfl(?:y|ies)|bees?|ladybugs?"),
    "plants": ("植物", "plants", r"植物|花|树|种子|plants?|flowers?|trees?|seeds?"),
    "weather": ("天气", "weather", r"天气|下雨|下雪|彩虹|打雷|weather|rain|snow|rainbows?|thunder"),
    "body": ("身体", "the human body", r"身体|骨头|心脏|大脑|human body|bones?|heart|brain"),
    "vehicles": ("交通工具", "vehicles", r"汽车|火车|飞机|轮船|车|cars?|trains?|planes?|airplanes?|ships?|trucks?"),
    "cartoons": ("动画故事", "cartoons", r"动画|动画片|七龙珠|宝可梦|皮卡丘|悟空|cartoons?|pok[eé]mon|dragon ball|pikachu|goku"),
    "stories": ("故事和书", "stories and books", r"故事|看书|读书|绘本|stories|story|books?|reading"),
    "art": ("画画", "drawing", r"画画|画|手工|drawing|painting|art|crafts?"),
    "music": ("音乐", "music", r"音乐|唱歌|钢琴|跳舞|music|singing|songs?|piano|dancing"),
    "sports": ("运动", "sports", r"运动|游泳|网球|足球|篮球|跑步|sports?|swimming|tennis|soccer|football|basketball|running"),
    "math": ("数学", "math", r"数学|算数|算术|数字|math|maths|numbers"),
    "science": ("科学", "science", r"科学|实验|science|experiments?"),
    "food": ("美食", "food", r"美食|做饭|烘焙|food|cooking|baking"),
}
PATTERNS = {k: re.compile(v[2], re.IGNORECASE) for k, v in INTERESTS.items()}

# The child about herself: "我(最/特别/超)喜欢…", "I (really) like/love …"; never "你喜欢…" (that is about the pet)
LIKE = re.compile(r"(?:^|[,，。!！\s])我(?:最|特别|很|超|超级|真的|也)?(?:喜欢|爱)(?P<what>[^,，。!！?？]{1,16})|"
                  r"\bI (?:really |also |just )?(?:like|love|am into)\b(?P<what_en>[^.!?,]{1,40})", re.IGNORECASE)
UNLIKE = re.compile(r"我(?:不|不再|已经不)喜欢(?P<what>[^,，。!！?？]{1,16})了|(?:忘掉|别记|不要记)(?P<what2>[^,，。!！?？]{1,16})|"
                    r"\bI don'?t (?:like|love) (?P<what_en>[^.!?,]{1,40}) any ?more\b|\bforget (?:that )?I like (?P<what_en2>[^.!?,]{1,40})",
                    re.IGNORECASE)
ASK = re.compile(r"你(?:还)?(?:记得|知道)我(?:最)?喜欢什么|我喜欢什么你记得吗|do you (?:remember|know) what I (?:like|love)|"
                 r"what do I (?:like|love)", re.IGNORECASE)
# "Will you remember me / what I said?" gets a fixed, honest answer (the model mixed up what it can keep)
ASK_REMEMBER = re.compile(
    r"你(?:会|能|还能|可以)?(?:记住|记得住|记得)(?:我|我说的|我今天说的|我们说的|我们聊的|我的)|你会忘(?:记)?(?:我|掉)|你有(?:没有)?记忆|"
    r"\bdo you have (?:a )?memory\b|\bwill you remember\b|\bcan you remember\b|\bdo you remember me\b|\bwill you forget\b",
    re.IGNORECASE,
)
SAVE = re.compile(r"收藏|保存(?:这个|下来|一下)?|记下来|放进我的发现|放到我的发现|我想留着|留下来|"
                  r"\bsave (?:this|that|it)\b|\bkeep (?:this|that)\b|\badd (?:this|it|that) to my discoveries\b", re.IGNORECASE)


def topics_in(text: str) -> list[str]:
    return [k for k, p in PATTERNS.items() if p.search(text)]


def stated_likes(text: str) -> list[str]:
    m = LIKE.search(text)
    if not m or UNLIKE.search(text):
        return []
    return topics_in(m.group("what") or m.group("what_en") or "")


def stated_unlikes(text: str) -> list[str]:
    m = UNLIKE.search(text)
    if not m:
        return []
    return topics_in(next(g for g in m.groups() if g))


def asks_what_i_like(text: str) -> bool:
    return bool(ASK.search(text))


def asks_if_remembered(text: str) -> bool:
    return bool(ASK_REMEMBER.search(text)) and not ASK.search(text)


def wants_to_save(text: str) -> bool:
    return bool(SAVE.search(text))


def names(topics: list[str], lang: str) -> str:
    i = 0 if lang == "zh" else 1
    words = [INTERESTS[t][i] for t in topics if t in INTERESTS]
    if lang == "zh":
        return "、".join(words[:-1]) + ("和" if len(words) > 1 else "") + words[-1] if words else ""
    return ", ".join(words[:-1]) + (" and " if len(words) > 1 else "") + words[-1] if words else ""


TEXT = {
    "zh": {
        "liked": "我记住啦,你喜欢{what}。",
        "unliked": "好的,我不再记着你喜欢{what}了。",
        "recall": "我记得你喜欢{what}。",
        "recall_none": "你还没告诉我你喜欢什么呢。",
        "saved": "好,我把刚才的问题和答案放进\"我的发现\"了。",
        "nothing_to_save": "我们还没聊什么呢,先问我一个问题吧。",
        "wrap_up": "我们今天探索了好一会儿啦,让眼睛和耳朵休息一下吧,下次见!",
        "remember": "我们聊的话,我不会一直记着。你告诉我你喜欢什么,我会记住;想留下刚才的问题和答案,就说\"收藏这个\"。",
    },
    "en": {
        "liked": "Got it, you like {what}.",
        "unliked": "Okay, I won't keep remembering that you like {what}.",
        "recall": "I remember you like {what}.",
        "recall_none": "You haven't told me what you like yet.",
        "saved": "Okay, I put that question and answer in My Discoveries.",
        "nothing_to_save": "We haven't talked about anything yet. Ask me a question first!",
        "wrap_up": "We've explored for a good while today. Let's give our eyes and ears a rest. See you next time!",
        "remember": "I don't keep what we talk about. If you tell me what you like, I'll remember that, and if you want "
                    "to keep a question and its answer, just say \"save this\".",
    },
}
