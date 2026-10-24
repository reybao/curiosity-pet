"""主模型常驻内存是否随请求增长,以及不同引擎和 KV 缓存设置下的速度。

模拟真实使用:每道题先单独问,再追问"再简单一点"(带历史),共 --requests 次请求。
每 10 次记录一次 Ollama 报告的模型占用(/api/ps)和系统交换区用量。
同时检查回答语言是否正确,防止量化影响质量。问题均为虚构示例。

用法(先用临时 ollama serve 起一个端口,见 evals/results 里的说明):
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

    chat(args.url, args.model, [{"role": "user", "content": "你好"}])  # 加载并预热
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
    print(f"  内存(GB,每 10 次): {sizes}")
    print(f"  交换区(GB): {samples[0]['swap_gb']:.1f} -> {samples[-1]['swap_gb']:.1f}")
    print(
        f"  首字 {med('first_token_s'):.2f}s | 第一块 {med('first_chunk_s'):.2f}s | "
        f"生成 {med('gen_tok_s'):.1f} tok/s | 语言正确 {sum(r['lang_ok'] for r in rows)}/{len(rows)}"
    )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"label": args.label, "model": args.model, "samples": samples, "rows": rows},
                      f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
