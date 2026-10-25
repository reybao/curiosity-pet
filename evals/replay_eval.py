"""Replay evaluation: run real conversations through today's pipeline and score how each turn was handled.

Data (never in git, hard constraint 6): DATA_DIR/replay/turns.jsonl (exported real turns, with the pet's previous
sentence) and DATA_DIR/replay/labels.json (what each turn was: id -> {"intent", "context"}).

Each exploration is replayed in order through a fresh Pet with the real local model, so state (a pending riddle, a
pending "要我告诉妈妈吗?") builds up as it did. Nothing leaves the machine and nothing is recorded for real:
- lookups use the local library only (no network);
- call_parent uses a fake sender; the concern push is switched off;
- usage records go to a temporary database.

Scoring:
- route accuracy: the path the pipeline took (Turn.route) against the routes allowed for the labelled intent;
- turns whose label needs a context that the replay did not reproduce (the model asked a different question this
  time) are listed as "context changed" and left out of the accuracy;
- quality flags on every turn: silent (nothing said although it should answer), claim (the model wrote that it did
  something only the program can do), two or more questions in one answer;
- time to first audio per route.

Usage: uv run python evals/replay_eval.py [--ids 1,2,3] [--limit N] [--summary FILE]
Writes the full report with the child's words to DATA_DIR/replay/report-<time>.md (local only); --summary writes
only aggregate numbers, safe for evals/results.
"""

import argparse
import json
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

# Allowed routes per labelled intent. "side" is talk not addressed to the pet (adults, a car's navigation voice):
# ideally ignored; router.py catches some of it (short or third-person messages).
ROUTES = {
    "noise": {"ignore"},
    "garbled": {"ignore", "clarify"},
    "side": {"ignore", "clarify"},
    "chat": {"model"},
    "about_pet": {"model"},
    "ability": {"model"},
    "answer": {"model"},
    "distress": {"model"},
    "knowledge": {"lookup"},
    "followup": {"lookup", "model"},
    "correction": {"lookup", "model"},
    "pet_or_knowledge": {"lookup", "model"},
    "idiom": {"lookup"},
    "idiom_more": {"lookup", "model"},
    "poem": {"lookup"},
    "poem_more": {"lookup", "model"},
    "story": {"story"},
    "math": {"math"},
    "time": {"time"},
    "riddle_request": {"riddle_pet"},
    "riddle_answer": {"riddle_pet"},
    "riddle_tell": {"riddle_child"},
    "riddle_fragment": {"riddle_child", "clarify", "ignore"},
    "riddle_any": {"riddle_pet", "riddle_child"},
    "call": {"call"},
    "call_reply": {"call"},
    "call_status": {"call"},
    "garbled_or_call": {"ignore", "clarify", "call"},
    "harm": {"safety"},
    "memory_q": {"memory"},
    "goodbye": {"goodbye"},
}
FAKE_CALL_SETTINGS = {"call_parent": {"telegram": {"bot_token": "replay", "chat_ids": {"dad": "d", "mom": "m"}}}}


class CaptureTTS:
    def __init__(self):
        self.speed = 1.0

    def synthesize(self, text, lang, speed=None):
        return np.zeros(10, dtype=np.float32)


class NoPlayer:
    def play(self, audio, text=None, on_start=None):
        pass


def load(data_dir: Path):
    turns = [json.loads(line) for line in (data_dir / "turns.jsonl").open(encoding="utf-8")]
    labels = json.loads((data_dir / "labels.json").read_text(encoding="utf-8"))
    return turns, labels


def context_of(pet, last_sentences: list[str]) -> set[str]:
    from curiosity_pet.followup import ends_with_question

    ctx = set()
    if pet.calls.pending is not None:
        ctx.add("call_pending")
    if pet.riddles.pending is not None:
        ctx.add("pet_riddle")
    if pet.riddles.child_stage is not None:
        ctx.add("child_riddle")
    if last_sentences and ends_with_question(last_sentences[-1]):
        ctx.add("pet_asked")
    return ctx


def make_pet(store, researcher, use_router=False):
    from curiosity_pet import call_parent
    from curiosity_pet.pipeline import Pet
    from curiosity_pet.usage import UsageLog

    from curiosity_pet.router import Router

    pet = Pet(asr=None, tts=CaptureTTS(), player=NoPlayer(), researcher=researcher, usage=UsageLog(store, client="ipad"),
              router=Router() if use_router else None)
    pet.calls = call_parent.CallParent("ipad", None, send=lambda opts, chat, text: True, limit=call_parent.RateLimit(),
                                       settings=lambda: FAKE_CALL_SETTINGS)
    return pet


def replay(turns, labels, ids=None, limit=None, log=print, researcher=None, use_router=False):
    from curiosity_pet import call_parent, config, utterance
    from curiosity_pet.followup import ends_with_question
    from curiosity_pet.lookup import Researcher
    from curiosity_pet.search import LibraryProvider
    from curiosity_pet.store import Store

    call_parent.notify_concern = lambda *a, **k: None  # never push real alerts from a replay
    config.activate_skin("cat", save=False)
    if researcher is None:
        researcher = Researcher(store=None, enabled=False, providers=[LibraryProvider()])
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "replay.db")
    chosen = [t for t in turns if (ids is None or t["id"] in ids)]
    if limit:
        chosen = chosen[:limit]
    by_session = defaultdict(list)
    for t in chosen:
        by_session[t["session"]].append(t)
    rows = []
    for sid, session_turns in by_session.items():
        pet = make_pet(store, researcher, use_router)
        last: list[str] = []
        for t in session_turns:
            label = labels.get(str(t["id"]), {})
            ctx = context_of(pet, last)
            started = time.perf_counter()
            turn = pet.answer(t["question"], t["lang"])
            elapsed = time.perf_counter() - started
            raw = turn.answer or ""
            said = ("" if turn.lang == "zh" else " ").join(turn.sentences)
            intent = label.get("intent")
            need = label.get("context")
            allowed = ROUTES.get(intent, set())
            status = "unlabelled" if not intent else ("context_changed" if need and need not in ctx
                                                      else ("ok" if turn.route in allowed else "wrong"))
            flags = []
            model_spoke = turn.first_token_s is not None  # program lines (call, riddle, math) are not judged here
            if turn.route not in ("ignore",) and not turn.sentences:
                flags.append("silent")
            if model_spoke and (utterance.PASS_ON.search(raw) or utterance.FALSE_ABILITY.search(raw)):
                flags.append("claim")
            if model_spoke and sum(ends_with_question(s) for s in turn.sentences) >= 2:
                flags.append("two_questions")
            rows.append({"id": t["id"], "session": sid, "question": t["question"], "intent": intent, "context": need,
                         "actual_context": sorted(ctx), "route": turn.route, "allowed": sorted(allowed), "status": status,
                         "flags": flags, "said": said, "judged": turn.intent, "first_audio_s": turn.first_audio_s, "elapsed_s": round(elapsed, 2)})
            log(f"{t['id']:>4} {status:<15} {turn.route:<12} {intent or '-':<16} {turn.intent or '':<14} {' '.join(flags)}")
            last = turn.sentences or last if turn.route != "ignore" else last
    tmp.cleanup()
    return rows


def summarize(rows) -> dict:
    scored = [r for r in rows if r["status"] in ("ok", "wrong")]
    by_intent = defaultdict(lambda: [0, 0])
    confusion = Counter()
    for r in scored:
        by_intent[r["intent"]][0] += r["status"] == "ok"
        by_intent[r["intent"]][1] += 1
        if r["status"] == "wrong":
            confusion[(r["intent"], r["route"])] += 1
    flags = Counter(f for r in rows for f in r["flags"])
    times = defaultdict(list)
    for r in rows:
        if r["first_audio_s"] is not None:
            times[r["route"]].append(r["first_audio_s"])
    return {
        "turns": len(rows),
        "scored": len(scored),
        "correct": sum(r["status"] == "ok" for r in scored),
        "context_changed": sum(r["status"] == "context_changed" for r in rows),
        "by_intent": {k: v for k, v in sorted(by_intent.items(), key=lambda kv: kv[1][0] / kv[1][1])},
        "confusion": confusion.most_common(),
        "flags": dict(flags),
        "first_audio_median": {k: round(statistics.median(v), 2) for k, v in times.items()},
    }


def report(rows, s) -> str:
    acc = s["correct"] / s["scored"] if s["scored"] else 0
    out = [f"# Replay report {time.strftime('%Y-%m-%d %H:%M')}", "",
           f"Route accuracy: {s['correct']}/{s['scored']} ({acc:.0%}); context changed: {s['context_changed']}; "
           f"turns: {s['turns']}", "", "## By intent", "", "| Intent | Correct |", "|---|---|"]
    out += [f"| {k} | {v[0]}/{v[1]} |" for k, v in s["by_intent"].items()]
    out += ["", "## Most common mistakes (intent -> route taken)", ""]
    out += [f"- {i} -> {r}: {n}" for (i, r), n in s["confusion"]]
    out += ["", f"## Quality flags: {s['flags']}", "", f"## Median time to first audio by route: {s['first_audio_median']}",
            "", "## Turns that went wrong or were flagged", ""]
    for r in rows:
        if r["status"] == "wrong" or r["flags"]:
            out.append(f"- #{r['id']} [{r['intent']} -> {r['route']}] {' '.join(r['flags'])} | {r['question']} | {r['said'][:120]}")
    out += ["", "## Context changed (not scored)", ""]
    out += [f"- #{r['id']} needed {r['context']}, had {r['actual_context']} | {r['question']}" for r in rows
            if r["status"] == "context_changed"]
    return "\n".join(out) + "\n"


def summary_only(s) -> str:
    """Aggregate numbers only: no child words, safe to commit."""
    acc = s["correct"] / s["scored"] if s["scored"] else 0
    lines = [f"Route accuracy {s['correct']}/{s['scored']} ({acc:.0%}), context changed {s['context_changed']}, "
             f"turns {s['turns']}", "", "| Intent | Correct |", "|---|---|"]
    lines += [f"| {k} | {v[0]}/{v[1]} |" for k, v in s["by_intent"].items()]
    lines += ["", "Mistakes (intent -> route): " + ", ".join(f"{i} -> {r} x{n}" for (i, r), n in s["confusion"]),
              "", f"Quality flags: {s['flags']}", f"Median first audio by route (s): {s['first_audio_median']}"]
    return "\n".join(lines) + "\n"


def main():
    from curiosity_pet import config

    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="comma-separated turn ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--summary", help="also write aggregate numbers (no child words) to this file")
    ap.add_argument("--router", action="store_true", help="turn on the context-aware router (router.py)")
    args = ap.parse_args()
    data_dir = config.DATA_DIR / "replay"
    turns, labels = load(data_dir)
    ids = {int(x) for x in args.ids.split(",")} if args.ids else None
    rows = replay(turns, labels, ids=ids, limit=args.limit, use_router=args.router)
    s = summarize(rows)
    stamp = time.strftime("%Y%m%d-%H%M")
    (data_dir / f"report-{stamp}.md").write_text(report(rows, s), encoding="utf-8")
    (data_dir / f"rows-{stamp}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nRoute accuracy {s['correct']}/{s['scored']}; context changed {s['context_changed']}; flags {s['flags']}")
    print(f"Full report: {data_dir / f'report-{stamp}.md'}")
    if args.summary:
        Path(args.summary).write_text(summary_only(s), encoding="utf-8")


if __name__ == "__main__":
    main()
