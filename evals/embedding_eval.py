"""Offline experiment: would embeddings help the local library find the right article?

Compares, on the same questions:
  lexical  the library as it is (rewritten query, full-text search and rule-based ranking)
  rerank   the lexical candidate pool (exact title matches + full-text hits) re-ordered by embedding similarity
           to the child's original question
  hybrid   reciprocal-rank fusion of the lexical order and the embedding order over that pool
  dense    nearest neighbours over an embedding index of the whole library (same language)
  dense+   fusion of the lexical order and the dense order

Questions: the 53 cases of evals/library_eval.py plus 30 more (real misses from the child's first days and typical
"why" and "biggest/fastest" questions). Some have no good article in the library ("-"): a method is right there only
if it returns nothing, which for embeddings needs a similarity threshold (reported separately).

Runs in its own process with sentence-transformers (not Ollama), so the running pet server and its loaded model are
untouched; it pauses while the child has a session open. Nothing in the project environment changes:

  HF_HUB_OFFLINE=0 uv run --with sentence-transformers --with psutil python evals/embedding_eval.py --model e5-small --dense

Index files go to --work (default: a scratch folder you pass); results print as Markdown.
"""

import argparse
import importlib.util
import json
import math
import os
import sqlite3
import time
from pathlib import Path

import numpy as np

from curiosity_pet import config
from curiosity_pet.library import DICTIONARY_SOURCES, Library, definition_intent

MODELS = {
    "e5-small": {"name": "intfloat/multilingual-e5-small", "query": "query: ", "passage": "passage: "},
    "qwen3-0.6b": {"name": "Qwen/Qwen3-Embedding-0.6B",
                   "query": "Instruct: Given a child's question, retrieve the encyclopedia passage that answers it\nQuery: ",
                   "passage": ""},
    "bge-m3": {"name": "BAAI/bge-m3", "query": "", "passage": ""},
}

# (original question, language, rewritten query as the pet's rewriter produces it, acceptable first results; "-" = none)
EXTRA = [
    # Real misses and weak answers from the child's first days (turns in pet.db)
    ("最老的树是多老?", "zh", "最老 树", "-"),
    ("What's the oldest tree?", "en", "oldest tree", "Pando (tree)"),
    ("世界上最大的数是多少?", "zh", "最大 数", "无穷|古戈尔|古戈尔普勒克斯"),
    ("你说说特斯拉的故事", "zh", "特斯拉 故事", "尼古拉·特斯拉"),
    ("What's the tallest building?", "en", "tallest building", "Burj Khalifa|List of tallest buildings"),
    ("你的数学水平怎么样?", "zh", "数学 水平", "-"),
    ("Now, how many percent of battery?", "en", "battery percent", "-"),
    # Typical "why" questions where the answer's words differ from the question's
    ("星星为什么会眨眼?", "zh", "星星 眨眼", "恒星"),
    ("Why do stars twinkle?", "en", "stars twinkle", "Star"),
    ("天空为什么是蓝色的?", "zh", "天空 蓝色", "瑞利散射"),
    ("Why is the sky blue?", "en", "sky blue", "Rayleigh scattering|Sky"),
    ("为什么会打雷?", "zh", "打雷", "雷|雷暴|闪电"),
    ("Why do leaves change color in fall?", "en", "leaves change color", "Leaf"),
    ("鱼在水里怎么呼吸?", "zh", "鱼 呼吸", "鳃|鱼"),
    ("How do airplanes fly?", "en", "airplanes fly", "Airplane|Lift (force)|Flight"),
    ("为什么月亮会变形状?", "zh", "月亮 形状", "月相|月球"),
    ("Why does the moon change shape?", "en", "moon change shape", "Phases of the Moon|Moon"),
    ("恐龙为什么灭绝了?", "zh", "恐龙 灭绝", "白垩纪—古近纪灭绝事件|恐龙"),
    ("为什么冬天会下雪?", "zh", "冬天 下雪", "雪"),
    ("Why do we need to sleep?", "en", "sleep", "Sleep"),
    ("植物怎么吃东西?", "zh", "植物 吃", "光合作用"),
    ("How do plants make their food?", "en", "plants make food", "Photosynthesis"),
    ("Why do cats purr?", "en", "cats purr", "Cat|purr"),
    # Superlatives ("世界之最"), frequent in real use
    ("What is the biggest animal in the world?", "en", "biggest animal", "Blue whale*"),
    ("世界上最大的动物是什么?", "zh", "最大 动物", "蓝鲸"),
    ("What is the fastest animal?", "en", "fastest animal", "Cheetah*|Peregrine falcon"),
    ("跑得最快的动物是什么?", "zh", "最快 动物", "猎豹|游隼"),
    ("世界上最高的山是哪座?", "zh", "最高 山", "珠穆朗玛峰"),
    ("What is the tallest mountain?", "en", "tallest mountain", "Mount Everest"),
    ("世界上最高的楼是哪个?", "zh", "最高 楼", "哈利法塔"),
]


def load_cases():
    spec = importlib.util.spec_from_file_location("library_eval", Path(__file__).with_name("library_eval.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = [(q, lang, q, expect, "eval set") for q, lang, expect in mod.CASES]
    return base + [(q, lang, rq, expect, "real/semantic") for q, lang, rq, expect in EXTRA]


def child_session_open(idle_s: int = 300) -> bool:
    """The child is using the pet: a session is open and someone spoke in the last few minutes
    (the watch client leaves its session open after the conversation ends)."""
    try:
        db = sqlite3.connect(f"file:{config.DATA_DIR / 'pet.db'}?mode=ro", uri=True)
        open_ = db.execute("SELECT COUNT(*) FROM sessions WHERE end_ts IS NULL").fetchone()[0]
        last = db.execute("SELECT MAX(ts) FROM turns").fetchone()[0] or 0
        return open_ > 0 and time.time() - last < idle_s
    except sqlite3.Error:
        return False


def wait_for_quiet(log):
    if child_session_open():
        log("A pet session is open: pausing until it ends")
        while child_session_open():
            time.sleep(15)
        log("Session ended, continuing")


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1e6


def doc_text(title: str, lead: str) -> str:
    return f"{title}: {lead[:400]}"


def candidate_pool(lib: Library, query: str, lang: str, question: str):
    """Everything the lexical stage considers (exact title or redirect matches and full-text hits), before its ranking
    rules; like the library, dictionary entries and xiehouyu only when the child asks what a word means."""
    terms = [t for t in query.split() if t]
    with lib._connect() as db:
        exact = lib._exact(db, terms, lang)
        ids = list(dict.fromkeys(list(exact) + lib._fulltext(db, terms, lang)))
        if not ids:
            return []
        rows = db.execute(f"SELECT id, title, lead, source FROM docs WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    keep_dictionary = definition_intent(question, lang) == "definition" or any(w in query.lower() for w in ("meaning", "意思"))
    return [(i, t, l) for i, t, l, src in rows if keep_dictionary or src not in DICTIONARY_SOURCES | {"xiehouyu"}]


def rrf(*rankings, k=60):
    score = {}
    for ranking in rankings:
        for r, key in enumerate(ranking):
            score[key] = score.get(key, 0.0) + 1.0 / (k + r + 1)
    return sorted(score, key=lambda x: -score[x])


def build_index(model, spec, lib: Library, work: Path, lang: str, batch: int, log):
    """Embeddings of every library entry in one language (fp16), cached in work/."""
    vec_path, id_path = work / f"{lang}.npy", work / f"{lang}.ids.npy"
    if vec_path.exists() and id_path.exists():
        return np.load(vec_path, mmap_mode="r"), np.load(id_path), None
    with lib._connect() as db:
        rows = db.execute("SELECT id, title, lead FROM docs WHERE lang = ? ORDER BY id", [lang]).fetchall()
    ids = np.array([r[0] for r in rows], dtype=np.int64)
    out = np.lib.format.open_memmap(work / f"{lang}.partial.npy", mode="w+", dtype=np.float16,
                                    shape=(len(rows), model.get_sentence_embedding_dimension()))
    t0, done = time.time(), 0
    chunk = batch * 50
    for start in range(0, len(rows), chunk):
        wait_for_quiet(log)
        part = rows[start : start + chunk]
        emb = model.encode([spec["passage"] + doc_text(t, l) for _, t, l in part], batch_size=batch,
                           normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        out[start : start + len(part)] = emb.astype(np.float16)
        done += len(part)
        if (start // chunk) % 10 == 0:
            log(f"  {lang}: {done}/{len(rows)} entries, {done / (time.time() - t0):.0f}/s, rss {rss_mb():.0f} MB")
    out.flush()
    del out
    os.replace(work / f"{lang}.partial.npy", vec_path)
    np.save(id_path, ids)
    return np.load(vec_path, mmap_mode="r"), ids, {"seconds": time.time() - t0, "entries": len(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="e5-small", choices=list(MODELS))
    ap.add_argument("--dense", action="store_true", help="also build a full index of the library and search it")
    ap.add_argument("--work", default=str(config.DATA_DIR / "library" / "embedding-experiment"))
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--sample", type=int, default=0, help="only time encoding of this many entries (no full index)")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    log = lambda m: print(m, flush=True)  # noqa: E731

    import torch
    from sentence_transformers import SentenceTransformer

    spec = MODELS[args.model]
    work = Path(args.work) / args.model
    work.mkdir(parents=True, exist_ok=True)
    lib = Library()
    cases = load_cases()
    report = {"model": spec["name"], "rss_start_mb": rss_mb()}

    wait_for_quiet(log)
    t0 = time.time()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    kwargs = {"model_kwargs": {"torch_dtype": torch.float16}} if args.model != "e5-small" else {}
    model = SentenceTransformer(spec["name"], device=device, **kwargs)
    model.max_seq_length = 192
    report.update(load_s=time.time() - t0, rss_model_mb=rss_mb(), device=device,
                  params_m=sum(p.numel() for p in model.parameters()) / 1e6, dim=model.get_sentence_embedding_dimension())
    log(f"{spec['name']}: {report['params_m']:.0f}M parameters, dim {report['dim']}, loaded in {report['load_s']:.1f} s, rss {report['rss_model_mb']:.0f} MB")

    def enc(texts, batch=32):
        return model.encode(texts, batch_size=batch, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)

    enc([spec["query"] + "warm up"])  # first call compiles kernels

    if args.sample:
        with lib._connect() as db:
            rows = db.execute("SELECT title, lead FROM docs ORDER BY RANDOM() LIMIT ?", [args.sample]).fetchall()
        t = time.time()
        enc([spec["passage"] + doc_text(a, b) for a, b in rows], batch=args.batch)
        rate = args.sample / (time.time() - t)
        total = 535045
        report.update(sample_rate=rate, full_index_minutes=total / rate / 60, rss_after_sample_mb=rss_mb())
        log(f"Encoding: {rate:.0f} entries/s, full library ({total}) would take about {total / rate / 60:.0f} min")

    indexes = {}
    if args.dense:
        for lang in ("zh", "en"):
            vecs, ids, built = build_index(model, spec, lib, work, lang, args.batch, log)
            indexes[lang] = (vecs, ids)
            if built:
                report[f"index_{lang}"] = built
        report["index_mb"] = sum(v.nbytes for v, _ in indexes.values()) / 1e6
        report["rss_index_mb"] = rss_mb()

    results, timing = [], {"query": [], "rerank": [], "dense": []}
    for q, lang, rq, expect, group in cases:
        accepted = expect.split("|")  # "Cheetah*" also accepts "Cheetah (Big Cats)" from Wikijunior

        def is_ok(title, accepted=accepted):
            return any(title == a or (a.endswith("*") and title.startswith(a[:-1])) for a in accepted)

        lex = lib.search(rq, lang, limit=40)
        lex_titles = [r.title for r in lex]
        pool = candidate_pool(lib, rq, lang, q)

        t = time.perf_counter()
        qv = enc([spec["query"] + q])[0]
        timing["query"].append(time.perf_counter() - t)

        row = {"q": q, "lang": lang, "expect": expect, "group": group, "lexical": lex_titles[0] if lex_titles else "-"}
        if pool:
            t = time.perf_counter()
            dv = enc([spec["passage"] + doc_text(title, lead) for _, title, lead in pool])
            timing["rerank"].append(time.perf_counter() - t)
            sims = dv @ qv
            order = [pool[i][1] for i in np.argsort(-sims)]
            row["rerank"], row["rerank_sim"] = order[0], float(sims.max())
            row["hybrid"] = rrf(lex_titles, order)[0] if lex_titles else order[0]
        else:
            row["rerank"] = row["hybrid"] = "-"
            row["rerank_sim"] = 0.0
        if indexes:
            vecs, ids = indexes[lang]
            t = time.perf_counter()
            sims = np.asarray(vecs @ qv.astype(np.float16), dtype=np.float32)
            top = np.argpartition(-sims, 40)[:40]
            top = top[np.argsort(-sims[top])]
            timing["dense"].append(time.perf_counter() - t)
            with lib._connect() as db:
                meta = {i: (tt, src) for i, tt, src in db.execute(
                    f"SELECT id, title, source FROM docs WHERE id IN ({','.join('?' * len(top))})", [int(ids[j]) for j in top])}
            keep_dictionary = definition_intent(q, lang) == "definition" or any(w in rq.lower() for w in ("meaning", "意思"))
            kept = [j for j in top if keep_dictionary or meta[int(ids[j])][1] not in DICTIONARY_SOURCES | {"xiehouyu"}][:10]
            top = np.array(kept)
            dense_titles = [meta[int(ids[j])][0] for j in top]
            row["dense"], row["dense_sim"] = dense_titles[0], float(sims[top[0]])
            row["dense+"] = rrf(lex_titles[:10], dense_titles)[0] if lex_titles else dense_titles[0]
        for m in ("lexical", "rerank", "hybrid", "dense", "dense+"):
            if m in row:
                row[m + "_ok"] = is_ok(row[m])
        results.append(row)

    report["timing_ms"] = {k: 1000 * float(np.median(v)) for k, v in timing.items() if v}
    report["rss_end_mb"] = rss_mb()
    if device == "mps":
        report["mps_driver_mb"] = torch.mps.driver_allocated_memory() / 1e6

    methods = [m for m in ("lexical", "rerank", "hybrid", "dense", "dense+") if m in results[0]]
    print(f"\n## {spec['name']}\n")
    print("| Group | Cases | " + " | ".join(methods) + " |\n|---|---|" + "---|" * len(methods))
    for group in ("eval set", "real/semantic", "all"):
        rows = [r for r in results if group == "all" or r["group"] == group]
        print(f"| {group} | {len(rows)} | " + " | ".join(f"{sum(r[m + '_ok'] for r in rows)}" for m in methods) + " |")
    print("\nCases where the methods disagree:\n")
    print("| Question | Expected | " + " | ".join(methods) + " |\n|---|---|" + "---|" * len(methods))
    for r in results:
        if len({r[m + "_ok"] for m in methods}) > 1:
            print(f"| {r['q']} | {r['expect']} | " + " | ".join(("**" if r[m + '_ok'] else "") + r[m] + ("**" if r[m + '_ok'] else "") for m in methods) + " |")
    sims_none = [r.get("dense_sim", r["rerank_sim"]) for r in results if r["expect"] == "-"]
    sims_ok = [r.get("dense_sim", r["rerank_sim"]) for r in results if r["expect"] != "-"]
    print(f"\nTop similarity, questions with no good article: {[round(s, 3) for s in sims_none]}; "
          f"others: median {np.median(sims_ok):.3f}, min {min(sims_ok):.3f}")
    print("\n" + json.dumps({k: v for k, v in report.items()}, ensure_ascii=False, indent=1, default=float))
    if args.json:
        Path(args.json).write_text(json.dumps({"report": report, "results": results}, ensure_ascii=False, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
