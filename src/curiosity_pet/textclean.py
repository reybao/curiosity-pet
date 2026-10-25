"""Text cleanup before TTS: strip emoji and Markdown symbols."""

import re

EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # assorted emoji, symbols, emoticons
    "☀-➿"  # miscellaneous and dingbat symbols (☀ ☄ ✨ etc.)
    "⬀-⯿"
    "️‍"  # variation selector and zero-width joiner
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


# Cat verbal tic: keep only the first "meow" per answer. The 4B model does not reliably obey "at most one" (measured: 13 of 36 answers meowed more than once), so code enforces it.
def sound_pattern(sounds) -> re.Pattern:
    """One regex matching any of the pet's catchphrases ("喵", "meow", or a skin's own), with optional trailing ~ ."""
    alts = []
    for s in sounds:
        if re.search(r"[\u4e00-\u9fff]", s):
            alts.append(f"(?:{re.escape(s)})+")
        else:
            alts.append(rf"\b{re.escape(s)}\b")
    return re.compile(r"[,，]?\s*(" + "|".join(alts) + r")[~～]?(?=[\s。.!！?？,，]|$)", re.IGNORECASE)


DEFAULT_SOUNDS = ("喵", "meow")
MEOW = sound_pattern(DEFAULT_SOUNDS)


class MeowLimiter:
    """Call per sentence; keeps only the first catchphrase of the whole answer."""

    def __init__(self, sounds=None):
        self.used = False
        if sounds is None:
            from curiosity_pet import config

            sounds = set(DEFAULT_SOUNDS) | set(config.PERSONA["sound"].values())
        self.pattern = sound_pattern(sorted(sounds, key=len, reverse=True))

    def __call__(self, sentence: str) -> str:
        def keep_first(m):
            if self.used:
                return ""
            self.used = True
            return m.group(0)

        out = self.pattern.sub(keep_first, sentence)
        # Removing the meow can leave stray punctuation or spaces, e.g. an English "Meow." standing alone as a sentence
        out = re.sub(r"^\s*[。.!！,，]\s*", "", out)
        out = re.sub(r"\s+([。.!！?？,，])", r"\1", out)
        return re.sub(r"\s{2,}", " ", out).strip()
