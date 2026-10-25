# Curiosity Pet (Curiosity Buddy)

A local, privacy-first voice learning companion for a bilingual 7-year-old, running entirely on a 16GB Mac mini.
A local AI learning pet that lives on a home Mac mini: the child asks questions by voice on an iPad, and speech recognition, answer generation, knowledge retrieval, safety filtering and speech synthesis all happen on the machine itself.

- **Proposal, architecture and flow diagrams**: [docs/PROPOSAL.md](docs/PROPOSAL.md)
- **Rules (hard constraints, component stack, stage acceptance)**: [CLAUDE.md](CLAUDE.md)
- **Decision log and reasons for revisions**: [docs/DECISIONS.md](docs/DECISIONS.md)
- **Measured data**: [evals/results/](evals/results/)
- **Changes**: [CHANGELOG.md](CHANGELOG.md)

## Status (2026-10-24)

| What it does | Measured |
|---|---|
| Tap on the iPad, talk to the kitten, answers play sentence by sentence with highlighted text | Median 2.3 s (local) / 2.8 s (via web) from end of speech to the pet speaking |
| Answers in the language the child asked in (Chinese, English, mixed) | 36/36 |
| When there is no local material, sends only a topic term stripped of personal information to Wikipedia, and cites the source | 0 leaks in the privacy test of 38 utterances |
| Local library: Simple English and Chinese Wikipedia opening paragraphs, Vikidia, Simple Wiktionary, Wikijunior, Chinese idioms, xiehouyu, a character dictionary, primary-school poems, classic readers, Gutenberg children's books; searched offline before going online (`uv run pet-library build`) | 53/53 ranking check, about 1 ms per search |
| British Shorthair blue cat look, four states; the small light on the collar marks it as a "program" | |
| Usage log: facts of each exploration and each question (duration, topic, follow-ups, whether a lookup was made); answer text deleted after 7 days | `uv run pet-log` |
| Private skin: replace the artwork, name and catchphrase from the data directory, never from the repo | [docs/SKIN.md](docs/SKIN.md) |
| Program-run conversation rules: rationed follow-up questions, arithmetic computed, riddles from a local bank with the answer withheld, "this is my guess" when no material backs a specific question | `evals/behavior_eval.py` |
| Characters (private skins) with a picker, each with its own tone, voice and cue sound | [docs/SKIN.md](docs/SKIN.md) |
| Safety in code: no praise or judgment of the child, no secrecy, no pretended abilities, fixed answers for harm and danger | adversarial set 23/23 per character |
| Calling a parent over Telegram after the child confirms; category-only alerts for talk about harm (both parent-approved) | `evals/call_parent_eval.py` |
| Memory the child chooses (interest cards, My Discoveries), stories and bedtime stories, natural wrap-up | |
| Weekly discovery report, facts only | `uv run pet-report` |
| Replay evaluation on real (local, never committed) conversations | 154/215 baseline route accuracy |
| 637 tests | `uv run pytest` |

Not done yet: daily planning and reminders, speech recognition accuracy on the child's recordings, installing the services under a dedicated user. See [CHANGELOG.md](CHANGELOG.md).

## Privacy

The child's voice, own words, conversation history, memory and mood never leave this machine. The repository contains no child data, recordings, databases or keys;
parent settings (contact info, family names, blocklist, Telegram bot settings) live in `settings.json` in the local data directory and are not committed. See section 11 of [docs/PROPOSAL.md](docs/PROPOSAL.md).

## Run

```bash
bash setup_mac_mini.sh                  # dependencies, models, baseline (Tailscale must be installed manually)
uv sync
uv run python scripts/convert_kokoro.py  # convert Kokoro v1.1-zh weights locally
uv run pytest
uv run pet --text                        # chat by typing in the terminal; uv run pet uses the microphone
uv run pet-server                        # iPad web service, then serve HTTPS with tailscale serve --bg 8730
uv run pet-log --days 7                  # parent view of the usage log (facts only, no judgments)
```

Hardware: Mac mini M4, 16GB. Software: macOS, Ollama, Python 3.12, uv, mlx-audio.
