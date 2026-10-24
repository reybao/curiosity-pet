"""流式断句。

模型逐块输出文字,凑够一句就交给 TTS,不等整段生成完。
Kokoro 念很短的句子效果差,所以第一句太短时与第二句合并后再合成。
实测 TTS 与生成同时跑时抢 GPU,合成耗时约变成 3 倍,第一块越长开口越晚;
所以第一块在够长(SHORT_FIRST_CHARS 以上)时也可以在逗号处断开。
"""

import re

# 中文标点直接断;英文 . ! ? 后面需要空白(或在 flush 时位于末尾),避免把 3.5 断开
ZH_END = "\u3002\uff01\uff1f\uff1b!?;\u2026"  # 句号 叹号 问号 分号(全角与半角)、省略号
EN_END = ".!?"
COMMA = "\uff0c\u3001,"  # 全角逗号、顿号、半角逗号
SHORT_FIRST_CHARS = 8
EN_FIRST_MIN_WORDS = 8
# 连词前要有空格、后面也要有空格,保证这个词已经完整生成
EN_CONJUNCTION = re.compile(r"(?<=\s)(?:when|because|and|but|so|which|while|like|or)(?=\s)")


class SentenceSplitter:
    def __init__(self, merge_short_first: bool = True, short_first_chars: int = SHORT_FIRST_CHARS):
        self.buf = ""
        self.merge_short_first = merge_short_first
        self.short_first_chars = short_first_chars
        self.pending_first: str | None = None
        self.emitted = 0

    def feed(self, piece: str) -> list[str]:
        self.buf += piece
        out = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            sentence, self.buf = self.buf[:cut].strip(), self.buf[cut:].lstrip()
            if sentence:
                out.extend(self._emit(sentence))
        return out

    def flush(self) -> list[str]:
        out = []
        tail = self.buf.strip()
        self.buf = ""
        if tail:
            out.extend(self._emit(tail))
        if self.pending_first is not None:
            out.append(self.pending_first)
            self.pending_first = None
        return out

    def _find_cut(self) -> int | None:
        first = self.merge_short_first and self.emitted == 0 and self.pending_first is None
        cut = self._punctuation_cut(first)
        if first:
            # 英文回答很少有早出现的逗号:第一块够 EN_FIRST_MIN_WORDS 个词后,可在连词前断开
            for m in EN_CONJUNCTION.finditer(self.buf):
                if cut is not None and m.start() >= cut:
                    break
                if len(self.buf[: m.start()].split()) >= EN_FIRST_MIN_WORDS:
                    return m.start()
        return cut

    def _punctuation_cut(self, first: bool) -> int | None:
        for i, ch in enumerate(self.buf):
            if first and ch in COMMA and _length(self.buf[: i + 1]) >= self.short_first_chars:
                return i + 1
            if ch in ZH_END:
                # 连续标点(如 "?!" "……")一起归到这一句
                j = i + 1
                while j < len(self.buf) and self.buf[j] in ZH_END + EN_END:
                    j += 1
                return j
            if ch in EN_END:
                nxt = self.buf[i + 1] if i + 1 < len(self.buf) else None
                if nxt is not None and nxt.isspace():
                    return i + 1
        return None

    def _emit(self, sentence: str) -> list[str]:
        if not self.merge_short_first:
            self.emitted += 1
            return [sentence]
        if self.emitted == 0 and self.pending_first is None:
            if _length(sentence) < self.short_first_chars:
                self.pending_first = sentence
                return []
        if self.pending_first is not None:
            sentence = _join(self.pending_first, sentence)
            self.pending_first = None
        self.emitted += 1
        return [sentence]


def _length(s: str) -> int:
    """中文按字数,英文按字母数的一半粗算,和中文字数大致可比。"""
    cjk = len(re.findall(r"[一-鿿]", s))
    latin = len(re.findall(r"[A-Za-z]", s))
    return cjk + latin // 2


def _join(a: str, b: str) -> str:
    if a and a[-1] in EN_END and b[:1].isascii():
        return f"{a} {b}"
    return a + b
