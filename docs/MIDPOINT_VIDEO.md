# Midpoint check-in video: script and shot list

About 4 minutes (hard limit 5), played to the class on Thursday, November 19. The narration is about 530 words.
It follows the proposal of October 29 (Kit): what was promised, what is done, what is left.

Draft: check it against the course's video guidelines before recording.

## Before recording

- Record the demo on the iPad with the built-in screen recording, microphone on.
- A parent asks the questions. Do not record the child's voice, face or name.
- Use only the built-in kitten. Do not show the private character skins.
- Use only the made-up questions below. Do not open the usage log, parent notes or the weekly report on screen.
- Hide or crop: the Tailscale address in the browser bar, the Telegram chat list and phone numbers.
- The help button sends a real message to both parents: tell the other parent before recording.
- Update the two cells marked "confirm" in the scoreboard on the day of recording.

## Shot list and narration

| Time | On screen | Narration |
|---|---|---|
| 0:00 to 0:25 | Proposal title slide, then proposal slide 4 with "One complete flow" highlighted. | "This is Kit, a private AI agent for my seven-year-old daughter, running on a Mac mini at home. In October I promised one complete flow: a spoken question, a sourced answer, and a separate way to reach a parent. Here is where that stands." |
| 0:25 to 0:50 | iPad. Tap Start. Ask in Chinese: "为什么月亮白天也会出现?" Answer plays with highlighted sentences. | "She taps and asks, in Chinese or English. Speech recognition, the language model and speech synthesis all run on the Mac mini. The answer comes back sentence by sentence." |
| 0:50 to 1:15 | Ask in English: "Who is Goku in Dragon Ball?" Zoom on the source line. | "Kit looks in a local library first and says where the answer came from. If the library has nothing, only a cleaned topic word goes to Wikipedia. Her sentence never leaves the house." |
| 1:15 to 1:45 | Tap the red "Get Mom or Dad" button. The page shows the confirmation. Cut to the phone: the message arrives (chat list cropped). Then tap again to show the rate-limit line. | "This is the help button from the proposal. One tap sends a fixed message to my phone. The language model is not involved. It is rate limited, and every attempt is logged. She can also just say it." |
| 1:45 to 2:40 | Scoreboard slide, top half ("Done"). Highlight rows as they are named. | "Against the plan. The question-to-answer flow is complete. The answer check is in code: every sentence is checked before it is spoken, and the adversarial set passes twenty-three of twenty-three. The privacy gate leaked zero of thirty-eight test sentences. The library ranks fifty-three of fifty-three test queries correctly. Parent alerts and the weekly topic summary both work. All of this is covered by six hundred forty-seven tests." |
| 2:40 to 3:15 | Slide "What real use taught me", three bullets. | "One thing came early. The proposal put the trial at the end, but she has already used Kit for two days. I replayed those sessions, which stay on our machine. A quarter of what the microphone heard on day one was laughter, fillers, or other people talking. After the fixes, the share of turns handled correctly went from seventy-two to eighty percent. She also found the small model wrong too often, so I moved to a larger one and accepted slower answers." |
| 3:15 to 4:00 | Scoreboard slide, bottom half ("Left"). | "What is left. Speed: the median time to first word is three point one seconds, above my three-second target. Recognition accuracy on her own voice is not measured yet. The library has about a hundred reviewed entries; I want more. The rules that limit actions are spread across modules, and I want them in one layer. And I still have to verify privacy by watching network traffic and testing deletion. Those are the work between now and the final. Thank you. Questions are welcome." |

## Scoreboard slide

| Promised in the proposal | State | Evidence |
|---|---|---|
| Complete question-to-answer flow (midpoint) | Done | Demo |
| Answer check (core) | Done | 23/23 adversarial cases, `evals/results/2026-10-24-adversarial.md` |
| Offline library, sourced answers (core) | Done | 53/53 ranking checks; privacy gate 0 leaks in 38 sentences |
| Parent help request: button and voice (core) | Done | 25/25 spoken requests found; button rate limited and logged |
| Parent alerts and topic summary (core) | Done | Category-only alerts; weekly report with facts only |
| Trial with the child (planned for the final) | Early | Two days of use; routing 72% to 80% on 215 replayed turns |
| 100 reviewed library entries (midpoint) | **confirm**: "Done, N approved" or "In progress, N of 100" | `uv run pet-library qa stats` |
| Real child speech measured (midpoint) | Partly | Real sessions replayed; recognition accuracy not measured |
| Speed: median under 3 s | Not met | 3.14 s median, 6 of 16 within 3 s, `evals/results/2026-11-17-midpoint.md` |
| Approved tools and inputs as one layer (core) | Partly | Rules are in code but spread across modules |
| Privacy checks: network traffic, access, deletion | Left | For the final |
| Supervised trial findings, reproducible demo | Left | For the final |

Test count: **confirm** with `uv run pytest` on the day (647 on November 17).

## Slide "What real use taught me"

- A quarter of first-day microphone input was not a question (laughter, fillers, other voices): the program now
  decides what counts as a message.
- The 4B model was wrong too often for her: moved to 9B, at the cost of speed.
- Behaviour moved from the prompt into code: follow-up questions rationed, arithmetic computed, no praise or
  judgment of her.

## If the 100 entries are not reviewed by Thursday

Replace the sentence "The library has about a hundred reviewed entries; I want more." with:
"Eight hundred library entries are written, but I have reviewed only N of them, so the hundred I promised are not
done."
