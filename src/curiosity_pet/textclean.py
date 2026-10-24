"""送 TTS 前的文字清理:去掉 emoji 和 Markdown 符号。"""

import re

EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # 各类 emoji、符号、表情
    "☀-➿"  # 杂项符号与装饰符号(☀ ☄ ✨ 等)
    "⬀-⯿"
    "️‍"  # 变体选择符与零宽连接符
    "]+"
)
MARKDOWN_INLINE = re.compile(r"(\*\*|__|\*|`|~~)")
MARKDOWN_LINE_PREFIX = re.compile(r"^\s*(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)", re.MULTILINE)


def clean_for_speech(text: str) -> str:
    text = EMOJI.sub("", text)
    text = MARKDOWN_LINE_PREFIX.sub("", text)
    text = MARKDOWN_INLINE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


# 猫咪口癖:一次回答只留第一个"喵"。4B 模型不太遵守"最多一个"的要求(实测 13/36 次回答喵了不止一次),由程序保证。
MEOW = re.compile(r"[,，]?\s*(喵+|\bmeow\b)[~～]?(?=[\s。.!！?？,，]|$)", re.IGNORECASE)


class MeowLimiter:
    """逐句调用;整轮回答里只保留第一个喵。"""

    def __init__(self):
        self.used = False

    def __call__(self, sentence: str) -> str:
        def keep_first(m):
            if self.used:
                return ""
            self.used = True
            return m.group(0)

        out = MEOW.sub(keep_first, sentence)
        # 删掉喵后可能留下孤立的标点或空格,比如英文的 "Meow." 单独成句
        out = re.sub(r"^\s*[。.!！,，]\s*", "", out)
        out = re.sub(r"\s+([。.!！?？,，])", r"\1", out)
        return re.sub(r"\s{2,}", " ", out).strip()
