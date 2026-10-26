# Proposal deck: revision plan (PS06, 1.125 Agentic Engineering)

Due 2026-10-29 9:00 ET as `<github-username>/proposal.pdf` (PR to onexi/ps06), five-minute talk on the same deck.
Base: the existing Slides artifact "Curiosity Pet Proposal" (https://claude.ai/artifact/E2B8gNAny1zV9q3TE4yiEQ),
cover plus five slides in the course's suggested order. Keep its look (dark/light alternation, Syne + Manrope,
orange for her data, teal for public facts, blue for the agent) and its cover story. The changes below bring it in line
with the 10-25 direction and with what the system will actually do; it is a proposal, so "already done" content goes.

Global changes
- Rename to **Kit** (subtitle "a local-first agent for a seven-year-old"); keep the cat mark.
- Drop v0.1 / "done" content: the Done column on slide 4, "Now · Oct 29" on slide 5, the measured numbers and the
  "Built and measured" footer on slide 3. Keep exactly one feasibility line, on slide 4 under the title:
  "Builds on a working voice prototype on the Mac mini (speaks in about 3 s)." Reason: the proposal is judged on
  whether the scope is realistic, and the midpoint asks for evidence the core technologies are viable.
- Type sizes: the deck uses 88 / 56 / 52 / 34 / 30 / 28 / 26 / 24. The 10-25 rule is 96 / 60 / 28 / 24; either adopt it
  in one sweep or drop the rule. Do not mix.
- Speaker notes: rewrite wherever they say 4B, sqlite-vec, Tier 3 as core, or v0.1 numbers.

---

## Cover (keep)

- Keep the hook ("Every evening, my seven-year-old borrows my phone...") and the three question pills.
- "Curiosity Pet" -> "Kit"; subtitle -> "A local-first agent for a seven-year-old".

## 1. Problem and audience (change)

Current: "Three defaults that do not fit a child" cards plus the data-sensitivity x reasoning grid.

Change: replace the three cards with the **comparison matrix**; it answers the reviewer's first question ("isn't this
Gemini for kids?"). The grid is the design argument, not the problem; move it to the appendix or one line of notes.

Title: "Kids' AI is cloud chat with filters." (or keep "Three defaults..." as the subtitle)

| | Under 13 | Her words stay home | Parents see topics, not transcripts | Tools at home | Mic only on tap |
|---|---|---|---|---|---|
| Gemini (Family Link) | yes | no | no | no | yes (app) |
| ChatGPT for Teens | no (13+) | no | no (safety alerts only) | no | yes (app) |
| Curio Grok plush | yes | no (OpenAI, Azure) | no (full transcripts) | no | no (always listening) |
| **Kit** | yes | yes* | yes** | yes | yes |

\* Only checked topic words (Wikipedia) and a fixed "she wants you" message (Telegram) leave the machine.
\** Topics and counts by default; her own sentence is kept only for worrying moments, 30 days, parent-only.

Checked 2026-10-25:
- Baby Grok left out: announced 2025-07, no official xAI launch found; mention it in notes as "announced" only.
- Gemini: under-13 via Family Link (not in EEA, CH, UK); sources disagree on whether parents can see history, so the
  cell claims only "no topic view". Common Sense Media rated Gemini Under 13 "High Risk" (2025-09), usable in notes.
- ChatGPT: 13+ only, no supervised under-13 option; parental controls cannot read teen chats, only rare safety alerts
  (OpenAI help center).
- Curio: parents see real-time transcripts in the app; testers describe it as always listening; privacy policy names
  KWS, Azure Cognitive Services and OpenAI as data recipients (PIRG).

Keep the "Two users" line at the bottom.

## 2. Proposed solution (change)

Current: "One program cat. Five things it does for her." hub-and-spoke. Keep the layout, change the spokes:

| Spoke now | Change to |
|---|---|
| Bilingual voice: zh · en · mixed, cited | keep ("Asks anything": her language, source named or "my guess") |
| Age-appropriate: guard · blocklist · paths | merge into the hub text or bottom line (policy is slide 3) |
| Parent loop: topic alerts · weekly digest | keep |
| Private by design: only topic words leave | "Private by design: tap to talk, no wake word" (the leave rule is on slide 1) |
| Does things: saves · journals · stories | split into **Plans her day** (three things, gentle reminders, no streaks) and **Calls a parent** (button, the model can never block it) |

Hub: "Kit / iPad voice in, Mac mini, all local". Bottom line: "An agent with tools, every tool behind the parent's
policy. It says it is a program. It never tries to keep her talking."
Stretch spoke (dashed, optional): "Her room's light: parent scenes only".

## 3. Approach (change)

Current: "Three tiers, one router, gates both ways." Keep the vertical flow and the return gate; change the middle.

Title: "The model suggests. Rules and policy decide."

Flow:
1. Her question. Never leaves the device. (keep)
2. **Rules (veto)**: sensitive, personal, parent switches, blocklist -> fixed reply.
3. **Local planner (suggests)**: intent and a neutral topic term, only where rules are unsure.
4. **Policy (decides, only downgrades)**.
5. Tools row: Library | Wikipedia (topic words only) | Daily plan | Call a parent | Light (dashed) | Cloud model (dashed,
   parent switch off).
6. Return gate (keep): safety rules each sentence -> rewrite to her level -> word list + source.
7. Spoken to her, sentence by sentence. (keep)

Right column
- Stack chips: "Qwen3.5 9B (4B fallback) · Ollama", Qwen3-ASR, Kokoro TTS, Silero VAD, Qwen3Guard (optional),
  **SQLite full-text** (not sqlite-vec), FastAPI, Tailscale, Telegram bot.
- Label "open source · 8 GB budget" (a target, not "under 8 GB").
- Keep the two principle lines ("Knowledge from retrieval, not parameters." / "Safety in code, not prompts.");
  add "The router sees her words, so it runs at home."
- Remove the four numbers (2.3 s, 36/36, 0/38, 161 tests): done work, and partly stale.

## 4. Scope and risks (change)

Title: "Core by midpoint. Stretch after." Two columns instead of three.

| Core | Stretch |
|---|---|
| Policy layer for every tool call | Cloud model for neutral questions (parent switch, off) |
| Return gate | Her room's light (scene list only) |
| Learning flow agent | Reviewed library to 300 to 500 entries |
| Call a parent (button + voice) | Telegram parent bot (weekly report, misses) |
| Daily plan, light (reminders on the iPad page) | HomePod speaker |
| 100 reviewed entries, parent page, weekly digest | |

Risk cards (keep the four-card layout):
1. Small model gets facts wrong -> library first, guesses labelled. (keep)
2. Guard stops harmful, not unsuitable -> blocklist, fixed paths, adversarial set. (keep, drop "topic scope": not built)
3. Real child audio untested -> record her questions, keep tap-to-stop. (keep)
4. **16 GB machine: models plus speech exceed the 8 GB budget, latency near 3 s** -> measure with everything loaded
   first; guard optional; 4B fallback; rules before the model. (replaces "A 4B model cannot judge its limits", which
   belonged to Tier 3, now stretch)

Footer (keep): "No child data leaves except topic words and a call-me message. No engagement hooks. No evaluation of
the child."

## 5. Plan and success criteria (change)

Milestones: Proposal (Oct 29) -> Midpoint -> Final.
- Proposal: direction and policy rules written down; test sets defined.
- Midpoint: policy layer with every tool behind it; call a parent; daily plan light; return gate; learning flow;
  100 reviewed entries; memory and latency measured with everything loaded; her real audio measured.
- Final: parent page and digest; stretch by priority; self-healing deployment; adult trial with a fictional profile,
  then a supervised trial with her.

Five tiles:
| Now | Change to |
|---|---|
| < 3 s to first word, on her real recordings | keep |
| 100% adversarial set passes | keep |
| 0 privacy leaks, with Tier 3 switched on | "0 privacy leaks on the gate test set" |
| 0 judgements in the digest | "0 judgements in digest or plan (word list; no done/streak field)" |
| auto recovery | **"100% of tool calls checked by policy; a disabled tool cannot run"** |

Footer: "Demo: one day with Kit: a question, a plan, a reminder, a call. Individual project; code and evals on GitHub."

---

## Appendix (in the PDF, not presented)

1. The data-sensitivity x reasoning grid from the old slide 1.
2. Sources for the matrix (checked 2026-10-25):
   - Gemini under 13: https://techcrunch.com/2025/05/02/google-will-soon-start-letting-kids-under-13-use-its-gemini-chatbot
   - ChatGPT parental controls: https://help.openai.com/en/articles/12315553-managing-parental-controls-in-chatgpt
   - Curio Grok transcripts: https://www.tomsguide.com/ai/i-tested-this-adorable-ai-voice-toy-with-my-4-year-old-heres-what-happened-after-a-week-with-grok-by-curio
   - Curio data recipients: https://pirg.org/edfund/resources/ai-toys/
   - Curio always listening: https://futurism.com/ai-powered-childrens-toy-grok-interrupting
   - Baby Grok announcement: https://www.euronews.com/next/2025/07/21/elon-musk-to-build-child-friendly-ai-model-baby-grok-despite-past-controversies
3. Reused resources and licenses: Qwen3.5, Qwen3-ASR, Kokoro, Silero VAD, Qwen3Guard, Wikipedia (CC BY-SA), Project Gutenberg.
