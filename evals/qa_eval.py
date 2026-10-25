"""Idiom stories, poems and the reviewed child Q&A library, checked offline.

1. Conversations that failed in real use, replayed against the library (no model call): idiom story by name and at
   random, "不是这个意思", "这首诗想表达什么", "你会背多少首唐诗?", a poem about winter.
2. Q&A matching, leave-one-out: each sampled alternative phrasing is asked with that phrasing removed from the store
   (every entry treated as approved); the right entry, a wrong one, or none (the usual library lookup follows).
   Uses the local model as judge for close candidates, as the pet does.

Usage: uv run python evals/qa_eval.py [--sample 80]
"""

import argparse
import json
import random
import time
from pathlib import Path

from curiosity_pet import qa as Q
from curiosity_pet.lookup import Researcher
from curiosity_pet.search import LibraryProvider

CONVERSATION = ["给我讲个成语故事", "不是这个意思", "再讲一个成语故事", "画蛇添足的故事", "这个成语是什么意思", "背一首关于冬天的诗",
                "这首诗想表达什么", "你会背多少首唐诗?", "江雪是什么意思", "鹅鹅鹅后面是什么?", "这首诗讲的什么"]


def replay():
    r = Researcher(store=None, enabled=False, contact="", providers=[LibraryProvider()], guess=None, qa_judge=None,
                   rewrite=lambda q, lang: {"kind": "chat", "topic": "other", "query": ""})
    print("| Child | Entry attached |\n|---|---|")
    for q in CONVERSATION:
        d = r.decide(q, "zh")
        res = r.fetch(d, "zh") if d.go else None
        print(f"| {q} | {res.title + ': ' + res.text[:50] if res else '-'} |")


def leave_one_out(n: int):
    random.seed(7)
    for lang in ("zh", "en"):
        E = [e for e in json.loads((Q.SEED_DIR / f"qa_{lang}.json").read_text(encoding="utf-8")) if e["kind"] == "qa"]
        trials = random.sample([(i, alt) for i, e in enumerate(E) for alt in e["alt"]], n)
        right = wrong = none = 0
        times, wrongs = [], []
        for i, alt in trials:
            store = Q.QAStore.__new__(Q.QAStore)
            store._entries = {str(j): Q.QA(id=str(j), lang=lang, q=e["q"], a=e["a"], alt=[x for x in e["alt"] if not (j == i and x == alt)])
                              for j, e in enumerate(E)}
            store.status = lambda _id: "approved"
            t = time.perf_counter()
            hit = store.match(alt, lang, judge=Q.judge_with_model)
            times.append(time.perf_counter() - t)
            if hit is None:
                none += 1
            elif hit.id == str(i):
                right += 1
            else:
                wrong += 1
                wrongs.append(f"{alt} -> {hit.q} (should be {E[i]['q']})")
        times.sort()
        print(f"\n{lang}: right {right}, wrong {wrong}, none {none} of {n}; median {times[n // 2]:.2f} s, max {times[-1]:.2f} s")
        for w in wrongs:
            print("  wrong:", w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=80)
    args = ap.parse_args()
    replay()
    leave_one_out(args.sample)


if __name__ == "__main__":
    main()
