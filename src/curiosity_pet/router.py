"""Is this message meant for the pet? A small, context-free check for doubtful messages (2026-10-24, step 3).

The replay of the first two days (evals/results/2026-10-24-replay.md) found 72% of turns handled right; 62% of the
mistakes were talk not meant for the pet (adults, a navigation voice) or garbled recognition answered as a question.
A first router that asked the 9B model to name the intent of every message was measured and rejected
(evals/results/2026-10-24-router.md): 74% instead of 72%, about 3 seconds more per answer, and it called "你好" and
"my tummy hurts" not meant for the pet, so the child got silence. What works on this machine:
- only doubtful messages are checked: short ones, and ones that speak of someone as 他/它/he/it (side talk does), and
  never while the pet is waiting for her answer (then a short reply is expected);
- one word from the model, with a few made-up examples (none taken from the replay data): chat, side or garbled,
  about 1.2 seconds; on doubt it answers "chat", so a real question is never dropped;
- side: no answer at all; garbled: "I didn't catch that".
The current activity and its end are handled by explicit rules in the pipeline and the handlers (riddles, calls,
stories), not by the model. Nothing leaves the machine.
"""

import re

from curiosity_pet import config

PROMPT = """Classify what a 7-year-old's message to a talking pet program is. Speech recognition may garble words; adults or a navigation voice may be picked up.
Labels: chat (said to the pet: questions, greetings, feelings, answers), side (not said to the pet: adults talking, speaking about the pet as he/it, navigation), garbled (makes no sense).
Examples:
"你好呀。" -> chat
"为什么天会下雨？" -> chat
"五。" -> chat
"我今天肚子有点疼。" -> chat
"你问它一下吧。" -> side
"Turn right in 300 feet." -> side
"他刚才听成五加五了。" -> side
"好，开布。" -> garbled
"Seven SL，那我次看就。" -> garbled
Message: "{text}" ->"""
THIRD = re.compile(r"他|它|(?<![a-z])(?:he|it|him)(?![a-z])", re.IGNORECASE)
WAITING = ("call_confirm", "pet_riddle", "child_riddle_waiting", "child_riddle_guessed", "story_hero", "pet_question")


def activity_of(pet) -> str:
    """The one current activity, from the handlers' own state."""
    if pet.calls.pending is not None:
        return "call_confirm"
    if pet.riddles.pending is not None:
        return "pet_riddle"
    if pet.riddles.child_stage == "waiting":
        return "child_riddle_waiting"
    if pet.riddles.child_stage == "guessing":
        return "child_riddle_guessed"
    if pet.story_waiting:
        return "story_hero"
    if pet.followup.pending_question:
        return "pet_question"
    return "chat"


def doubtful(text: str, activity: str) -> bool:
    """Worth checking: short, or speaks of someone in the third person; never while the pet waits for an answer."""
    if activity in WAITING:
        return False
    size = len(re.findall(r"[一-鿿]", text)) + len(re.findall(r"[a-zA-Z']+", text))
    return size <= 4 or bool(THIRD.search(text))


def judge_with_model(text: str) -> str:
    import httpx

    from curiosity_pet.llm import LOCAL_HOSTS
    from urllib.parse import urlparse

    if urlparse(config.OLLAMA_URL).hostname not in LOCAL_HOSTS:
        return "chat"
    body = {"model": config.HELPER_MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content": PROMPT.format(text=text[:300])}],
            "options": {"temperature": 0, "num_predict": 3}}
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=10)
    r.raise_for_status()
    return r.json()["message"]["content"]


class Router:
    def __init__(self, judge=judge_with_model):
        self.judge = judge

    def classify(self, text: str) -> str:
        """"chat", "side" or "garbled"; anything unexpected (or a failure) is "chat", so nothing real is dropped."""
        try:
            word = re.sub(r"[^a-z]", "", str(self.judge(text)).lower())
        except Exception:  # noqa: BLE001
            return "chat"
        return next((label for label in ("side", "garbled") if word.startswith(label)), "chat")
