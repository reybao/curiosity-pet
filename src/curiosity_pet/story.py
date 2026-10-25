"""Storytelling and bedtime modes (CLAUDE.md "Storytelling mode"), run by the program.

- Original short stories with a fixed structure: who, a small problem, how it is solved, a warm ending. The child picks
  the protagonist and setting; if the request does not say, the pet asks once ("主角是谁?在哪里发生?").
- Things talked about earlier in the exploration may be woven in.
- Never online, no follow-up questions, no guess marker. Original only: no retelling of copyrighted picture books or
  cartoon plots. Idiom and fable requests ("讲个成语故事") are not story mode: they come from the library.
- Bedtime: slower voice, calm story ending with the protagonist falling asleep, a fixed goodnight, and the exploration
  ends by itself.
Before this, "讲故事" got one sentence of the Monkey King, and a long request got a short summary.
"""

import re

STORY = re.compile(
    r"(?:讲|说)(?:个|一个|一段|一下)?(?P<about>[^,，。!！?？]{0,16}?)的?故事|讲故事|说故事|"
    r"\btell me (?:a|another|one more) story\b(?: about (?P<about_en>[^.!?]{1,60}))?|\bstory time\b|"
    r"\bcan you tell (?:me )?a story\b(?: about (?P<about_en2>[^.!?]{1,60}))?",
    re.IGNORECASE,
)
BEDTIME = re.compile(r"睡前故事|睡觉(?:前)?的?故事|哄我睡觉|晚安故事|\bbedtime stor(?:y|ies)\b|\bsleepy? story\b|\bstory (?:before|for) (?:bed|sleep)\b",
                     re.IGNORECASE)
# Library stories (idioms, fables) and "the story of <a known work>" are not original story mode
NOT_ORIGINAL = re.compile(r"成语|寓言|典故|历史|《|》|的故事是什么|没讲清楚|讲的不|讲得不|不是这个|(?:说说|讲讲).{1,16}的故事|\bstory of\b|\bwhat happened\b",
                          re.IGNORECASE)
HERO = re.compile(r"主角(?:是|叫)(?P<who>[^,，。!！?？]{1,12})|(?:about|with) (?P<who_en>[a-z][^.!?,]{1,40})", re.IGNORECASE)
FILLER_ABOUT = re.compile(r"^(?:睡前|晚安|好听|有趣|好玩|短|长|新|别的|另外|一个)+$|^[\s的]*$")

TEXT = {
    "zh": {
        "ask": "好呀!故事的主角是谁?在哪里发生呢?",
        "note": "(讲一个原创的儿童故事,不要讲有版权的绘本或动画剧情。主角和场景:{about}。结构:主角是谁、遇到一个小麻烦、"
                "自己想办法解决、温暖的结尾。大约五六百字,用短句,一二年级能听懂;不吓人,没有暴力;这次不受两三句的限制,不要提问。{extra})",
        "bedtime": "这是睡前故事:节奏慢,安静温柔,最后主角安心地睡着了。",
        "weave": "可以自然地用上今天聊过的话题:{topics}。",
        "goodnight": "晚安,做个好梦。",
    },
    "en": {
        "ask": "Okay! Who should the story be about, and where does it happen?",
        "note": "(Tell an original children's story; do not retell copyrighted picture books or cartoon plots. Main character "
                "and place: {about}. Structure: who it is about, a small problem, how they solve it themselves, a warm ending. "
                "About 300 words, short sentences a first grader understands; nothing scary, no violence; this time the "
                "two-or-three-sentence rule does not apply; do not ask questions. {extra})",
        "bedtime": "This is a bedtime story: slow, calm and gentle, ending with the main character falling asleep peacefully.",
        "weave": "You may weave in what we talked about today: {topics}.",
        "goodnight": "Good night, sweet dreams.",
    },
}
BEDTIME_SPEED = 0.85


def request(text: str) -> tuple[str, str] | None:
    """("story" or "bedtime", what the story should be about, "" if not said), or None for other messages."""
    bedtime = bool(BEDTIME.search(text))
    m = STORY.search(text)
    if not (bedtime or m) or NOT_ORIGINAL.search(text):
        return None
    about = ""
    if m:
        about = (m.group("about") or m.group("about_en") or m.group("about_en2") or "").strip()
        about = re.sub(r"^(?:关于|有关|一个|个)", "", about).strip()
    if FILLER_ABOUT.match(about):
        about = ""
    if not about:
        h = HERO.search(text)
        about = (h.group("who") or h.group("who_en") or "").strip() if h else ""
    return ("bedtime" if bedtime else "story"), about


def note(lang: str, mode: str, about: str, topics: list[str]) -> str:
    t = TEXT[lang]
    extra = []
    if mode == "bedtime":
        extra.append(t["bedtime"])
    if topics:
        extra.append(t["weave"].format(topics=("、" if lang == "zh" else ", ").join(topics[:3])))
    return t["note"].format(about=about, extra="".join(extra) if lang == "zh" else " ".join(extra))
