"""Streaming sentence splitting.

The model emits text chunk by chunk; as soon as a sentence is complete it goes to TTS, without waiting for the whole answer.
Kokoro reads very short sentences poorly, so a too-short first sentence is merged with the second before synthesis.
Measured: when TTS and generation run together they fight for the GPU and synthesis takes about 3 times longer, and the longer the first chunk the later speech starts;
so once the first chunk is long enough (SHORT_FIRST_CHARS or more) it may also be split at a comma.
"""

import re

# Chinese punctuation splits directly; English . ! ? must be followed by whitespace (or sit at the end on flush), so 3.5 is not split
ZH_END = "\u3002\uff01\uff1f\uff1b!?;\u2026"  # period, exclamation, question, semicolon (full-width and half-width), ellipsis
EN_END = ".!?"
COMMA = "\uff0c\u3001,"  # full-width comma, enumeration comma, half-width comma
SHORT_FIRST_CHARS = 8
EN_FIRST_MIN_WORDS = 8
# Conjunctions need a space before and after, which guarantees the word is fully generated
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
            # English answers rarely have an early comma: once the first chunk has EN_FIRST_MIN_WORDS words, it may be split before a conjunction
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
                # Consecutive punctuation (e.g. "?!" "……") stays with this sentence
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
    """Chinese counts by characters, English by half the letter count, roughly comparable to Chinese character counts."""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", s))
    latin = len(re.findall(r"[A-Za-z]", s))
    return cjk + latin // 2


def _join(a: str, b: str) -> str:
    if a and a[-1] in EN_END and b[:1].isascii():
        return f"{a} {b}"
    return a + b
