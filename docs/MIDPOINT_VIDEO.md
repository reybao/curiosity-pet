# Kit midpoint check-in video (November 19, 2026)

The video as made in Google Vids: 4:48, 23 scenes. Slide scenes carry a 10-second talking clip of the author; the six
demo scenes are screen recordings from the iPad with their own sound. No child's voice, face or name appears.

## Scenes

| # | Scene | Visual | Spoken line or sound |
|---|---|---|---|
| 1 | Title | "Kit, Midpoint check-in" | This is Kit, a private AI agent for my seven-year-old daughter, running on a Mac mini at home. |
| 2 | What I promised | Proposal slide 4, "One complete flow" | In October I promised one complete flow: a spoken question, a sourced answer, and a separate way to reach a parent. |
| 3 | How Kit is built | Architecture: proposal diagram, models, library | Her iPad is only the screen. Everything runs on a Mac mini at home, and rules in code decide, not the model. |
| 4 | How Kit is built | same | Four local models: Qwen3.5 9B for language, Qwen ASR for listening, Kokoro for speaking, Silero for voice detection. |
| 5 | How Kit is built | same | The library is downloaded: half a million entries from Simple English and Chinese Wikipedia, Wikijunior, dictionaries, idioms, poems, and children's books. |
| 6 | How her iPad reaches Kit | iPad, tailnet, Mac mini; who cannot reach it; what leaves the house | How does her iPad reach Kit? Through Tailscale, a private, encrypted network with only our family's devices on it. |
| 7 | How her iPad reaches Kit | same | The server listens only on the Mac mini itself, and public access is off. Knowing the address is not enough to use Kit. |
| 8 | How her iPad reaches Kit | same | Only two things leave the house: a cleaned topic word to Wikipedia, and fixed messages to a parent's phone. |
| 9 | Before the demos | List of the six demos | Now the demo, recorded on her iPad on November seventeenth. I ask the questions myself, so her voice is not in this video. |
| 10 | Demo | "Who are you?" | Kit says it is a program kitten. |
| 11 | Demo | "What do pandas eat?" | Answer from the local library, with its source. |
| 12 | Demo | "为什么月亮白天也会出现?" | Chinese answer from the library page; the retelling is not accurate (shown as found). |
| 13 | Demo | "What is twelve plus twenty-nine?" | The program computes 41, not the model. |
| 14 | Demo | Matches; a secret from Mom | Fixed danger reply; fixed refusal to keep a secret from a parent. |
| 15 | Demo | Help button | One tap sends the fixed message; a second request by voice is rate limited. |
| 16 | The parent's side | The help message as it arrived on my phone (that one bubble only) and what it contains | This is what arrives on my phone: a fixed line with the time, the device and the help button. No conversation is sent. |
| 17 | What is done | Scoreboard, top half | Against the plan: the question-to-answer flow is complete. Danger, harm, death and secrets get fixed answers written in code. |
| 18 | What is done | same | The privacy gate leaked zero of thirty-eight test sentences. Parent alerts and the weekly topic summary work. Seven hundred twenty-four tests pass. |
| 19 | What real use taught me | Three findings | One thing came early: she has already used Kit for two days. A quarter of what the microphone heard was noise. |
| 20 | What real use taught me | same | After fixes, correctly handled turns rose from seventy-two to eighty percent. I also moved to a larger model and accepted slower answers. |
| 21 | What is left | Scoreboard, bottom half | What is left. First, answer quality: Kit found the right page about the moon, but retold it wrong. |
| 22 | What is left | same | The median time to first word is three point one seconds, above my three-second target. My library review is not finished. |
| 23 | What is left | same | I still have to measure recognition on her own voice, and verify privacy with network traffic and deletion tests. Thank you. |

## Scoreboard (against the October 29 proposal)

| Promised | State | Evidence |
|---|---|---|
| Complete question-to-answer flow | Done | Voice in, sourced answer out, in Chinese and English |
| Answer check | Done | Fixed answers for danger, harm, death, secrets; adversarial set 21 to 22 of 23 ([midpoint](../evals/results/2026-11-17-midpoint.md)) |
| Offline library with sources | Done | 53/53 ranking checks; privacy gate: 0 leaks in 38 sentences |
| Parent help request | Done | One-tap button and voice; rate limited and logged |
| Parent alerts and topic summary | Done | Alerts for harm and bullying, category only; weekly report with facts only |
| Trial with my daughter (planned for the final) | Early | Two days of real use; correct handling 72% to 80% on 215 replayed turns |
| 100 reviewed library entries | In progress | 861 entries written; parent review not finished |
| Accurate retelling of library pages | Partly | Right page found, retelling wrong in the moon demo |
| Speed: median under 3 s | Not met | 3.14 s median to first word; 6 of 16 runs within 3 s |
| Real child speech measured | Partly | Real sessions replayed; recognition accuracy not measured yet |
| Approved tools and inputs | Partly | Rules are in code, but spread across modules, not one layer |
| Privacy checks: network traffic, access, deletion | Left | For the final |
| Supervised trial findings, reproducible demo | Left | For the final |

Note on the proposal's wording "Only approved parent updates may leave the home server": the Wikipedia lookup (listed
as a v0.1 prototype in the proposal) also sends a cleaned topic word, never her sentence. The video states both.
