"""阶段 0 基线:主模型在本机的速度。

通过 Ollama 原生 /api/chat 流式请求(think=false),记录:
首字延迟、首句延迟、预填充速度、生成速度、加载时间。
只用标准库,问题均为虚构示例,不含任何真实儿童数据。

用法:
    python evals/baseline.py                       # 默认 pet-chat,每题 3 次
    python evals/baseline.py --model gemma4:e4b --runs 5
    python evals/baseline.py --json evals/results/raw.json
"""

import argparse
import json
import statistics
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"

SYSTEM = (
    "你是一个给 7 岁孩子讲科学的小伙伴。用孩子提问的语言回答,两三句话,简单易懂。"
    "You are a friendly science buddy for a 7-year-old. Answer in the child's language, "
    "in two or three short sentences."
)

QUESTIONS = [
    ("zh", "为什么月亮白天也会出现?"),
    ("zh", "蚂蚁为什么排队走路?"),
    ("en", "Why is the sky blue?"),
    ("en", "How do fish breathe under water?"),
    ("mix", "为什么 dinosaurs 会 extinct?"),
]

SENTENCE_END = set("\u3002\uff01\uff1f!?.")  # 全角句号叹号问号与半角


def chat_once(model, question):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
        "stream": True,
        "think": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    first_token = first_sentence = None
    text = ""
    final = {}
    with urllib.request.urlopen(req, timeout=300) as resp:
        for line in resp:
            if not line.strip():
                continue
            chunk = json.loads(line)
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                now = time.perf_counter() - t0
                if first_token is None:
                    first_token = now
                text += piece
                if first_sentence is None and any(c in SENTENCE_END for c in piece):
                    first_sentence = now
            if chunk.get("done"):
                final = chunk
    total = time.perf_counter() - t0
    ns = 1e9
    return {
        "question": question,
        "answer": text.strip(),
        "first_token_s": first_token,
        "first_sentence_s": first_sentence,
        "total_s": total,
        "load_s": final.get("load_duration", 0) / ns,
        "prompt_tokens": final.get("prompt_eval_count", 0),
        "prefill_tok_s": final.get("prompt_eval_count", 0)
        / max(final.get("prompt_eval_duration", 1) / ns, 1e-9),
        "gen_tokens": final.get("eval_count", 0),
        "gen_tok_s": final.get("eval_count", 0)
        / max(final.get("eval_duration", 1) / ns, 1e-9),
    }


def median(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    return statistics.median(vals) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="pet-chat")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--json", help="把逐次结果写入该文件")
    args = ap.parse_args()

    # 预热一次,确保模型已常驻,不计入统计
    chat_once(args.model, "你好")

    rows = []
    for lang, q in QUESTIONS:
        for _ in range(args.runs):
            r = chat_once(args.model, q)
            r["lang"] = lang
            rows.append(r)

    print(f"模型: {args.model},每题 {args.runs} 次,共 {len(rows)} 次(中位数)")
    # 预填充速度受 Ollama 前缀缓存影响,短提示下数字失真,只留在原始 JSON 里,不进表
    print("| 语言 | 首字 s | 首句 s | 总时长 s | 生成 tok/s |")
    print("|---|---|---|---|---|")
    for lang in ["zh", "en", "mix", "all"]:
        sub = rows if lang == "all" else [r for r in rows if r["lang"] == lang]
        cells = [
            median(sub, k)
            for k in ["first_token_s", "first_sentence_s", "total_s", "gen_tok_s"]
        ]
        print(f"| {lang} | " + " | ".join("-" if c is None else f"{c:.2f}" for c in cells) + " |")

    print("\n示例回答:")
    seen = set()
    for r in rows:
        if r["question"] not in seen:
            seen.add(r["question"])
            print(f"- {r['question']}\n  {r['answer']}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"model": args.model, "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
