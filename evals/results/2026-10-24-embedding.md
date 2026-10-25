# 2026-10-24: Embedding experiment for the local library (offline)

Question: would embedding search find better articles than the library's keyword search?
Scripts: `evals/embedding_eval.py` (embeddings, run in its own process with sentence-transformers, not Ollama, pausing
while the child talks to the pet) and `evals/answer_guess_eval.py` (an alternative found during the experiment).

## Questions

83 cases: the 53 of `evals/library_eval.py` (the keyword ranking was tuned on these, so it has a home advantage there)
and 30 new ones: 7 real misses or weak answers from the child's first days (oldest tree, biggest number, Tesla, tallest
building, two that should find nothing), 16 "why" questions whose answer uses other words than the question, and 7
superlatives ("世界之最"), half in Chinese, half in English. The 30 new cases are the fair comparison.

## Methods

- lexical: the library today (model-rewritten query, full-text search, rule-based ranking)
- rerank: the keyword candidate pool (before ranking rules) ordered by embedding similarity to the child's question
- hybrid: reciprocal-rank fusion of the keyword order and the embedding order
- dense: nearest neighbours over an embedding index of the whole library (535k entries)
- dense+: fusion of the keyword order and the dense order
- guess: the chat model names the likely answer ("蓝鲸"); its library entry is used when the title matches exactly,
  otherwise the keyword result (no embedding model)

## Results (first result right)

| Method | Model | Eval set (53) | New cases (30) | All (83) |
|---|---|---|---|---|
| lexical | none | 53 | 12 | 65 |
| rerank | multilingual-e5-small | 37 | 9 | 46 |
| hybrid | multilingual-e5-small | 43 | 12 | 55 |
| dense | multilingual-e5-small | 32 | 11 | 43 |
| dense+ | multilingual-e5-small | 42 | 11 | 53 |
| rerank | Qwen3-Embedding-0.6B | 39 | 11 | 50 |
| hybrid | Qwen3-Embedding-0.6B | 43 | 12 | 55 |
| guess, exact title | pet-chat-9b (already loaded) | 52 | 19 | 71 |
| guess first, any result | pet-chat-9b | 50 | 19 | 69 |

Dense search with Qwen3 was not run: see cost below.

What embeddings found that keywords missed: 尼古拉·特斯拉 ("你说说特斯拉的故事"), Burj Khalifa, 鳃 (fish breathing), Phases of
the Moon, 雪 ("为什么冬天会下雪"), 蓝鲸, Cheetah. What they broke: surface-similar entries win (眨眼 for twinkling stars,
灭绝 instead of the Cretaceous extinction, "Purr by Katy Perry" for cats purring, movie versions of Snow Queen and Peter
Rabbit, 冰皮月饼 for 中秋节). Similarity scores sit in a narrow band (e5: 0.84 to 0.92 for right and wrong alike), so no
threshold can say "the library has nothing on this".

The guess method fixed all 7 superlatives (Blue whale, 蓝鲸, Peregrine falcon, 猎豹, 珠穆朗玛峰, Mount Everest, 哈利法塔) and
changed one eval case ("Tale of Peter Rabbit" now returns the Peter Rabbit article). One risk seen: for "What's the oldest
tree?" the model named Methuselah, and the library's "Methuselah" is the biblical person; a real implementation must
also require a query word ("tree") in the chosen entry. For "why" questions the model named no single thing, so nothing
changed there (瑞利散射 for the blue sky, 光合作用 for how plants eat are still missed).

## Cost on the Mac mini (16 GB, pet-chat-9b and the speech models loaded)

| | multilingual-e5-small | Qwen3-Embedding-0.6B | guess |
|---|---|---|---|
| Parameters | 118M | 596M (fp16) | none extra |
| GPU memory (MPS) | 1.1 GB | 2.3 GB | none extra |
| Embedding one question | 8 ms | 36 ms | |
| Reranking about 20 candidates | 51 ms | 756 ms | |
| Indexing the whole library | 25 min (380 entries/s; 410 MB index) | about 9 h (16 entries/s) | none |
| Dense search over the index | 109 ms | not run | |
| Extra time per lookup | 0.06 to 0.12 s | 0.8 s | 2.4 s as a separate call; about 0 if folded into the existing rewrite call |

The Qwen3 run pushed swap from 1 GB to 4.7 GB; later in the day swap reached 13 GB with a watchOS simulator from another
session running at the same time, and the 9B and speech models were partly paged out. A warm-up request to Ollama
brought the 9B back (1.75 s, then 0.5 s). No pet session was open during the runs (the script paused while the child
was talking on the watch).

## Conclusion

Embeddings are not worth adding now: the small model that fits makes every mode worse than the keyword search, and the
larger one is no better while costing 0.8 s per lookup, 2.3 GB of GPU memory and a 9-hour index. The useful idea is the
answer name: ask the rewrite call to also name the answer, look that title up locally, and keep it only when the entry
also mentions a query word. It needs no new model and costs nothing extra when folded into the existing call.

Leftovers: the experiment index was deleted (the library was rebuilt afterwards, so its ids no longer matched). The two
embedding models remain in the shared Hugging Face cache (about 1.7 GB, next to the speech models); remove only them with
`huggingface-cli delete-cache` if wanted.

## Follow-up: the answer name, built in (same evening)

The parent approved building the answer-name lookup. First attempt, as proposed: an "answer" field added to the existing
rewrite call. It failed on the 9B: with the extra field the rewrite returned whole questions as search queries
("Why do zebras have stripes?" instead of "zebras stripes"):

| Rewrite prompt variant (36 questions) | Spoiled queries | Answer name filled | Median time |
|---|---|---|---|
| unchanged (no answer field) | 2 | not asked | 2.37 s |
| answer field described in the system prompt | 14 | 5 | 3.00 s |
| answer field described only in the JSON line | 17 | 3 | 3.30 s |

What was built instead: the rewrite prompt stays exactly as before; a separate short call (`lookup.guess_answer`) names
the answer, only for questions whose answer is one named thing (`lookup.ANSWER_ASK`: 最大/最快/最高, 世界上, 谁发明,
biggest/fastest/tallest, who invented ...), and only after the "let me look it up" filler has started (it runs inside
`Researcher.fetch`). `Library.answer_entry` accepts the name only for an entry titled exactly like it (case, spaces and a
"(qualifier)" ignored; no dictionary entries or xiehouyu) that also mentions a word of the rewritten query (for Chinese,
character pairs of longer words count, because the rewrite sometimes keeps "世界上最高的楼" as one word). The name is used
only locally and never sent to an online provider.

Pet's own flow (`uv run python evals/answer_guess_eval.py --pipeline`, real rewrite and guess calls, library only), on the
30 real and "why"/superlative questions:

| | Right |
|---|---|
| without the answer name | 13 |
| with the answer name | 19 |

All 7 superlatives right (蓝鲸, Blue whale, Peregrine falcon, 猎豹, 珠穆朗玛峰, Mount Everest, 哈利法塔); "What's the oldest
tree?" got the name Methuselah, which the check rejected (the library's Methuselah is the biblical person). The 53 eval
cases are bare keyword queries that do not pass as questions in this flow; their keyword path is unchanged
(`library_eval.py` 53/53). Privacy eval with the restored prompt: 0 leaks, 0/22, 16/16.

Time to decide (rewrite, plus the guess when triggered): median 2.41 s without, 3.12 s with the guess call in the eval.
Live on the server, after moving the guess behind the filler: filler at 2.9 to 3.5 s for all questions (the machine was
under swap pressure at the time, non-triggered questions were equally slow); first real sentence 4.9 to 7.8 s for
superlative questions.

| Live question | Entry used |
|---|---|
| 世界上最大的动物是什么? | 蓝鲸 |
| What is the fastest animal? | Peregrine falcon |
| 世界上最高的楼是哪个? | 哈利法塔 |
| 世界上最高的山是哪座? | 珠穆朗玛峰 |
| What's the oldest tree? | Tree (Methuselah rejected) |
