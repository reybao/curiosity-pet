"""Follow-up questions: decided by the program, not by the model.

The parent's complaint: the 4B model ended every answer with a question, even when the child did not
want to answer. Rules (kept across stop and start; reset after RESET_AFTER_S without a turn):
- no question by default, none on the first turn; at most one every MIN_GAP turns;
- never right after the child ignored one (asked something else instead of answering);
- never on a follow-up turn ("simpler", "example", ...), the child is still on the previous answer;
- once the child says "stop asking" (or "I don't want to answer"), none for the rest of the exploration.
When a question is not allowed, the prompt says so and any sentence ending with a question mark is
dropped before it is spoken, so a disobedient model cannot sneak one in.
"""

import re
import time

from curiosity_pet.usage import classify_follow_up

MIN_GAP = 3  # turns between two questions
RESET_AFTER_S = 30 * 60  # a pause this long starts a fresh exploration for the question limit

STOP_ASKING = re.compile(
    r"别问|不要问|不想回答|不想说|不要再问|别再问|不回答|我不答|"
    r"stop asking|don'?t ask|no more questions|i don'?t want to answer|not answering",
    re.IGNORECASE,
)
QUESTION_END = re.compile(r"[?？]\s*$")
# A message that looks like a new question rather than an answer to the pet's question
NEW_QUESTION = re.compile(
    r"为什么|为啥|什么|怎么|怎样|哪|谁|几|多少|吗\s*[?？]?$|呢\s*[?？]?$|"
    r"^\s*(why|what|how|who|where|when|which|is|are|do|does|did|can|could)\b|[?？]\s*$",
    re.IGNORECASE,
)


def ends_with_question(sentence: str) -> bool:
    return bool(QUESTION_END.search(sentence))


def looks_like_new_question(text: str) -> bool:
    return bool(NEW_QUESTION.search(text))


class FollowUpPolicy:
    def __init__(self, min_gap: int = MIN_GAP, clock=time.monotonic):
        self.min_gap = min_gap
        self.clock = clock
        self.last_turn = None
        self.reset()

    def reset(self):
        self.turns_since_question = 0  # no question on the first turn
        self.pending_question = False  # the last answer ended with a question
        self.ignored = 0  # the child did not answer the last question
        self.off = False

    def new_turn(self):
        """Called at the start of each turn: after a long pause the limits start afresh."""
        now = self.clock()
        if self.last_turn is not None and now - self.last_turn > RESET_AFTER_S:
            self.reset()
        self.last_turn = now

    def allow(self, child_text: str) -> bool:
        """Decide for the turn that answers child_text. Also updates the state from what the child said."""
        if STOP_ASKING.search(child_text):
            self.off = True
        if self.pending_question:
            if looks_like_new_question(child_text):
                self.ignored += 1
                self.turns_since_question = 0  # start the cooldown again
            self.pending_question = False
        if self.off or classify_follow_up(child_text):
            return False
        if self.ignored >= 2:
            return False  # ignored twice in a row: stop for this exploration
        return self.turns_since_question >= self.min_gap

    def after_turn(self, asked: bool):
        if asked:
            self.turns_since_question = 0
            self.pending_question = True
        else:
            self.turns_since_question += 1

    def answered(self):
        """The child replied to the pet's question (not with a new question): clear the ignore count."""
        self.ignored = 0
