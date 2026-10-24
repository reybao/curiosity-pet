"""生成两个模型的盲测评分表。

读取两份 baseline.py 的 --json 结果,每题各取第一次回答,随机排成 A/B,
输出评分表(不含模型名)和单独的答案键。家长评完再打开答案键。

用法:
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
    ap.add_argument("--out", required=True, help="输出前缀,生成 <out>-sheet.md 和 <out>-key.json")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    model_a, ans_a = first_answers(args.a)
    model_b, ans_b = first_answers(args.b)
    rng = random.Random(args.seed)

    lines = [
        "# 盲测评分表",
        "",
        "每题两个回答,来自两个不同的模型,顺序已随机。每项 1 至 5 分,5 最好。",
        "",
        "评分项:**对**(事实正确)、**懂**(7 岁能听懂)、**语**(用提问的语言回答)、**短**(两三句,适合念出来)。",
        "",
    ]
    key = {"seed": args.seed, "items": []}
    for i, q in enumerate(ans_a, 1):
        pair = [(model_a, ans_a[q]), (model_b, ans_b.get(q, ""))]
        rng.shuffle(pair)
        key["items"].append({"no": i, "question": q, "A": pair[0][0], "B": pair[1][0]})
        lines += [f"## {i}. {q}", ""]
        for label, (_, text) in zip("AB", pair):
            lines += [f"**{label}**:{text}", "", f"对 __ 懂 __ 语 __ 短 __", ""]
        lines += ["更喜欢:A / B / 差不多", ""]

    with open(f"{args.out}-sheet.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(f"{args.out}-key.json", "w", encoding="utf-8") as f:
        json.dump(key, f, ensure_ascii=False, indent=2)
    print(f"已生成 {args.out}-sheet.md 和 {args.out}-key.json")


if __name__ == "__main__":
    main()
