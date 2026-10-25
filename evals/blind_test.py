"""Generate a blind-test scoring sheet for two models.

Reads two baseline.py --json results, takes the first answer per question from each, and shuffles them into A/B.
Outputs a scoring sheet (no model names) and a separate answer key. Open the key only after the parent has scored.

Usage:
    python evals/blind_test.py a.json b.json --out evals/results/2026-10-23-blind --seed 1
"""

import argparse
import json
import random


def first_answers(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    answers = {}
    for row in data["rows"]:
        answers.setdefault(row["question"], row["answer"])
    return data["model"], answers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--out", required=True, help="output prefix; generates <out>-sheet.md and <out>-key.json")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    model_a, ans_a = first_answers(args.a)
    model_b, ans_b = first_answers(args.b)
    rng = random.Random(args.seed)

    lines = [
        "# Blind test scoring sheet",
        "",
        "Each question has two answers from two different models, in random order. Score each item 1 to 5, 5 is best.",
        "",
        "Items: **Correct** (factually right), **Clear** (a 7-year-old can follow), **Language** (answers in the language asked), **Short** (two or three sentences, good to read aloud).",
        "",
    ]
    key = {"seed": args.seed, "items": []}
    for i, q in enumerate(ans_a, 1):
        pair = [(model_a, ans_a[q]), (model_b, ans_b.get(q, ""))]
        rng.shuffle(pair)
        key["items"].append({"no": i, "question": q, "A": pair[0][0], "B": pair[1][0]})
        lines += [f"## {i}. {q}", ""]
        for label, (_, text) in zip("AB", pair):
            lines += [f"**{label}**: {text}", "", f"Correct __ Clear __ Language __ Short __", ""]
        lines += ["Preferred: A / B / about the same", ""]

    with open(f"{args.out}-sheet.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(f"{args.out}-key.json", "w", encoding="utf-8") as f:
        json.dump(key, f, ensure_ascii=False, indent=2)
    print(f"Generated {args.out}-sheet.md and {args.out}-key.json")


if __name__ == "__main__":
    main()
