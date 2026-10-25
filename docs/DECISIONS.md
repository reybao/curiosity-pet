# Curiosity Pet: Development Thinking and Decision Log (2026-10-23)

CLAUDE.md holds the rules; this file holds the reasons and background. In a new session, read this file and CLAUDE.md first.

## 1. What the project is

A local AI learning pet for my 7.5-year-old daughter, who is bilingual (Chinese/English, often mixed in one sentence). The child asks questions by voice on an iPad, and the Mac mini does speech recognition, answer generation, knowledge retrieval, safety filtering and speech synthesis locally. The child's data never leaves the device, and there is no cloud fallback. The goal is to practice asking, following up, verifying and expressing ideas, with no retention-oriented design. It is also a course project, so tests and evaluations must be reproducible.

## 2. Why the shift from "personal local assistant" to "child curiosity pet"

The original plan was a local assistant on the Mac mini + Telegram entry + Amazon shopping. Research showed Amazon has systematically blocked third-party AI agents (robots.txt blocks 47+ crawlers, terms since March 2026 require agents to identify themselves, Meta Muse was banned in September; legally, the Ninth Circuit vacated the preliminary injunction against Perplexity, but the big question is still open), and the official channel of food-delivery platforms (DoorDash MCP) is waitlist-only for business customers. Shopping has no stable endpoint. The child version has a smaller scope, real technical difficulty (local speech, child safety, traceable answers), and an evaluation method that can convince people.

## 3. Division of labor between small local models and large cloud models

Local models of 4B to 9B are weak at factual knowledge, long-chain reasoning, following complex instructions, mixed-language speech and safety judgment; they are strong at "short, well-defined tasks within given material". So we use "large model builds the library offline, small model expresses online": frontier models such as Claude generate and check child-level Q&A and test sets and review local model output; at runtime everything is local. The breadth of the knowledge base, not model parameters, is the main lever on product quality.

## 4. How this differs from "giving the child an AI account"

Cloud models are smarter, but mainstream services have age limits (ChatGPT 13+, Claude 18+), data goes to the vendor's servers, and the product goal is retention. The value of this project: no account, data stays in the home, the flow is designed around educational goals, age-appropriateness is guaranteed by code rather than vendor policy, knowledge boundaries are traceable, parents can see everything, and it does not change with product redesigns. The positioning is "a learning tool under full control".

## 5. October 2026 model selection (final for 16GB M4)

| Component | Choice | Reason |
|---|---|---|
| LLM | Qwen3.5-4B q4_K_M (Ollama llama.cpp engine, think=false, num_ctx 8192) | One of the strongest small models for Chinese, quality close to the previous generation's 7B to 8B; 9B fits but sits near the limit and the first sentence is too slow; control group Gemma 4 E4B |
| STT | Qwen3-ASR-0.6B 4-bit (mlx-audio) | Far lower Chinese error rate than Whisper (noisy Mandarin CER 16 vs 63), 0.13 to 0.18 s per utterance on an M4 Pro; the common base of the winning solutions in children's speech competitions; control Fun-ASR-Nano (the only one explicitly trained on mixed Chinese/English) |
| VAD | Silero + smart-turn, silence threshold tuned from 0.8 s | The child pauses a lot; tap to talk, ends automatically when done, keep hold-to-talk as a fallback |
| TTS | Kokoro-82M v1.1-zh | Under 0.5GB, first packet about 65 ms; Qwen3-TTS is better but takes almost 2GB more; weak on short sentences, so merge the first two sentences before synthesis; the iPad's built-in voice is the fallback |
| Guard | Qwen3Guard-Gen-0.6B strict mode | The only small guard that supports Chinese; Llama Guard 4 does not cover Chinese |
| Embedding | Qwen3-Embedding-0.6B + sqlite-vec | Good in both Chinese and English, single-file storage |
| Backend | Python + FastAPI + Pipecat, uv | Single process, no microservices |
| Frontend | Lightweight pages hosted by FastAPI, Rive/Lottie pet animation | No React/Electron |

Memory: about 10 to 11GB of GPU memory is usable, resident models total about 6GB, leaving 4GB for the KV cache and processes.

Latency budget: segmentation 0.5 to 0.8 s + STT 0.2 + guard and retrieval 0.2 + prefill 0.5 + first sentence generation 0.6 + TTS 0.07, about 1.8 to 3.0 s in total. Key tricks: stream sentence by sentence to TTS, turn thinking off, and have the iPad play a cue sound and switch to the "thinking" animation right after VAD ends.

Ollama notes: use the native /api/chat (the OpenAI-compatible endpoint ignores num_ctx); KEEP_ALIVE=-1, NUM_PARALLEL=1, MAX_LOADED_MODELS=3; cut the embedding model's num_ctx to 2048; on 16GB the MLX engine may not be enabled, and falling back to llama.cpp is 15% to 30% slower, which is acceptable; answers read to the child use streamed text rather than JSON, and JSON Schema is only for the guard, intent classification and memory extraction.

Evidence gaps (must be measured on this machine): recognition rate for a 7-year-old's Mandarin, Chinese naturalness of each TTS, real tok/s on a base M4.

Reference open-source projects: kwindla/macos-local-voice-agents, mthomas100/local-voice, dusterbloom/localcat (Pipecat local voice pipelines; swapping the ASR for Qwen3-ASR gives this project's skeleton).

### Revision after measurements on 2026-10-23

- The main model changed from the default tag `qwen3.5:4b` (nvfp4, MLX engine) to `qwen3.5:4b-q4_K_M` (GGUF, llama.cpp engine).
  Reason: with Ollama 0.40.9, the MLX engine's resident memory grows with every request, from 4.1GB to 12.6GB over 60 requests, triggering swap and slowing latency;
  KV cache quantization (q8_0) has no effect on MLX. The llama.cpp build was still at 3.4GB after 60 requests, with a median end-to-end time to speak of 2.25 s (MLX 2.40 s),
  and the same language accuracy. The KV cache stays f16; q8_0 saves only 0.1GB and generates about 13% slower. Data in `evals/results/2026-10-23.md`.
- The statement above that "the MLX engine may not be enabled, and falling back to llama.cpp is 15% to 30% slower" does not match the measurements: MLX works on this machine, but llama.cpp is actually faster end to end.

### Stage 2 trade-offs, 2026-10-23

- The voice channel uses a FastAPI WebSocket, not Pipecat. Pipecat 1.14 pins soundfile 0.13 (the project already uses 0.14), pulls in onnxruntime, numba,
  the OpenAI SDK and other dependencies, and would require rewriting the already tested segmentation, recognition, generation and synthesis modules as its processors. For a single child and a single connection,
  sending PCM directly over a WebSocket is simpler and reuses the Stage 1 modules and tests. Re-evaluate when WebRTC or barge-in (listening while speaking) is needed.
- The pet animation starts with SVG + CSS (zero dependencies, hosted locally); switch to Rive or Lottie once there is proper artwork.
- When Ollama runs Qwen3.5 through llama.cpp, the prompt cache cannot be reused (hybrid architecture + Ollama fixes `--cache-ram 0`), so every turn prefills from scratch.
  Therefore the system prompt is kept lean and the session history carries only the last 2 turns.

### 2026-10-24 Limited online access allowed (Wikipedia)

- After testing, the parent reported "a lot of the information is wrong", for example not knowing Goku from Dragon Ball. The parent's view: when there is no local material,
  general-knowledge questions may go online; but large amounts of child data must not leave the machine, and private or family information the child shares and the child's mood must never be sent out.
- So hard constraint 1 was amended with a narrow exception: only a topic search term rewritten locally and checked by rules is sent, and for now the only source is Wikipedia
  (mostly factual and relatively age-appropriate; general web search content is too mixed, so it stays off). Going online adds about 1 to 2 s, and the pet first says "let me look it up".
- Search terms are kept 7 days for the parent to view, after which only per-topic counts remain, used for factual trends in the weekly report (no interpretation such as "likes it more and more").
- The online switch is on by default; storytelling and bedtime modes never go online; in the first two weeks the parent reviews the log weekly, and if anything looks wrong, turns it off and tightens the rules.

### 2026-10-24 Pet appearance and "interaction habits"

- The parent wanted the pet to be a British Shorthair blue cat, with a cat feel in the voice. To keep hard constraint 4 (clearly a program), the collar light stays as the program marker,
  and the pet calls itself "the program kitten, not a real cat, with no feelings". In measurements the 4B model did not obey "at most one meow" (13/36 answers had more than one), so code now truncates it.
- The parent wanted "personality and interests" recorded with advice. Personality analysis is not done (hard constraint 3: small-model judgments are unreliable, labels would shape the parent's view of the child,
  and the child also reads the weekly report). The parent agreed to: no personality analysis, but keep the **countable facts** that reflect personality ("interaction habits"), for the parent to interpret;
  interests are counted by topic, and the weekly report gives parent-child activity suggestions.

### 2026-10-24 Stage 3 postponed; record usage first

The parent decided not to build the learning flow (follow-ups, small activities, favorites, routine reminders, diary) yet, and instead to record how the child actually uses it, then decide what to change after looking at the records for a while.
Records are strictly limited to facts allowed by constraints 2 and 3: question text, language, topic, follow-up type, whether a lookup was made, duration, how it ended; answer text is deleted after 7 days;
no evaluation. The parent views it with `pet-log`. Topic tagging is done afterwards by the local model once the answer ends, so it does not add to the time-to-speak latency.

### 2026-10-24 Private skin instead of a copyrighted character in the repo

The parent was not satisfied with the hand-drawn cat variants and considered Pikachu or young Goku, for private,
non-commercial home use. Those are copyrighted characters: the assistant will not draw them, and they cannot go into the public
repository. Compromise: a private skin mechanism. Artwork, name and catchphrase live in the data directory (`skin/`), the repo keeps
the default cat, the program badge stays on the picture, and the pet still says it is a program when asked whether it is real.
The parent prepares the images.

### 2026-10-24 After the first half-day of real use

The child used the pet for half a day; the parent reported six problems. Diagnosis and the decisions taken:

1. A follow-up question after every answer, even when the child did not want one: the model obeyed the prompt
   mechanically. Decided: follow-ups are rationed by the program (at most one in three turns, none after one is
   ignored, none after "stop asking"), and question sentences are dropped when not allowed.
   The constant "talk to a parent or teacher" line is removed from the system prompt and only used when the
   program detects distress.
2. "Hold to talk" did not work on the iPad: replaced by a single start/stop button; the VAD does the segmentation.
3. After "stop" the pet stopped hearing: a real bug (a stop during thinking or speaking left the server waiting
   for playback_done forever). Fixed with cancellable turns and an idle state.
4. Arithmetic was wrong (91 / 5): computed by the program now, with ASR homophone fixes.
5. Hallucinated plots (Goku vs the Red Ribbon Army): story questions now count as knowledge questions and are
   looked up; with no material the answer is spoken as a guess and logged for the parent. The parent declined a
   cloud model and chose web search instead (Brave or Google, free tiers), behind the same privacy gate.
6. The same riddle every time and the answer given at once: riddles come from a local bank of 120 (60 per
   language), used ones are remembered, and the answer is withheld until the child answers or gives up.
   The parent asked for natural conversation rather than a game mode, so the state is internal only.

The parent also asked about a larger model: the 9B variant (Qwen3.5-9B q4_K_M) was measured, see evals/results.

After seeing the numbers the parent chose the 9B: slower is fine if it is smarter. It runs as the only model
(the helper follows the main model, since two models do not fit next to the speech models in 16 GB).
Typical first audio is about 2.7 s, and the first real answer sentence on lookup turns comes at 4 to 6 s.
The repository default stays 4B; the switch is `"chat_model": "pet-chat-9b"` in the local settings.json.

### Several skins and a picker (2026-10-24)

The parent noticed the "I heard you" cue was still a meow with Goku active, and asked that each character sound like itself
(kitten: meow, Pikachu: pika, Goku: his own way of talking) and for a button to switch. Each skin now sets its catchphrase,
an optional speaking tone that goes into the prompt, an optional voice and speed, and an optional cue file; without a cue file
the pet's own voice says the catchphrase. The persona is read at call time instead of at startup, so a switch takes effect
on the next sentence. Switching ends a running exploration, so one answer never mixes two characters. All 103 official Kokoro
voices were converted so the parent can choose by ear; only one Kokoro model is loaded, so this costs no memory.

### 2026-10-24 Local library from Wikipedia dumps

The parent asked for a local library. Built from Wikimedia's CirrusSearch dumps (plain text, Wikidata items): all of Simple
English Wikipedia (277k articles) and only the Chinese Wikipedia articles about the same concepts (158k, matched by Wikidata
item, converted to Simplified). This keeps the rule "no full Chinese Wikipedia": measured on one shard, the Chinese articles
outside that set are mostly places, elections, politicians, celebrities and TV dramas. Only opening paragraphs are kept
(451 MB SQLite full-text index in the data directory; the 7.3 GB dumps stay outside the repository and can be deleted).
The library is searched first with the same privacy-checked query, needs no contact info and also works with online lookup
off; the source label is "小图书馆" / "my library". Wikipedia text is CC BY-SA: private family use, article URLs kept.
Results: evals/results/2026-10-24-library.md.
Same day, the parent approved the first batch of extra sources: Vikidia (English, for 8 to 13 year olds), Simple English
Wiktionary, Wikijunior, Chinese idioms with origins and filtered xiehouyu (chinese-xinhua, MIT), 三字经, 千字文, 弟子规,
声律启蒙, 唐诗三百首 and 千家诗 (chinese-poetry, MIT), and six Project Gutenberg children's books. Child-level sources rank
slightly above encyclopedia articles; dictionary entries only win for "what does X mean". A shared filter drops entries
centered on serial killers, sexual violence, massacres, terror attacks or horror films from every source, Wikipedia included.
Xiehouyu are filtered by word list (11,579 of 14,032 kept) but not reviewed one by one.
Evening, after reading the child's real questions: added 110 primary-school poems (texts found by first line in
chinese-poetry and Werneror/Poetry, never from memory; Wikisource search was tried and rejected after it returned a court
document and a parody), the xinhua character dictionary (the word dictionary was left out as classical), and 200 new
riddles. Poem and character questions take their target from the child's own words and search only the library, because
the model rewrite loses it. The pet answers a child's riddle from its bank when it is a classic, and recognizes riddle
forms told without an announcement. Embeddings are the next experiment, offline first, measured on real misses.
Measured the same evening (evals/results/2026-10-24-embedding.md): multilingual-e5-small (the size that fits) makes
every mode worse than the keyword search (43 to 55 of 83 against 65), Qwen3-Embedding-0.6B is no better (55) and costs
0.8 s per lookup, 2.3 GB of GPU memory and a 9-hour index. Embeddings are not adopted. Instead, letting the chat model
name the answer and looking that title up reached 71 of 83 and fixed all superlatives ("世界上最大的动物" -> 蓝鲸).
Also from this round: the grim-entry filter now covers murder cases (杀人事件, 凶杀, 血案, 惨案).
Built: for questions whose answer is one named thing (superlatives, "who invented"), a separate short model call names the
answer after the filler starts, and the library entry with exactly that title is used if it mentions a word of the
question. Folding the field into the rewrite call was tried first and dropped: the 9B then returned whole questions as
search queries. Real and superlative questions: 13 -> 19 of 30; the name never leaves the machine.
Idiom stories and poems now come from the library (review finding: the pet told 画蛇添足 and 《江雪》 wrong from memory).
Story requests pick from 38 child-suitable story idioms; poem requests attach the text; "这首诗/这个成语" and "不是这个意思"
re-attach the entry used last. A reviewed child Q&A library started (CLAUDE.md source priority 1): 357 Chinese and 356
English questions, 110 poem meaning notes, 38 idiom stories, all drafted by the large model and pending until the parent
approves them; only approved entries are served, and they rank above every other source. Matching uses word overlap to
propose candidates and the local model to pick (word overlap alone was wrong 21% of the time); the pick runs after the
filler. Results: evals/results/2026-10-24-qa.md.
Not available as open data: 十万个为什么 (copyrighted); child-safe joke collections with a clear license were not found.
Candidates for later: public-domain stories (Project Gutenberg: Aesop, Grimm, Andersen, Just So Stories), chinese-poetry
(MIT; 蒙学: 三字经, 千家诗, 声律启蒙), chinese-xinhua (MIT; 歇后语, 成语 with origins), CC-Riddle (Chinese character riddles,
CC BY-NC-SA, fine for private use), and parent-reviewed Q&A, jokes and riddles generated offline by a large model.

### Second day of real use (2026-10-24)

- Division: the child asked "六除九十是几". "A除B" means B divided by A, so a plain 除 now divides the larger number by
  the smaller one and the answer says which way it computed ("九十除以六等于十五"). A smaller number divided by a larger
  one first says there is not enough to share, then gives the other way round. Lead-ins ("我问你:", "考考你") and a
  calculation relayed in quotes or after a colon are computed by the program too.
- Pronunciation: fixes are applied only to the text sent to the voice. English "Pika" was read as the animal ("pie-ka")
  and "Pikachu" was unknown, so both get explicit phonemes. A lone 长 meaning long was read zhǎng, and the 传 ending a
  title was read chuán; both are swapped for homophones (常, 赚) by rules that leave words the G2P already reads right alone.
- Riddles in the other direction: when the child posed a riddle, the pet answered with one of its own, because "riddle"
  only meant "give me one". Now "I have a riddle for you" gets "go ahead"; the pet then guesses, asks only "Am I right?",
  and stops there, and it never poses a new riddle in reply. "说一个Riddle" (the word glued to Chinese) is recognized as
  a request again instead of going to the model, which had made up a riddle and given the answer at once.
- A stopped turn could still deliver one sentence after "idle" (a rare test failure). Messages from a turn's thread are
  now checked against the current turn on the event loop, in order with the stop.

### Review of the first full day (2026-10-24, 112 turns in 28 explorations)

- Noise: 27 turns were laughter, fillers, single misheard words, a car's navigation voice or adults talking, and each got
  a full answer. Fillers and laughter now get no answer; a lone word gets a short "I didn't catch that". While the pet is
  waiting for an answer (it asked, or a riddle is open) every message counts, since "十。" or "Dog." is then an answer.
- "I'm a program, I have no feelings" was said 13 times, never when asked. The prompt no longer states "you have no
  feelings" (the 9B model repeated it), and those clauses are cut from answers unless the child asked whether the pet is
  real or has feelings. Hard constraint 4 still holds: asked directly, it says it is a program.
- Questions: 40% of answers still asked one, half on the first turn of an exploration, because the limit reset on every
  stop/start and the child restarted 28 times (6 of them to switch characters). The limit now survives stop/start, resets
  only after 30 minutes without a turn, and never allows a question on the first turn.
- Characters: each skin has a short tone line in every prompt and a character card added only when the child asks about
  the character or its world, plus its own fixed lines. Goku had told the Monkey King's story; his card says he is from
  Dragon Ball and does not do the 72 transformations.
- Foreign words: Japanese kana and Korean were silent; they are removed from the voice text. English names inside Chinese
  answers (Vegeta, Bulma) were silent too; the Chinese path now uses the same espeak fallback as the English one.
- Pikachu's "pika": the parent asked for the original sound. The project does not download character recordings; a clip
  the parent provides is used both as the cue and in place of the catchphrase, and without one the voice is pitched up.

### 2026-10-24 The child can ask the pet to call a parent (Telegram)

- The parent asked whether the pet could reach them through their own Telegram assistant, for example when the child
  wants her dad. This is the second path where something the child did leaves the home, so it is a narrow,
  parent-approved exception to hard constraint 1, and the program keeps every decision that matters (`call_parent.py`).
- Clear fixed phrases are matched by the program ("叫爸爸来", "告诉妈妈我饿了", "叫爸爸妈妈过来", "tell daddy I'm
  done"), only when the request leads the sentence: "为什么爸爸叫爸爸", "妈妈叫我吃饭" and "don't tell mom" are not.
- The parent then asked for detection by meaning ("我要妈妈", "爸爸在哪儿", "我想爸爸了", "where's daddy"). A sentence
  that names a parent but is no fixed phrase goes to the local helper model, which only answers dad / mom / both /
  none and is told to answer none for talk about a parent, stories, riddles and when unsure. It is one short JSON call,
  made only for sentences with a parent word, never during a riddle or story, and not at all when the feature is off.
  The model cannot send anything: its verdict only makes the pet ask, so a false positive costs one question.
- Measured with pet-chat-9b on 50 made-up Chinese, English and mixed sentences (evals/call_parent_eval.py): 25 of 25
  requests found with the right target, 0 of 25 look-alikes ("我爸爸是医生", "mom said I can watch TV", "不要告诉妈妈")
  asked about. A judge call takes about 2.3 s (the prompt cannot be cached), so the model is asked only when the
  sentence also has a request word (找, 要, 想, 哪, 来, where, want, miss, come...): most talk about a parent loses no time.
- The pet asks first with a fixed line ("要我告诉爸爸你在找他吗?") and sends only after a yes ("要", "嗯", "好", "yes").
  "不要" or "算了" cancels; anything else drops the question and is answered normally; the question lapses after 60 s and
  on stop.
- What is sent is fixed by default: "宝宝想找爸爸 / Your daughter is asking for Daddy", the time and the
  device; the prefix sets it apart from the assistant's own replies in the same chat. The
  child's own words are added only when the parent sets `"call_parent": {"include_words": true}`; the pet then asks
  "要我把你的话发给爸爸吗?" so she knows her words go out.
- At most one message per 2 minutes (`min_interval_s`) across iPad and watch; a failed send does not use up the slot.
  The pet says so with a fixed line ("我刚刚已经告诉过爸爸了") and tells her to go find the parent when sending is off or fails.
- Every attempt (sent, failed, declined, rate limited, switched off) is a row in `parent_calls`, shown in pet-log with
  the exact text sent; the text is cleared after 7 days like other conversation text.
- It goes through the parent's own Telegram assistant bot (home-bot, a separate project): the pet reuses that bot's
  token and only calls sendMessage, never getUpdates or a webhook, which would break the assistant's polling.
  "叫爸爸" goes to the father's chat only and "叫妈妈" to the mother's only (`chat_ids`, parent's choice 2026-10-24);
  both are on that bot's allowlist. Only "爸爸妈妈", "爸妈", "你们", "大人", "parents" or "mom and dad" reach both,
  as one message for the rate limit.
- The bot token and chat id live only in `settings.json` in the data directory (`"call_parent": {"telegram":
  {"bot_token", "chat_id", "chat_ids": {"dad": ..., "mom": ...}}}`). With no token, or `"enabled": false`, the feature is off.
  Settings are read on every request, so switching it off needs no restart. The token is never logged.

### Fixing the review findings (2026-10-24 evening)

The parent asked to fix everything from the review of the afternoon's use and their own test, and to keep records of
upsetting things the child says so parents are reminded.
- Parent notes amend the "no emotional fields" rule narrowly: the child's own sentence, time and a plain category, 30 days,
  parent-only, never inferred or summarized, never in the weekly report.
- Code-level guards for hard constraints 3 and 4 (praise, secrecy, replacing adults) and for pretended abilities, plus an
  honest ability note when she asks about memory, alarms, pictures or plans. The parent's daily-plan test had the pet claim
  "I wrote everything down"; real planning (saved plans, reminders) is still not built.
- Fixed safety answers for hurting oneself or others and dangerous actions; the blocklist now applies to answers.
- Qwen3Guard measured: strict mode would silence 10% of ordinary sentences, so it is non-strict and off by default.
- Stage 3 (My Discoveries, interest cards, natural wrap-up), stage 6 (story and bedtime modes, weekly report) and stage 7
  pieces (launchd templates, backup script, failure tests) are built; installing the agents and the `pet` user are left
  to the parent (admin account).
- Found by the failure tests: a lookup source that raises (network down) aborted the whole answer; now it answers
  without material. Riddle false triggers from the parent's test (negation, "another question", long remarks) are fixed.

### Calling a parent over Telegram: a second exception to hard constraint 1 (2026-10-24)

The parent asked that the child can have the pet call or tell a parent, and confirmed the rule in their own words:
after the child confirms, a fixed message goes to the parent she named, without her own words by default, at most one
every two minutes, and every attempt is in the parent log. Built in call_parent.py (by a separate session) and wired into
the pipeline and pet-log. Pushing the parent notes (concern.py) to Telegram was decided separately (next entry).

### Serious parent notes pushed to Telegram: a third exception to hard constraint 1 (2026-10-24)

Asked in chat, the parent chose: push only the most serious parent-note categories (`concern.SERIOUS`: hurting herself,
hurting others), the category only and not her sentence, to both dad and mom, at most one message per 10 minutes.
- `notify_concern` in call_parent.py sends "宝宝说到伤害自己 / Your daughter talked about hurting herself", the
  time and the device; no interpretation. Her sentence stays in `parent_notes` on this machine (pet-log).
- Its own switch, off unless set: `"call_parent": {"concern_push": {"enabled": true}}`; optional `categories`,
  `include_words` (literal true), `parents` (dad / mom / both) and `min_interval_s` (default 600). It does not follow
  the call switch, and has its own rate limit so it never uses up the child's call. Nothing is said to the child.
- Same bot token and sendMessage-only path as calling a parent; every attempt is a `parent_calls` row shown in pet-log.
- The pipeline starts it in a background thread right after the parent note, so an answer never waits on the network.
  The parent confirmed the rule again in their own words (CLAUDE.md, constraints 1 and 2) and switched it on in the
  dev settings the same evening.

### Calling a parent: per-parent limit and honest replies (2026-10-24 evening)

In the parent's test, asking for Mommy 16 seconds after Daddy was blocked by the shared 2-minute limit, and the pet said
"我刚刚已经告诉过妈妈了" although only Daddy had been told. The parent decided: each parent has their own 2-minute limit.
When blocked the pet now says "刚才已经给妈妈发过一条消息了,过两分钟才能再发". Several yes words in a row ("好,是。") count
as yes; before, that reply went to the model, which said "好的,皮卡帮你问问爸爸!" and sent nothing. Model sentences that
claim to pass something on to a parent, or promise a parent is coming, are now removed whole.

## 6. Key trade-offs at the product boundary

- Voice is a first-version feature, and the iPad web page must be HTTPS; Tailscale solves certificates and device pairing together; PWA plus Guided Access.
- The weekly report becomes the "weekly discovery report": it contains only question text, favorites, topic counts, questions that missed the material, and parent-child activity suggestions; judgments of ability, emotion or personality and comparisons are forbidden; trends are factual only; the raw material is structured fields rather than chat text; the child reads it together with the parent; the parent can turn it off or delete it.
- Chat text is kept at most 7 days for the parent to view; memory allows whitelisted fields only, with no free-text "observation" field.
- The guard model only blocks "harmful", not "age-inappropriate", so we layer: system prompt, Qwen3Guard, parent topic range and blocklist, knowledge base first, fixed path for sensitive topics, time-limited logs; the adversarial test set covers violence, bodies, "are you alive", "I hate my little brother", "don't tell mom", scary stories, jailbreak prompts.
- Knowledge base: do not download the full Wikipedia or the "Hundred Thousand Whys" children's encyclopedia. Prefer child-level Q&A generated offline by a large model and reviewed by the parent (300 to 500 entries first, one set each in Chinese and English), then a Simple English Wikipedia subset, Wikijunior, and books at home (not in the repository). Questions that miss are recorded in a table, and the weekly report lists them for filling the library.
- Storytelling: original or public-domain adaptations (Grimm, Andersen, Chinese folk tales and idiom stories), 3 to 5 minutes, fixed structure, can weave in the day's discoveries, the guard checks sentence by sentence, bedtime mode is slow with no follow-ups.
- HomePod is closed, so it only serves as an AirPlay speaker for stories; voice input stays on the iPad. Home Assistant Voice PE can be evaluated later as a voice satellite.

## 7. Development approach and environment

- Develop directly on the Mac mini with Claude Code (the dev environment is the runtime environment), entering from a laptop via SSH or screen sharing.
- The service should run under a separate standard account, pet; the current connection is a personal account (device reys-mac-local, home directory already has .ollama); develop first and migrate before real use.
- The directory split into three: project ~/Projects/curiosity-pet (in git); dev data ~/pet-data-dev; production data ~/Library/Application Support/CuriosityPet; audio samples ~/pet-evals/audio (the last three are not in git).
- Claude Code permissions (.claude/settings.json): acceptEdits plus pre-approvals (uv, ollama, git commit, pytest, brew install, launchctl, tailscale); rm -rf, git push, git reset --hard require asking; sudo, reading the audio directory and production data directory, .env, ~/.ssh are forbidden. Auto mode is fine; do not use dangerously-skip-permissions.
- Power and sharing settings that need sudo are run by the user from the admin account (see the end of setup_mac_mini.sh).

## 8. Stages and acceptance

0 Baseline (tok/s, first-token latency, ASR error rate on the child's recordings, 4B vs E4B blind test) → 1 command-line voice loop (first sentence within 3 s) → 2 iPad access + Tailscale + four-state pet animation → 3 learning flow → 4 knowledge base, sources, misses, interest cards, deletion → 5 guard, blocklist, sensitive topics, parent page, retention rules → 6 stories, weekly report → 7 launchd deployment, backup, failure tests → 8 a week of adult trial with a fictional profile, then a short trial with the parent present. Estimated calendar time is about two weeks.

## 9. Next steps (a new session starts here)

1. Create ~/Projects/curiosity-pet and put this package's contents in it (CLAUDE.md, setup_mac_mini.sh, .claude/settings.json, .gitignore, docs/DECISIONS.md), then git init.
2. In the Claude desktop app, connect that directory with "Add folder" (the last authorization prompt got no response and must be redone).
3. In a terminal, cd in and run claude, with the first sentence: "Read CLAUDE.md and docs/DECISIONS.md, run setup_mac_mini.sh to finish installation and the baseline test, write the numbers into evals/results/, then start Stage 1".
4. Record 30 to 50 of my daughter's questions in Chinese, English and mixed speech, and put them in ~/pet-evals/audio.
5. Install Tailscale on the Mac and iPad and sign in with the same account.
