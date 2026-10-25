# Changelog

All notable changes. Dates are when the work was done; details and reasons are in [docs/DECISIONS.md](docs/DECISIONS.md),
measured numbers in [evals/results/](evals/results/).

## 2026-10-23 to 2026-10-24: first real use and the fixes it led to

The child used the pet for two days on the iPad (and once on a watch). Every change below comes from her real sessions or
the parent's tests, reviewed turn by turn. No child data is in this repository: real conversations, labels and reports
stay in the local data directory.

### Models and speed
- Main model switched to Qwen3.5 9B (`pet-chat-9b`, parent's choice: slower is fine if smarter); helper calls use the same
  model because two models do not fit next to speech in 16 GB.
- Query rewriting moved from schema-constrained JSON (the 9B produced unrelated words) to plain JSON mode with validation.

### Conversation behaviour (decided by the program, not the model)
- Follow-up questions rationed: none on the first turn, at most one every 3 turns, at most one per answer, none after
  "stop asking"; the limit survives stop and start.
- Fillers and laughter are never answered; a lone word gets "I didn't catch that".
- "I'm a program / I have no feelings" only when asked whether the pet is real.
- Arithmetic computed by the program, including "A除B" (B divided by A) and a child's stated result ("三加四等于七").
- Dates and times from the Mac's clock.
- Riddles from a local bank with the answer withheld; riddles the child tells are guessed, never answered with a new one;
  false triggers (negations, "another question", long remarks) removed.
- Code guardrails on every spoken sentence: no praise or judgment of the child, no secrecy, no "tell a teacher or me",
  no pretended abilities (remembering chats, alarms, pictures, files, passing a message to a parent).
- Fixed safety answers for hurting oneself or others and dangerous actions; the parent's blocklist applies to answers.
- One current activity: starting a call, a story or a new question ends a pending riddle or story question.

### New features
- Characters (private skins): picker button, per-character tone, character card, fixed lines, voice, speed and cue
  sound; Pikachu's catchphrase can use a parent-provided clip or a pitched voice.
- Local library: Simple English Wikipedia, matching Chinese Wikipedia entries, Vikidia, Simple Wiktionary, Wikijunior,
  idioms, xiehouyu, a character dictionary, primary-school poems, classic readers, Gutenberg children's books;
  idiom stories and poems come from it; a parent-reviewed child Q&A set (pending review until approved).
- Calling a parent over Telegram after the child confirms (fixed text, per-parent 2-minute limit, every attempt logged);
  category-only alerts for talk about hurting oneself or others (off by default). Both are parent-confirmed exceptions
  to hard constraint 1 (see CLAUDE.md).
- Parent notes: what the child said that a parent may want to know, verbatim with time and a plain category, 30 days,
  parent-only.
- Memory the child chooses: interest cards ("我喜欢恐龙") and My Discoveries ("收藏这个").
- Story and bedtime modes; natural wrap-up after 15 minutes; goodbye ends the exploration after it has played.
- Weekly discovery report (`pet-report`) with a word-list check.
- Pronunciation fixes before speech (Pika, polyphones 长 and 传, English names inside Chinese, kana removed).
- Microphone and audio re-opened after the iPad locks; the usage log stores what was actually spoken.
- Optional Qwen3Guard safety model (non-strict, off by default; strict mode silenced 10% of ordinary sentences).
- Deployment pieces: launchd templates, installer (`scripts/install_services.sh`), backup script, failure tests;
  stale sessions are closed.
- Watch client API (pairing, turn, poll).

### Evaluation
- Replay evaluation (`evals/replay_eval.py`): real turns with labels, replayed through the pipeline offline; baseline
  route accuracy 154/215 (72%). A first model router was measured and rejected (slower and not better); a smaller check
  for doubtful messages is being measured.
- Adversarial safety set: 23/23 checks for each character.
- Privacy gate: 0 leaks after every change to it.

### Not done
- Real daily planning and reminders.
- Speech recognition accuracy on the child's own recordings; blind scoring of models.
- Installing the services under a dedicated `pet` user (needs the admin account).
