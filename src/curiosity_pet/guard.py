"""Safety guard (safety layer 2 in CLAUDE.md): Qwen3Guard-Gen-0.6B judges the child's question and every answer sentence.

Measured on the child's real turns (evals/results/2026-10-24-guard.md): strict mode ("Controversial" counts as unsafe)
flagged 15% of ordinary questions and 10% of ordinary answer sentences ("喵。", "皮卡!", a riddle answer), so it would
silence normal answers; the guard therefore runs non-strict (only "Unsafe" blocks). An unsafe question gets the fixed
"let's ask mom or dad" line; an unsafe answer sentence is not spoken. The model is the official one converted locally
(scripts/convert_guard.py), 4-bit MLX, about 350 MB on disk; it runs in the server process under the engine lock.

Off unless settings.json sets "guard": "questions" (judge only the child's question, about 0.16 s per turn) or "all"
(also every answer sentence, about 0.22 s each). It costs about 0.6 GB on top of the 9B model and speech, which already
sit near the memory budget, so the parent decides. Needs the optional dependency group: uv sync --group guard.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from curiosity_pet import config

DEFAULT_PATH = Path.home() / "pet-models" / "qwen3guard-gen-0.6b-4bit"
VERDICT = re.compile(r"Safety:\s*(Safe|Unsafe|Controversial)", re.IGNORECASE)
CATEGORIES = re.compile(r"Categories:\s*([^\n]*)", re.IGNORECASE)


@dataclass
class Verdict:
    safe: bool
    label: str  # Safe, Unsafe, Controversial, or Unknown when the output could not be read
    categories: str = ""


def parse(output: str, strict: bool = False) -> Verdict:
    m = VERDICT.search(output)
    if not m:
        return Verdict(True, "Unknown")  # unreadable output never blocks the conversation
    label = m.group(1).capitalize()
    cats = CATEGORIES.search(output)
    safe = label == "Safe" or (label == "Controversial" and not strict)
    return Verdict(safe, label, cats.group(1).strip() if cats else "")


class Guard:
    def __init__(self, path: Path | str = DEFAULT_PATH, strict: bool = False):
        from mlx_lm import load

        self.model, self.tokenizer = load(str(path))
        self.strict = strict

    def _judge(self, messages: list[dict]) -> Verdict:
        from mlx_lm import generate

        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return parse(generate(self.model, self.tokenizer, prompt=prompt, max_tokens=24, verbose=False), self.strict)

    def question(self, text: str) -> Verdict:
        return self._judge([{"role": "user", "content": text}])

    def answer(self, question: str, sentence: str) -> Verdict:
        return self._judge([{"role": "user", "content": question}, {"role": "assistant", "content": sentence}])


def mode(settings: dict | None = None) -> str:
    """"off", "questions" or "all"."""
    settings = config.load_settings() if settings is None else settings
    value = settings.get("guard", False)
    value = "all" if value is True else str(value or "off")
    return value if value in ("questions", "all") and DEFAULT_PATH.is_dir() else "off"
