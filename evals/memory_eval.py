"""Does the main model's resident memory grow with requests, and how fast is it under different engines and KV cache settings.

Simulates real use: each question is asked alone, then followed up with "再简单一点" (with history), for --requests requests in total.
Every 10 requests, records the model memory reported by Ollama (/api/ps) and system swap usage.
Also checks that the answer language is correct, to catch quality loss from quantization. Questions are fictional examples.

Usage (first start a temporary ollama serve on its own port, see the notes in evals/results):
    uv run python evals/memory_eval.py --url http://127.0.0.1:11435 --model pet-chat --label A
"""

import argparse
import json
import re
import statistics
import subprocess
import time

import httpx

from curiosity_pet.lang import detect_language
from curiosity_pet.prompts import build_messages
from curiosity_pet.sentences import SentenceSplitter

QUESTIONS = [
    "为什么月亮白天也会出现?", "蚂蚁为什么排队走路?", "彩虹是怎么来的?", "为什么冬天会下雪?",
    "小鸟为什么会飞?", "我们为什么要睡觉?", "为什么海水是咸的?", "星星为什么一闪一闪?",
    "为什么树叶是绿色的?", "打雷是怎么回事?", "为什么会有回声?", "鱼会睡觉吗?",
    "Why is the sky blue?", "How do fish breathe under water?", "Why do leaves change color?",
    "Where does rain come from?", "Why do cats purr?", "How big is the sun?",
    "Why do we have seasons?", "How do bees make honey?", "Why is the ocean salty?",
    "What makes thunder?", "Why do zebras have stripes?", "How do plants drink water?",
    "恐龙为什么会 extinct 呢?", "Why do 熊猫 eat bamboo all day?", "What is a 黑洞 made of?",
    "为什么 volcano 会喷火?", "How do 蜜蜂 talk to each other?", "为什么 octopus 有八条腿?",
]
FOLLOW_UP = {"zh": "再简单一点", "en": "Can you make it simpler?"}


def ps_size(url, model):
    for m in httpx.get(f"{url}/api/ps", timeout=10).json().get("models", []):
        if m["name"].split(":")[0] == model.split(":")[0]:
            return m.get("size", 0) / 1e9
    return None


def swap_used_gb():
    out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    m = re.search(r"used = ([\d.]+)M", out)
    return float(m.group(1)) / 1024 if m else None


def chat(url, model, messages):
    t0 = time.perf_counter()
    first_token = first_chunk = None
    text = ""
    final = {}
    sp = SentenceSplitter()
    body = {"model": model, "messages": messages, "stream": True, "think": False}
    with httpx.stream("POST", f"{url}/api/chat", json=body, timeout=120) as r:
        for line in r.iter_lines():
            if not line:
                continue
            c = json.loads(line)
            piece = c.get("message", {}).get("content", "")
            if piece:
                now = time.perf_counter() - t0
                first_token = first_token or now
                text += piece
                if first_chunk is None and sp.feed(piece):
                    first_chunk = now
            if c.get("done"):
                final = c
    if first_chunk is None:
        first_chunk = time.perf_counter() - t0
    gen = final.get("eval_count", 0) / max(final.get("eval_duration", 1) / 1e9, 1e-9)
    return text, first_token, first_chunk, gen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="pet-chat")
    ap.add_argument("--label", default="")
    ap.add_argument("--requests", type=int, default=60)
    ap.add_argument("--json")
    args = ap.parse_args()

    chat(args.url, args.model, [{"role": "user", "content": "你好"}])  # load and warm up
    samples = [{"n": 0, "size_gb": ps_size(args.url, args.model), "swap_gb": swap_used_gb()}]
    rows = []
    i = 0
    while len(rows) < args.requests:
        q = QUESTIONS[i % len(QUESTIONS)]
        i += 1
        lang = detect_language(q)
        history = []
        for ask in (q, FOLLOW_UP[lang]):
            if len(rows) >= args.requests:
                break
            text, ft, fc, gen = chat(args.url, args.model, build_messages(ask, lang, history))
            history += [{"role": "user", "content": ask}, {"role": "assistant", "content": text}]
            rows.append({
                "question": ask, "lang": lang, "answer": text,
                "lang_ok": detect_language(text, fallback="?") == lang,
                "first_token_s": ft, "first_chunk_s": fc, "gen_tok_s": gen,
            })
            if len(rows) % 10 == 0:
                samples.append({
                    "n": len(rows), "size_gb": ps_size(args.url, args.model), "swap_gb": swap_used_gb()
                })

    med = lambda k: statistics.median(r[k] for r in rows)  # noqa: E731
    sizes = " -> ".join(f"{s['size_gb']:.1f}" for s in samples)
    print(f"[{args.label}] {args.model} @ {args.url}")
    print(f"  memory (GB, every 10 requests): {sizes}")
    print(f"  swap (GB): {samples[0]['swap_gb']:.1f} -> {samples[-1]['swap_gb']:.1f}")
    print(
        f"  first token {med('first_token_s'):.2f}s | first chunk {med('first_chunk_s'):.2f}s | "
        f"generation {med('gen_tok_s'):.1f} tok/s | correct language {sum(r['lang_ok'] for r in rows)}/{len(rows)}"
    )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"label": args.label, "model": args.model, "samples": samples, "rows": rows},
                      f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
