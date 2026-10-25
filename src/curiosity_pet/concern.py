"""Things the child said that a parent may want to know about: kept as facts for the parent, never judged.

Owner decision 2026-10-24: "记忆也需要有一些负面情绪记录之类的,用来提醒父母". This amends the rule that no emotional
fields are collected, in a narrow way:
- only the child's own sentence, its time and a category are stored (what she said, not what she "is");
- no scores, labels, inferences or summaries; nothing is said to the child about it;
- shown only to the parent (pet-log), kept NOTE_RETENTION_DAYS days, deletable at any time;
- like everything else, it never leaves this machine.
The categories also make the pet answer gently (the care note), and the most serious ones take the fixed safety path.
"""

import re

NOTE_RETENTION_DAYS = 30

CATEGORIES = {
    # The most serious first: these also take the fixed safety response (safety.py)
    "harm_self": r"不想活|想死|去死|自杀|伤害自己|弄伤自己|kill myself|want to die|hurt myself|wish i (?:was|were) dead",
    "harm_others": r"(?:想|要|去)(?:杀|弄死|打死|揍)|(?:想|要|去)打(?:我的?|他的?|她的?)?(?:弟弟|妹妹|哥哥|姐姐|同学|小朋友|他|她|人|别人|爸爸|妈妈)|杀(?:了|掉)?(?:他|她|人|别人)|\bkill (?:some(?:body|one)|him|her|them|people)\b|"
                   r"\b(?:hit|punch|hurt|kick) (?:him|her|them|others|someone|somebody|people)\b|\bcan i (?:kill|hit|hurt)\b",
    "bullied": r"欺负|(?<![想要去])打我(?!的?(?:弟弟|妹妹|哥哥|姐姐|同学))|推我|骂我|笑话我|嘲笑我|没人(?:跟|和)我玩|不跟我玩|孤立|\bbull(?:y|ied|ies)\b|"
               r"\b(?:hit|pushed|kicked|laughed at) me\b|\bno ?(?:one|body) (?:plays|likes) (?:with )?me\b",
    "family_conflict": r"(?:爸爸|妈妈|爸|妈|爷爷|奶奶|外公|外婆).{0,10}(?:骂|打|凶|吼|生气|发火|推)|"
                       r"(?:讨厌|恨|烦)(?:我的?|死)?(?:弟弟|妹妹|哥哥|姐姐|爸爸|妈妈|爸|妈)|"
                       r"\bi (?:hate|can'?t stand) my (?:brother|sister|dad|mom|mum|parents?)\b|"
                       r"\bmy (?:dad|mom|mum|father|mother|parents?)\b.{0,40}\b(?:angry|mad|yell|yelled|shout|shouted|hit|hits|pushed|pushes)\b",
    "scared": r"害怕|好怕|吓死|做噩梦|噩梦|\bscared\b|\bafraid\b|\bnightmares?\b|\bfrightened\b",
    "sad": r"难过|伤心|想哭|哭了|我哭|不开心|孤独|寂寞|委屈|\bsad\b|\bi cry\b|\bcrying\b|\bunhappy\b|\blonely\b|\bupset\b",
    "angry": r"生气|气死|讨厌|恨|烦死|\bangry\b|\bmad\b|\bhate\b|\bannoyed\b|\bfurious\b",
    "unwell": r"不舒服|生病|发烧|头疼|头痛|肚子疼|好疼|受伤|\bsick\b|\bill\b|\bhurts?\b|\bfever\b|\bheadache\b|\btummy ache\b",
}
PATTERNS = {name: re.compile(p, re.IGNORECASE) for name, p in CATEGORIES.items()}
# Shown to the parent; plain words, not diagnoses
NAMES = {
    "harm_self": "说到伤害自己", "harm_others": "说到伤害别人", "bullied": "说到被欺负", "family_conflict": "说到和家人的冲突",
    "scared": "说到害怕", "sad": "说到难过", "angry": "说到生气", "unwell": "说到身体不舒服",
}
SERIOUS = ("harm_self", "harm_others")


def concerns(text: str) -> list[str]:
    """Categories found in what the child said, most serious first; empty for ordinary messages."""
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]
