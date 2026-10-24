"""语言跟随评测:宠物是否用孩子提问的语言回答。

对比阶段 0 基线用的双语系统提示(old)和 prompts.py 的分语言提示(new)。
问题均为虚构示例。期望语言由 lang.detect_language 判定(混说以占比多的为主)。

用法:
    uv run python evals/lang_eval.py --runs 2
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from baseline import SYSTEM as OLD_SYSTEM  # noqa: E402

from curiosity_pet.lang import detect_language  # noqa: E402
from curiosity_pet.llm import stream_chat  # noqa: E402
from curiosity_pet.prompts import build_messages  # noqa: E402
from curiosity_pet.textclean import EMOJI  # noqa: E402

QUESTIONS = [
    # 中文
    "为什么月亮白天也会出现?",
    "蚂蚁为什么排队走路?",
    "彩虹是怎么来的?",
    "为什么冬天会下雪?",
    "小鸟为什么会飞?",
    "我们为什么要睡觉?",
    # 英文
    "Why is the sky blue?",
    "How do fish breathe under water?",
    "Why do leaves change color?",
    "Where does rain come from?",
    "Why do cats purr?",
    "How big is the sun?",
    # 混说
    "为什么 dinosaurs 会 extinct?",
    "恐龙为什么会 extinct 呢?",
    "Why do 熊猫 eat bamboo all day?",
    "What is a 黑洞 made of?",
    "为什么 volcano 会喷火?",
    "How do 蜜蜂 make honey?",
]


def ask(question, mode):
    lang = detect_language(question)
    if mode == "old":
        msgs = [{"role": "system", "content": OLD_SYSTEM}, {"role": "user", "content": question}]
    else:
        msgs = build_messages(question, lang, history=[])
    answer = "".join(stream_chat(msgs))
    return lang, answer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args()

    for mode in ["old", "new"]:
        total = ok = emoji = meow = too_many_meow = 0
        fails = []
        for q in QUESTIONS:
            for _ in range(args.runs):
                expected, answer = ask(q, mode)
                got = detect_language(answer, fallback="?")
                total += 1
                ok += got == expected
                emoji += bool(EMOJI.search(answer))
                n_meow = len(re.findall(r"喵|meow", answer, re.I))
                meow += n_meow > 0
                too_many_meow += n_meow > 1
                if got != expected:
                    fails.append((q, expected, got, answer))
        print(
            f"\n[{mode}] 语言正确 {ok}/{total} ({ok / total:.0%}),含 emoji {emoji}/{total},"
            f"带喵 {meow}/{total},一次回答超过一个喵 {too_many_meow}/{total}"
        )
        for q, exp, got, ans in fails:
            print(f"  x {q}  期望 {exp} 实际 {got}: {ans[:60]}")


if __name__ == "__main__":
    main()
