# Kit

**A private AI agent for kids, run at home.**

Kit is a program kitten on my daughter's iPad. She asks questions by voice in Chinese or English; speech recognition,
the language model, the reviewed offline library, the safety rules and speech synthesis all run on a 16GB Mac mini at
home. The model suggests, rules in code decide. A separate one-tap button reaches a parent.

Internal names (`curiosity_pet`, `pet-server`, `com.curiositypet.*`) keep the project's earlier working title.

- **Architecture and design (technical companion to the October 29 proposal)**: [docs/PROPOSAL.md](docs/PROPOSAL.md)
- **Rules (hard constraints, component stack, stage acceptance)**: [CLAUDE.md](CLAUDE.md)
- **Decision log and reasons for revisions**: [docs/DECISIONS.md](docs/DECISIONS.md)
- **Measured data**: [evals/results/](evals/results/)
- **Changes**: [CHANGELOG.md](CHANGELOG.md)

## Status (midpoint, 2026-11-18)

Since October 24: a one-tap "Get Mom or Dad" button on the page (no model involved, rate limited, logged); fixed answers
for questions about death and for requests to keep a secret from a parent; English harm-to-others matched like Chinese;
a parent alert when she says she was bullied or hit (category only). After real use the live setup runs the 9B model
(settings.json `chat_model`; the code default is still the 4B). Measurements:
[evals/results/2026-11-17-midpoint.md](evals/results/2026-11-17-midpoint.md). Midpoint video script:
[docs/MIDPOINT_VIDEO.md](docs/MIDPOINT_VIDEO.md).

Still open: median time to first audio is 3.14 s with the 9B model (target under 3 s); the 100 reviewed library entries
(861 written, parent review not finished); accurate retelling of library pages; recognition accuracy on her own voice;
the action rules in one layer; privacy checked by watching network traffic, access and deletion.

| What it does | Measured |
|---|---|
| Tap on the iPad, talk to the kitten, answers play sentence by sentence with highlighted text | Median 3.1 s with the 9B model (2026-11-17); 2.3 s with the 4B model (2026-10-24), end of speech to first audio |
| Answers in the language the child asked in (Chinese, English, mixed) | 36/36 |
| When there is no local material, sends only a topic term stripped of personal information to Wikipedia, and cites the source | 0 leaks in the privacy test of 38 utterances |
| Local library: Simple English and Chinese Wikipedia opening paragraphs, Vikidia, Simple Wiktionary, Wikijunior, Chinese idioms, xiehouyu, a character dictionary, primary-school poems, classic readers, Gutenberg children's books; searched offline before going online (`uv run pet-library build`) | 53/53 ranking check, about 1 ms per search |
| British Shorthair blue cat look, four states; the small light on the collar marks it as a "program" | |
| Usage log: facts of each exploration and each question (duration, topic, follow-ups, whether a lookup was made); answer text deleted after 7 days | `uv run pet-log` |
| Private skin: replace the artwork, name and catchphrase from the data directory, never from the repo | [docs/SKIN.md](docs/SKIN.md) |
| Program-run conversation rules: rationed follow-up questions, arithmetic computed, riddles from a local bank with the answer withheld, "this is my guess" when no material backs a specific question | `evals/behavior_eval.py` |
| Characters (private skins) with a picker, each with its own tone, voice and cue sound | [docs/SKIN.md](docs/SKIN.md) |
| Safety in code: no praise or judgment of the child, no secrecy, no pretended abilities, fixed answers for harm, danger, death and secrecy | adversarial set 21 or 22 of 23 (2026-11-17, misses read one by one: the checks are too literal); 23/23 on 2026-10-24 |
| Calling a parent over Telegram after the child confirms; category-only alerts for talk about harm (both parent-approved) | `evals/call_parent_eval.py` |
| Memory the child chooses (interest cards, My Discoveries), stories and bedtime stories, natural wrap-up | |
| Weekly discovery report, facts only | `uv run pet-report` |
| Replay evaluation on real (local, never committed) conversations | 154/215 baseline route accuracy |
| 724 tests | `uv run pytest` |

Not done yet: daily planning and reminders, speech recognition accuracy on the child's recordings, installing the services under a dedicated user. See [CHANGELOG.md](CHANGELOG.md).

## Privacy

The child's voice, own words, conversation history, memory and mood never leave this machine. The repository contains no child data, recordings, databases or keys;
parent settings (contact info, family names, blocklist, Telegram bot settings) live in `settings.json` in the local data directory and are not committed. See section 11 of [docs/PROPOSAL.md](docs/PROPOSAL.md).

Who can reach Kit: the server listens on `127.0.0.1` only, so nothing on the home network or the internet can connect
to it. The iPad reaches it through `tailscale serve`, which gives HTTPS inside the family's own tailnet (private,
encrypted, only devices signed in to the family account). Tailscale Funnel (public access) is off. Knowing the address
is not enough to use Kit.

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
