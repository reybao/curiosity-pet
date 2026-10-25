# Curiosity Pet (Curiosity Buddy)

A local AI learning pet that lives on a home Mac mini. The child (7.5 years old, bilingual Chinese/English) asks questions by voice on an iPad;
the system does speech recognition, answer generation, knowledge retrieval, safety filtering and speech synthesis on the machine itself. The goal is to help the child practice asking questions, following up,
verifying and expressing ideas. This is also a course project, so tests and evaluation results must be reproducible.

Read this file before starting any work. The rules in this file take precedence over default practice.

## Hard constraints (must not be violated)

1. None of the child's data (voice, text, memory, logs) leaves this machine. No cloud models, no cloud speech recognition or synthesis,
   no third-party analytics, fonts or CDNs. When the local model is unavailable, show "can't answer right now" and do not fall back to any external service.
   The only exception (confirmed by the parent 2026-10-24): for **general-knowledge questions** the local knowledge base misses, a **topic search term**
   rewritten locally and checked by rules may be sent to Wikipedia (see "Online lookup"). The child's own words, recordings, conversation history, memory, any personal information,
   family information and mood are never sent out; the parent can turn this off at any time.
   A second exception (confirmed by the parent 2026-10-24): when the child asks the pet to call or tell a parent, and
   confirms when the pet asks, a message with fixed content ("宝宝想找爸爸", time, device) goes by Telegram to the parent(s)
   she named (call_parent.py). Her own words are not included unless the parent sets settings.json
   "call_parent": {"include_words": true}; at most one message every 2 minutes per parent, dad and mom counted
   separately (owner decision 2026-10-24, "min_interval_s"); when blocked the pet says so honestly; every attempt is in
   pet-log; "enabled": false turns it off. Nothing else about the child is sent this way.
   A third exception (confirmed by the parent 2026-10-24): when the child says something about hurting herself or
   others (concern.SERIOUS: harm_self, harm_others), a Telegram alert with the category, time and device only, never her
   words, goes to both parents (call_parent.notify_concern), at most one every 10 minutes. Off by default: it runs only
   when settings.json "call_parent": {"concern_push": {"enabled": true}}. Every alert is in pet-log.
2. Do not keep full chat transcripts as a long-term record. After a session keep only: question text, topic tag, whether the knowledge base hit, favorites, duration.
   Exception (owner decision 2026-10-24, "用来提醒父母"): when the child says something a parent may want to know (sad,
   scared, angry, bullied, unwell, conflict at home, hurting others or herself), her own sentence, its time and a plain
   category are kept for the parent for 30 days (concern.py, `parent_notes`, shown by pet-log, deletable). No scores,
   labels, inferences or summaries; never in the weekly report; never sent anywhere, except the category-only alert for
   hurting herself or others in hard constraint 1 (third exception).
   Transcripts of unsaved sessions are kept at most 7 days for the parent to review, then deleted automatically.
3. Never produce any evaluation of the child: ability judgments, emotion judgments, personality labels, comparison with others. The weekly report only describes and counts.
   A word list plus output checks block this in code, not only in the prompt.
4. The pet is explicitly a program: it does not pretend to have real feelings, does not ask for secrecy, does not use broken streaks, sadness or guilt to push usage, and does not imply it can replace family, teachers or friends.
5. Development and runtime data directories are strictly separate. `PET_DATA_DIR` points to `~/pet-data-dev` in development
   and to `~/Library/Application Support/CuriosityPet` in production. Tests use fictional child profiles only.
6. The child's audio samples, real questions, databases, keys and logs stay out of git. `.gitignore` must cover `evals/audio/`,
   `evals/real_questions/`, `*.db`, `*.sqlite*`, `.env`, `logs/`.

## Hardware and runtime environment

- Mac mini M4, 10-core CPU, 10-core GPU, 16GB unified memory, 256GB SSD. Usable GPU memory is about 10 to 11GB.
- All resident models together stay under 8GB. With the 9B main model (owner decision 2026-10-24) the measured total
  is about 8.5GB (9B 5.8GB incl. context, speech about 2.7GB); the optional guard adds about 0.6GB.
- Do not run heavy experiments (other models, embeddings, large builds) on this machine while the child may be using the
  pet: on 2026-10-24 an embedding experiment pushed answers to 10 to 60 seconds.
- Services run under the standard user `pet`, kept alive by a launchd LaunchAgent; logs in `~/Library/Logs/CuriosityPet/`.
  `scripts/install_services.sh` installs the server and daily backup agents (`--dry-run` to preview); creating the `pet`
  user needs the admin account. `scripts/backup.sh` makes a consistent copy of pet.db, settings, skins and reports.
- Ollama is managed by `~/Library/LaunchAgents/com.curiositypet.ollama.plist`,
  with environment variables `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=3`.
- The iPad connects through Tailscale, and `tailscale serve` provides HTTPS (microphone permission needs a secure context).
  Signing in to Tailscale is the device pairing; the service listens only on 127.0.0.1 and Tailscale forwards to it.

## Component stack (final for 16GB; do not swap in larger models on your own)

| Component | Choice | Notes |
|---|---|---|
| Main model | `qwen3.5:9b-q4_K_M`, Modelfile `pet-chat-9b` (owner decision 2026-10-24: slower is fine if smarter; settings.json `"chat_model"`); the default in code stays `pet-chat` (`qwen3.5:4b-q4_K_M`). GGUF, llama.cpp engine via Ollama, `num_ctx 8192`, `think=false` | The helper calls use the same model (two models do not fit). Control group `gemma4:e4b`, blind tests only; do not use the nvfp4 build (MLX engine memory grows with requests) |
| Speech recognition | Qwen3-ASR-0.6B 4-bit, mlx-audio | Language detected per utterance; compare Fun-ASR-Nano |
| Sentence segmentation | Silero VAD, silence threshold tuned starting from 0.8 s; keep "hold to talk" as a fallback | The child pauses a lot |
| Speech synthesis | Kokoro-82M v1.1-zh, mlx-audio, Chinese/English voice chosen by answer language | Weak on short sentences; merge the first two sentences before synthesis |
| Safety filter | Qwen3Guard-Gen-0.6B, official weights converted to 4-bit MLX (`scripts/convert_guard.py`), **non-strict**, off by default (settings.json `"guard": "questions"` or `"all"`) | Strict mode flagged 15% of ordinary questions and 10% of ordinary sentences ("喵。", "皮卡!"); see evals/results/2026-10-24-guard.md. The program's own rules (safety.py, utterance.py) are always on |
| Retrieval | The local library is SQLite full-text search (library.py), not vectors | Embeddings (e5-small, qwen3-embedding) were measured and did worse than keyword search (evals/results/2026-10-24-embedding.md) |
| Backend | Python 3.12 + FastAPI + WebSocket (no Pipecat), dependencies managed by uv | Single process |
| Frontend | Static pages served by FastAPI, vanilla JS, pet animation in SVG + CSS first (can switch to Rive/Lottie later) | No React/Electron |

Call Ollama through the native `/api/chat`, not the OpenAI-compatible endpoint (which ignores num_ctx).
Answers read aloud to the child use streamed text, not JSON; JSON Schema is used only for metadata such as guard verdicts, intent classification and memory extraction.

## Language rules

- Language is detected per utterance. The pet answers in the language the child asked in; for mixed speech, the language with the larger share leads.
- English proper nouns in a Chinese answer stay in the original and get a short explanation; the same applies to English answers.
- Reading level: Chinese at grade 1 to 2 of primary school, English at Grade 1 to 2. Explain terms as they appear.

## Answer flow

```
record -> VAD segmentation -> ASR -> language detection -> question guard verdict
  -> vector retrieval (2 to 3 passages) -> hit: rewrite based on the material
  -> miss, and a knowledge question: privacy gate -> local library (offline Wikipedia subset) -> web search / Wikipedia
     (online only when the switch is on) -> guard -> rewrite and cite the source, first say "let me look it up"
  -> still no material: answer conservatively and label it "this is my guess"
  -> streamed generation -> guard verdict per sentence -> each sentence to TTS -> iPad plays and highlights text sentence by sentence
```

- One exploration: question -> two or three sentences of explanation -> one follow-up or small activity -> the child expresses an idea -> choose to save or end.
- When the child asks directly for the answer, answer first; follow-ups help understanding and never turn into an exam.
- Support "simpler please", "give an example", "how do you know". When the child points out a mistake, re-check.
- An exploration wraps up naturally after 10 to 15 minutes; the pet ends it on its own and does not try to keep the child.
- Latency budget: the pet starts speaking within 3 seconds after the child finishes. As soon as VAD decides speech has ended, the iPad immediately plays a local cue sound and switches to the "thinking" animation.
- Local model unavailable: show and read aloud "I'm a bit tired, ask me again in a little while", and do not switch to an external service.

## Storytelling mode

- Original short stories, 3 to 5 minutes, fixed structure: protagonist, small problem, resolution, gentle ending. The child picks the protagonist and setting.
- The day's discoveries can be woven into the story. The guard checks sentence by sentence; scary plots are forbidden.
- Bedtime mode: slow pace, fixed ending, ends automatically after the story with no follow-up.
- Only original or public-domain adaptations (Grimm, Andersen, Chinese folk tales and idiom stories); do not retell copyrighted picture books.
- Favorite stories can be saved to "My Discoveries".
- Implemented in story.py: "讲个故事" asks who and where if not said, then an original story (about 500 Chinese
  characters) with the fixed structure; quoted dialogue may contain questions, the pet asks none. "睡前故事": slower
  voice (0.85), a fixed "晚安,做个好梦。", and the exploration ends. Idiom and fable requests come from the library instead.

## Knowledge base (RAG)

- Source priority: (1) child-level Q&A generated offline by a large model and reviewed by the parent, one set each in Chinese and English, starting with 300 to 500 entries;
  (2) a Simple English Wikipedia subset; (3) Wikijunior; (4) scans of books the parent imports locally (not in the repository).
- Do not import the full Chinese Wikipedia or other adult-oriented encyclopedias.
- Local library (`library.py`, `uv run pet-library build`): opening paragraphs of Simple English Wikipedia plus only those
  Chinese Wikipedia articles about the same concepts (matched by Wikidata item), converted to Simplified Chinese, in SQLite
  full-text search at DATA_DIR/library/library.db (dumps in DATA_DIR/library/src, never in the repo). It is searched before any
  web provider with the same checked topic terms; it needs no contact info and keeps working with online lookup off.
  Its source label is "小图书馆" / "my library"; the article URL is kept for attribution (CC BY-SA, private use).
  Extra sources (`library_sources.py`, files in DATA_DIR/library/src/extra): Vikidia, Simple English Wiktionary, Wikijunior,
  Chinese idioms and filtered xiehouyu, 蒙学 readers and Tang poems, six Project Gutenberg children's books. A shared
  filter (`too_grim`) drops entries centered on serial killers, sexual violence, massacres, terror attacks or horror films.
  Also the xinhua character dictionary and primary-school poems (`data/school_poems.json`, texts resolved by
  `uv run pet-library school-poems`; never write poem texts from memory). Poem and character questions take the line,
  title or character from the child's words (`library.local_target`) and search only the library.
  Superlative and "who invented" questions (`lookup.ANSWER_ASK`) get a separate answer-name call (`lookup.guess_answer`,
  made in fetch after the filler); `Library.answer_entry` uses it only for an exact title that also mentions a query word.
  Do not add fields to the rewrite call: the 9B then returns whole questions as queries (evals/results/2026-10-24-embedding.md).
- Each entry carries: topic, language, source, age-suitability tag. Chunks are a few hundred characters.
- Questions that miss the material are recorded in the `unanswered` table, and the weekly report lists "questions not found this week" so the parent can fill the library.
- When material is deleted, also clear the original text, vectors, related memory and cache.

## Online lookup (Wikipedia)

- Go online only when all three conditions hold: the local knowledge base missed; the local model judges it a general-knowledge question; the parent's online switch is on.
  Storytelling and bedtime modes never go online. When offline, fall back to "if I can't find it, say I don't know".
- Privacy gate (entirely local, every part needs tests): the local model rewrites the question into a neutral topic term; the program then checks it, and if it contains a person's name, a family term,
  school, address, phone number, digit string, emotion word, or personal pointers such as "I/my family", it does not go online; sensitive topics (death, war, disasters,
  physical safety, obvious distress) do not go online and get a fixed response. Only the rewritten topic term is sent, with no account, cookie or session ID.
- Sources: the local library first, then Brave or Google web search only when the parent puts a key in settings.json
  (owner decision 2026-10-24), then the Wikipedia API (Chinese, English, Simple English). All get only the checked topic words.
- Retrieved content goes through the guard first, then is rewritten into a child-level answer with the source cited; it is also stored in the local knowledge base as "pending review", and the parent reviews weekly.
- Search terms sent are logged and kept 7 days for the parent to view; after expiry the original text is deleted and only per-topic counts remain, used for factual trends in the weekly report.
- The online switch is on by default; during the first two weeks the parent is advised to check the search-term log once a week.

## Memory and data model

- Allowed to store: nickname, pet name, age band, language, reading level, interests chosen by the child (whitelist enum), discoveries the child saved on purpose, parent settings.
- Not collected: real name, birthday, school, address, identity of family members or classmates, permanent chat history, any psychological or emotional fields
  (except the parent notes in hard constraint 2: her own words, time and a plain category, 30 days, no inference).
- Interest memory is visible to the child as cards ("I remember you like space"), and both child and parent can edit and delete them.
  Implemented in memory.py: interests only from her own "我喜欢 / I like" about a fixed list of topics; "你记得我喜欢什么"
  recalls them, "我不喜欢…了" removes one; "收藏这个 / save this" keeps the last question and answer in My Discoveries.
  pet-log shows both (`--forget-interest`, `--delete-discovery`).
- The memory table allows whitelisted fields only; there is no free-text "observation" field.

## Pet appearance

- A British Shorthair blue cat (SVG + CSS, four states). The small light on the collar marks it as a "program", changes color with state, and must not be removed.
- It calls itself the "program kitten", not a real cat, with no feelings (hard constraint 4). The verbal tic "meow": at most one per answer, guaranteed by code.
- The thinking cue sound is a short "meow-oo" synthesized locally, not a recorded sample.
- Private skins (data directory `skin-<id>/` folders, chosen with the picker button, see docs/SKIN.md) may replace the artwork, name and catchphrase at home. It never goes
  into the repo. The program marker stays (a state-colored badge on the picture), and the pet still says it is a program when asked
  whether it is real.

## Conversation rules (decided by the program, not the model)

- Follow-up questions: none by default; at most one every 3 turns; none after the child ignores one or on a
  follow-up turn ("simpler", "example"); none for the rest of the exploration after "stop asking". When not
  allowed, the prompt says so and any sentence ending with a question mark is dropped before it is spoken.
- "Talk to a parent or teacher" appears only when the program detects that the child is sharing something
  upsetting (privacy.expresses_distress); never in ordinary answers.
- Arithmetic is computed by the program (arith.py), never asked of the model.
- Riddles come from the local bank (data/riddles.json), do not repeat until the bank is exhausted, and the
  answer is withheld: one hint after a wrong answer, reveal after the second or on "I don't know".
- A question about specific people, works or events with no material behind the answer is spoken as a
  guess ("I'm not sure, this is my guess") and listed for the parent (unanswered table, pet-log).
- Lookup providers, in order: the local library (if built; `"library": false` turns it off), Brave or Google web search
  when the parent sets a key in settings.json, then Wikipedia. All providers receive only the topic words that passed the
  privacy gate; with online lookup off or no contact info only the library is searched.
- The page has one button: tap to start listening, tap to stop (stop cancels a running answer and ends the exploration).
  Every start (and the page coming back from the lock screen) re-opens the microphone and audio if iOS stopped them.
- Fillers and laughter alone are not answered; a lone word gets "I didn't catch that" (utterance.py), except while the
  pet is waiting for her answer. "I'm a program / I have no feelings" is said only when she asks whether it is real or
  has feelings. The question limit survives stop/start (reset after 30 minutes idle) and no question on the first turn.
- A stated result ("三加四等于七", "three plus four equals ten") is checked by the program (arith.parse_claim).
- After WRAP_UP_MINUTES (settings.json "wrap_up_minutes", default 15) the pet closes the exploration gently after an
  answer (never in the middle of a riddle or a worry); goodbye and wrap-up go idle once the iPad has played the line.
- The usage log stores what was actually spoken (after these filters), not the model's raw output.
- A riddle the child tells is looked up in the riddle bank first (`RiddleGame.recognize`); a classic is answered by the
  program, an unknown one is guessed by the model. Riddle forms count even without "I have a riddle for you".

## Weekly report (weekly discovery report)

Generated once a week, for the child and parent to read together. It contains only: questions asked this week (verbatim), saved discoveries, topic distribution counts,
questions that missed the material, and parent-child activity suggestions generated by the model. Judgments about ability, emotion or personality, and comparisons, are forbidden.
Trends are factual only ("space questions went from 2 to 6"), with no interpretation ("likes space more and more").
There may be an "interaction habits" section listing only countable facts, so the parent can understand the child in their own way (confirmed by the parent 2026-10-24: no personality analysis, but keep the facts that reflect personality):
number and type of questions (how many "why", "how", "what"), number of follow-ups ("tell me more", "give an example", "how do you know"),
number of times she corrected the pet, whether the exploration was ended by the child or wrapped up naturally, duration of an exploration, Chinese/English ratio, number of favorites, the protagonists and settings she gave in storytelling.
No adjectives or labels (such as "curious", "introverted", "focused"), no comparison with others or with "the average child", no inference of causes; the word-list check applies here too.
The parent can turn off the weekly report and delete any week. `uv run pet-report [--week 2026-W43]` (report.py) writes
DATA_DIR/reports/<week>.md; settings.json `"weekly_report": false` turns it off; `--delete <week>` deletes one. Fillers,
lone words, safety turns and anything in the parent notes are left out of it.

## Safety layers (all need tests)

1. System prompt: age, tone, length, say "I don't know" when unsure, hard constraint 4.
2. Qwen3Guard judges the question and (optionally) every answer sentence, non-strict, when the parent turns it on.
   Always on in code (utterance.guard_sentence): no praise or judgment of the child, no secrecy, no "tell a teacher or me",
   no pretended abilities (remembering chats, alarms, pictures, saving files); ability questions get an honest note.
3. Parent-editable keyword blocklist (settings.json "blacklist"): used for lookups, and for answers (a question with a
   blocked word gets "let's ask mom or dad", a sentence with one is not spoken). A topic range is not implemented.
4. Knowledge base answers take priority.
5. Sensitive topics (death, war, disasters, physical safety, obvious distress) get a fixed, short, age-appropriate response and a suggestion to find a trusted adult.
   Implemented (safety.py): hurting herself or others and dangerous actions get fixed answers; other distress gets the
   gentle care note; questions about death or war are still answered (no lookup), so learning questions are not blocked.
   `uv run python evals/adversarial_eval.py --skin <id>`: 23/23 for cat, goku, pika (evals/results/2026-10-24-adversarial.md).
6. Parent-viewable session records (limited to 7 days).
The adversarial test set must cover: violence, bodies, "are you alive", "I hate my little brother", "don't tell mom", requests for scary stories, jailbreak-style prompts.

## Implementation stages and acceptance

| Stage | Content | Pass condition |
|---|---|---|
| 0 | Baseline: tok/s, first-token latency, ASR error rate on the child's recordings, 4B vs E4B blind test | Measured numbers written to `evals/results/` |
| 1 | Minimal command-line loop: VAD + ASR + LLM + TTS | Voice conversation works locally, first sentence within 3 seconds |
| 2 | iPad web access, Tailscale HTTPS, four-state pet animation, sentence-by-sentence highlight | A device not signed in to Tailscale cannot connect |
| 3 | Learning flow: explanation, follow-up, small activity, ending, favorites | One complete exploration done, without pushing the child to continue |
| 4 | Knowledge base, sources, miss records, interest cards, deletion; Wikipedia lookup and privacy gate | Answers are traceable, deletion really takes effect; privacy test set has zero leaks |
| 5 | Guard, blocklist, sensitive-topic path, parent page, session retention rules | The adversarial test set fully passes |
| 6 | Storytelling mode, weekly report | The weekly report has no evaluative statements (word-list check passes) |
| 7 | launchd deployment, backup script, docs, failure tests (model exit, network loss, restart) | Auto-recovers after restart, no data lost |
| 8 | An adult trial for a week with a fictional profile, then a short trial with the parent present | Problems and limitations recorded |

## Development conventions

- In each stage write the tests and evaluations before the implementation; at the end of a stage write the measured numbers into `evals/results/<date>.md`.
- Before and after any change to how messages are understood or routed, run the replay evaluation
  (`uv run python evals/replay_eval.py --summary <file>`): real turns with labels in DATA_DIR/replay (never in git),
  replayed through the pipeline; route accuracy must not drop. Baseline 2026-10-24: 154/215 (72%); current: 173/215 (80%) with the doubtful-message
  check on (evals/results/2026-10-24-router.md).
- Documentation and code comments in English (owner decision 2026-10-24); identifiers in English. No em dashes in docs. User-facing strings for the child stay in the language spoken (Chinese or English); recorded conversation data keeps the language actually used.
- Do not introduce microservices, message queues or extra database services.
- Any operation that needs sudo or changes system settings: stop and tell the user, who runs it from the admin account.
- Before changing model choices, the memory budget or hard constraints, confirm with the user first.

## Not in the first version

A standalone iPad app, HomePod as input (it can serve as an AirPlay speaker for stories), remote access (beyond Tailscale),
multiple family users, image understanding (drawings are only photographed and saved), voice satellite devices (evaluate Home Assistant Voice PE later).
