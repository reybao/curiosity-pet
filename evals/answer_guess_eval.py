"""Offline experiment: let the local model name the likely answer, then look that name up in the library.

Motivation (evals/embedding_eval.py): questions such as "世界上最大的动物是什么?" fail with every retrieval method,
because the answer's name (蓝鲸) is not in the question, so neither keywords nor embeddings over the keyword candidates
reach it. The model usually knows the name; the library then supplies checked text about it.

Compares on the same cases as embedding_eval.py:
  lexical       the library as it is (rewritten query)
  guess-first   search the model's answer name first, fall back to the rewritten query
  guess-backup  the rewritten query first, the answer name only when that finds nothing

Uses the already loaded chat model through Ollama (no other model is loaded) and searches only the local library.
Usage: uv run python evals/answer_guess_eval.py [--pipeline] [--json out.json]
  --pipeline: the pet's own flow after the answer name went into the rewrite call (one model call per question)
"""

import argparse
import importlib.util
import json
import time
from pathlib import Path

import httpx

from curiosity_pet import config
from curiosity_pet.library import Library

PROMPT = {
    "zh": "孩子问:{q}\n如果这个问题的答案是一个具体的东西、人、地方或概念,写出它在百科全书里的条目名(中文,尽量短);"
          "如果答案不是一个具体的东西,写空字符串。只输出 JSON:{{\"answer\": \"...\"}}",
    "en": "A child asks: {q}\nIf the answer is one specific thing, person, place or idea, write its encyclopedia article "
          "title (English, short); otherwise an empty string. Output JSON only: {{\"answer\": \"...\"}}",
}


def guess(question: str, lang: str) -> str:
    body = {"model": config.HELPER_MODEL, "messages": [{"role": "user", "content": PROMPT[lang].format(q=question)}],
            "stream": False, "think": False, "format": "json", "options": {"temperature": 0}}
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=60)
    r.raise_for_status()
    try:
        return str(json.loads(r.json()["message"]["content"]).get("answer", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        return ""


def run_pipeline(emb, out_json=""):
    """The pet's own flow: one rewrite call that returns query and answer name, then Researcher.fetch on the library
    (with and without the answer name)."""
    import dataclasses

    from curiosity_pet.lookup import Researcher
    from curiosity_pet.search import LibraryProvider

    r = Researcher(store=None, enabled=False, contact="", providers=[LibraryProvider()])
    rows, times = [], []
    for q, lang, rq, expect, group in emb.load_cases():
        accepted = expect.split("|")

        def ok(title):
            return any(title == a or (a.endswith("*") and title.startswith(a[:-1])) for a in accepted)

        emb.wait_for_quiet(print)
        t = time.perf_counter()
        d = r.decide(q, lang)
        times.append(time.perf_counter() - t)
        with_answer = r.fetch(d, lang) if d.go else None
        without = r.fetch(dataclasses.replace(d, answer=""), lang) if d.go else None
        row = {"q": q, "group": group, "expect": expect, "go": d.go, "reason": d.reason, "query": d.query, "answer": d.answer,
               "decide_s": times[-1],
               "without": without.title if without else "-", "with": with_answer.title if with_answer else "-"}
        row["without_ok"], row["with_ok"] = ok(row["without"]), ok(row["with"])
        rows.append(row)
    print("| Group | Cases | without answer name | with answer name |\n|---|---|---|---|")
    for group in ("eval set", "real/semantic", "all"):
        sel = [x for x in rows if group == "all" or x["group"] == group]
        print(f"| {group} | {len(sel)} | {sum(x['without_ok'] for x in sel)} | {sum(x['with_ok'] for x in sel)} |")
    print("\n| Question | Expected | Query | Answer name | without | with |\n|---|---|---|---|---|---|")
    for x in rows:
        if x["without_ok"] != x["with_ok"] or x["group"] == "real/semantic":
            print(f"| {x['q']} | {x['expect']} | {x['query'] or x['reason']} | {x['answer'] or '(none)'} | "
                  f"{'**' if x['without_ok'] else ''}{x['without']}{'**' if x['without_ok'] else ''} | "
                  f"{'**' if x['with_ok'] else ''}{x['with']}{'**' if x['with_ok'] else ''} |")
    from curiosity_pet.lookup import ANSWER_ASK

    real = [x for x in rows if x["group"] == "real/semantic" and x["go"]]
    for label, sel in (("with the answer-name call", [x for x in real if ANSWER_ASK.search(x["q"])]),
                       ("rewrite call only", [x for x in real if not ANSWER_ASK.search(x["q"])])):
        ts = sorted(x["decide_s"] for x in sel)
        if ts:
            print(f"\nDecide, real questions {label}: median {ts[len(ts) // 2]:.2f} s, max {ts[-1]:.2f} s ({len(ts)} questions)")
    if out_json:
        Path(out_json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--pipeline", action="store_true", help="evaluate the pet's own rewrite + fetch flow")
    args = ap.parse_args()
    spec = importlib.util.spec_from_file_location("embedding_eval", Path(__file__).with_name("embedding_eval.py"))
    emb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(emb)
    if args.pipeline:
        return run_pipeline(emb, args.json)
    lib = Library()
    rows, times = [], []
    for q, lang, rq, expect, group in emb.load_cases():
        accepted = expect.split("|")

        def ok(title):
            return any(title == a or (a.endswith("*") and title.startswith(a[:-1])) for a in accepted)

        emb.wait_for_quiet(print)
        t = time.perf_counter()
        g = guess(q, lang)
        times.append(time.perf_counter() - t)
        by_q = [r.title for r in lib.search(rq, lang)]
        by_g = [r.title for r in lib.search(g, lang)] if g else []
        row = {"q": q, "expect": expect, "group": group, "guess": g,
               "lexical": by_q[0] if by_q else "-",
               "guess-first": (by_g or by_q or ["-"])[0],
               "guess-backup": (by_q or by_g or ["-"])[0]}
        for m in ("lexical", "guess-first", "guess-backup"):
            row[m + "_ok"] = ok(row[m])
        rows.append(row)
    methods = ["lexical", "guess-first", "guess-backup"]
    print("| Group | Cases | " + " | ".join(methods) + " |\n|---|---|---|---|---|")
    for group in ("eval set", "real/semantic", "all"):
        sel = [r for r in rows if group == "all" or r["group"] == group]
        print(f"| {group} | {len(sel)} | " + " | ".join(str(sum(r[m + "_ok"] for r in sel)) for m in methods) + " |")
    print("\n| Question | Expected | Model's answer name | " + " | ".join(methods) + " |\n|---|---|---|---|---|---|")
    for r in rows:
        if len({r[m + "_ok"] for m in methods}) > 1 or r["group"] == "real/semantic":
            print(f"| {r['q']} | {r['expect']} | {r['guess'] or '(none)'} | " + " | ".join(("**" if r[m + '_ok'] else "") + r[m] + ("**" if r[m + '_ok'] else "") for m in methods) + " |")
    times.sort()
    print(f"\nModel call: median {times[len(times) // 2]:.2f} s, max {times[-1]:.2f} s ({config.HELPER_MODEL})")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
