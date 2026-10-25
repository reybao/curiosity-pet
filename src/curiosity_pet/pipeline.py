"""One full question-and-answer pass: ASR -> language detection -> streaming generation -> per-sentence TTS -> playback.

All timings start from the moment the child is judged to have finished speaking. Guards (stage 5) and retrieval (stage 4) are inserted before generation.
Session history lives in memory only and vanishes when the process ends; it is never written to disk (hard constraint 2).
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from curiosity_pet import arith, clock, config
from curiosity_pet.audio import Player, thinking_cue
from curiosity_pet.followup import FollowUpPolicy, ends_with_question, looks_like_new_question
from curiosity_pet.privacy import about_specific_things, expresses_distress, looks_like_knowledge_question
from curiosity_pet.lang import detect_language
from curiosity_pet.llm import UNAVAILABLE_TEXT, PetUnavailable, stream_chat
from curiosity_pet.lookup import filler
from curiosity_pet.prompts import ABILITY_NOTE, CHILD_RIDDLE_NOTE, CHILD_RIDDLE_REPLY_NOTE, GUESS_SPOKEN, build_messages, character_note
from curiosity_pet.riddles import (
    REPLY_WORDS, TEXT as RIDDLE_TEXT, RiddleGame, child_poses, could_be_told_riddle, has_riddle_content, is_long, word_count,
    looks_like_riddle, wants_another, wants_riddle,
)
from curiosity_pet.sentences import SentenceSplitter
from curiosity_pet.textclean import MeowLimiter, clean_for_speech
from curiosity_pet import concern, memory, router as router_mod, safety, story, utterance
from curiosity_pet import call_parent
from curiosity_pet.call_parent import CallParent, answer_kind, detect

log = logging.getLogger("curiosity_pet.pipeline")

MAX_HISTORY_MESSAGES = 8


@dataclass
class Turn:
    question: str = ""
    lang: str = ""
    answer: str = ""
    sentences: list[str] = field(default_factory=list)
    asr_s: float | None = None
    first_token_s: float | None = None
    first_sentence_s: float | None = None
    first_audio_s: float | None = None  # first sentence synthesized, playback starts
    tts_s: list[float] = field(default_factory=list)  # synthesis time per sentence
    lookup_reason: str = ""  # why no lookup happened (reason only, never content)
    looked_up: bool = False  # whether a web lookup was made
    source: str | None = None  # title of the Wikipedia entry the answer is based on
    topic: str | None = None  # topic tag (given by the model during the lookup decision, otherwise tagged afterwards)
    total_s: float | None = None
    unavailable: bool = False
    cancelled: bool = False  # the child pressed stop while this turn was running
    guessed: bool = False  # no material for a question about specific things: spoken as a guess
    ignored: bool = False  # only fillers or laughter: not answered, not recorded
    ended: bool = False  # the pet ended the exploration (goodbye, or the natural wrap-up): go idle after playback
    intent: str = ""  # what the router judged the message to be (when the router is on)
    route: str = ""  # which path answered (ignore, clarify, call, memory, safety, goodbye, story, riddle_pet, riddle_child,
    #                  time, math, lookup, model, unavailable); for the replay evaluation and the logs


def search_label(host: str, lang: str) -> str:
    from curiosity_pet.search import label

    return label(host, lang)


GOODBYE_WORDS = ("再见", "拜拜", "bye", "goodbye")
# The farewell is fixed, not left to the model: the model once asked "how was your day" when saying goodbye, which is emotional probing
def farewell(lang: str, persona: dict | None = None) -> str:
    sound = (persona or config.PERSONA)["sound"][lang]
    default = f"好的,下次见,{sound}!" if lang == "zh" else f"Okay, see you next time. {sound.capitalize()}!"
    return default if persona is not None else config.phrase("farewell", lang, default)


FAREWELL = {lang: farewell(lang) for lang in ("zh", "en")}


# "Which one is the biggest ocean?" matched a bank riddle on two words and was taken as her riddle (replay)
SUPERLATIVE = re.compile(r"biggest|largest|oldest|tallest|fastest|smallest|最大|最高|最老|最快|最小|最长|which one", re.IGNORECASE)


def still_about_her_riddle(text: str) -> bool:
    """After the pet guessed her riddle: only a reply about it continues ("对了", "不对,是小猫", "Yes!"); a call, a goodbye,
    a story or a new question ends the riddle (it used to take over "你可以帮我叫一下爸爸吗?" and "好,谢谢,拜拜")."""
    if detect(text) is not None or is_goodbye(text) or story.request(text) is not None:
        return False
    return bool(REPLY_WORDS.search(text)) or (word_count(text) <= 3 and not looks_like_new_question(text))


def story_topic_ok(text: str) -> bool:
    """Whether something the child said earlier may be woven into a story ("我想打我弟弟" once was)."""
    return (utterance.kind(text) == "ok" and not concern.concerns(text) and not memory.wants_to_save(text)
            and not memory.asks_what_i_like(text) and not memory.stated_likes(text) and not memory.stated_unlikes(text)
            and not utterance.asks_about_abilities(text) and story.request(text) is None
            and safety.fixed_response(text, [], "zh") is None and len(text.strip()) >= 4)


GOODBYE_END = re.compile(r"(?:^|[,，。.!！\s])(?:拜拜|再见|bye[- ]?bye|goodbye|bye)[\s。.!！~～]*$", re.IGNORECASE)


def is_goodbye(text: str) -> bool:
    """A goodbye alone, or at the end of a short message ("好,谢谢,拜拜。" was missed)."""
    t = "".join(c for c in text.lower() if c.isalnum())
    return t in GOODBYE_WORDS or (len(text.strip()) <= 16 and bool(GOODBYE_END.search(text.strip())))


class Pet:
    def __init__(
        self, asr, tts, player: Player, on_sentence=None, on_question=None, researcher=None, usage=None,
        riddles=None, guard=None, guard_answers=False, router="auto",
    ):
        self.researcher = researcher  # web lookup (lookup.Researcher); None means no web access
        self.guard = guard  # guard.Guard or None; judges the question, and every sentence when guard_answers
        # Context-aware intent judgment (router.py); settings.json "router": true turns it on, "auto" follows that
        self.router = (router_mod.Router() if config.ROUTER else None) if router == "auto" else (router or None)
        self.started_at: float | None = None  # first turn of this exploration (for the natural wrap-up)
        self.last_exchange: tuple | None = None  # (lang, question, what was said): "收藏这个" keeps it
        self.story_waiting: str | None = None  # "story" / "bedtime": the pet asked who the story is about
        self.guard_answers = guard_answers
        self.usage = usage  # usage log (usage.UsageLog); None means no logging (CLI, evals)
        self.asr = asr
        self.tts = tts
        self.player = player
        self.on_sentence = on_sentence or (lambda s: None)
        self.on_question = on_question or (lambda q, lang: None)
        self.history: list[dict] = []
        self.followup = FollowUpPolicy()
        self.riddles = riddles if riddles is not None else RiddleGame(store=getattr(usage, "store", None), judge=None)
        # Calling a parent (call_parent.py): fixed phrases, asks first, parent settings decide what is sent
        self.calls = CallParent(client=getattr(usage, "client", "cli"), store=getattr(usage, "store", None))

    def handle_audio(self, audio: np.ndarray, play_cue: bool = True, cancel=None) -> Turn:
        """Called after the VAD decides the child has finished. Plays the cue sound first, then recognizes and answers.

        In web mode the cue sound is played locally on the iPad (faster), so pass play_cue=False here.
        """
        t0 = time.perf_counter()
        if play_cue:
            self.player.play(thinking_cue())
        if cancel is not None and cancel.is_set():
            return Turn()
        text, asr_lang = self.asr.transcribe(audio)
        # asr_s in answer() is the time from t0 to the start of generation, i.e. the recognition time here
        return self.answer(text, asr_lang, t0=t0, cancel=cancel)

    def answer(
        self, question: str, asr_lang: str | None = None, t0: float | None = None, cancel=None
    ) -> Turn:
        """Answer one message; then, past the wrap-up time, close the exploration gently (it never tries to keep the child)."""
        turn = self._answer(question, asr_lang, t0=t0, cancel=cancel)
        if turn.ended or turn.cancelled or turn.ignored or not turn.sentences:
            return turn
        now = time.monotonic()
        self.started_at = self.started_at or now
        said = ("" if turn.lang == "zh" else " ").join(turn.sentences)
        if turn.topic not in ("safety",) and not memory.wants_to_save(question):
            self.last_exchange = (turn.lang, question, said)
        busy = self.riddles.pending is not None or self.riddles.child_stage is not None or turn.topic == "safety"
        if now - self.started_at >= config.WRAP_UP_MINUTES * 60 and not busy and not concern.concerns(question):
            text = config.phrase("wrap_up", turn.lang, memory.TEXT[turn.lang]["wrap_up"])
            audio = self.tts.synthesize(text, turn.lang)
            turn.sentences.append(text)
            self.player.play(audio, text=text, on_start=lambda s=text: self.on_sentence(s))
            turn.ended = True
            self.end_session("wrap_up")
        return turn

    def _answer(
        self, question: str, asr_lang: str | None = None, t0: float | None = None, cancel=None
    ) -> Turn:
        """cancel: optional threading.Event; when set (the child pressed stop) generation and speech stop
        as soon as possible and the turn is neither spoken further nor recorded."""
        t0 = t0 if t0 is not None else time.perf_counter()
        turn = Turn(question=question)
        turn.asr_s = time.perf_counter() - t0
        turn.lang = detect_language(question, fallback=asr_lang or "zh")
        if not question:
            return turn
        self.on_question(question, turn.lang)
        self.followup.new_turn()  # a long pause starts the question limit afresh
        # While the pet waits for the child (it asked something, or a riddle is open) every message is an answer;
        # otherwise fillers and laughter are not answered, and a lone word gets "I didn't catch that"
        waiting = (self.followup.pending_question or self.riddles.pending is not None
                   or self.riddles.child_stage is not None or self.calls.pending is not None)
        heard = utterance.kind(question)
        if heard == "fragment" and waiting:
            heard = "ok"  # "十。" or "Dog." can be a real answer
        if heard == "noise" and not (self.calls.pending is not None and answer_kind(question)):
            turn.route = "ignore"
            turn.ignored = True
            return turn
        about_self = utterance.asked_about_self(question)
        splitter = SentenceSplitter()
        worries = concern.concerns(question)
        if worries and self.usage:
            self.usage.note(question, turn.lang, worries)  # for the parent, facts only (concern.py)
            # Serious ones may also go to the parents' Telegram (category only, off unless the parent turned it on).
            # It can wait on the network, so it runs off the answer path.
            threading.Thread(target=call_parent.notify_concern, args=(worries, question, getattr(self.usage, "client", "ipad")),
                             kwargs={"store": getattr(self.usage, "store", None)}, daemon=True).start()
        care = expresses_distress(question) or any(w in worries for w in ("harm_self", "harm_others", "bullied", "family_conflict", "scared", "sad"))
        ask_allowed = self.followup.allow(question) and not care
        if not ends_with_question(question) and not care:
            self.followup.answered()
        meow = MeowLimiter()
        riddle_note = None  # set below when the child poses a riddle
        story_mode = None  # set below for a story or bedtime story

        def cancelled():
            return cancel is not None and cancel.is_set()

        def speak(sentence, force_question=False):
            spoken = meow(clean_for_speech(sentence))
            if not spoken or cancelled():
                return
            if not force_question:
                if not about_self:
                    spoken = utterance.drop_disclaimers(spoken)  # "I'm a program, no feelings" only when asked
                spoken = utterance.guard_sentence(spoken)  # no praise, secrets or pretended abilities
                if not turn.sentences or turn.sentences == [filler(turn.lang)]:
                    spoken = utterance.tidy_start(spoken)  # the sentence before it was cut: no leading "不过"
                if not spoken:
                    return
                spoken = safety.remove_blocked(spoken)  # the parent's blocklist applies to answers too
                if not spoken:
                    return
                if self.guard is not None and self.guard_answers and not self.guard.answer(question, spoken).safe:
                    return  # safety layer 2: the guard judged this sentence unsafe
            in_story_dialogue = story_mode is not None and re.search(r"[“”「」\"]", spoken)  # a character asking, not the pet
            if (not force_question and not in_story_dialogue and ends_with_question(spoken)
                    and any(ends_with_question(x) for x in turn.sentences)):
                return  # at most one question per answer, even when a question is allowed
            if (not force_question and not ask_allowed and not in_story_dialogue and ends_with_question(spoken)
                    and spoken not in (filler(turn.lang), farewell(turn.lang))):
                return  # the program, not the model, decides when the pet asks something
            if riddle_note and any(ends_with_question(x) for x in turn.sentences):
                return  # a child's riddle: stop at the first question ("我猜对了吗?"), nothing tacked on after it
            ts = time.perf_counter()
            audio = self.tts.synthesize(spoken, turn.lang)
            turn.tts_s.append(time.perf_counter() - ts)
            if turn.first_audio_s is None:
                turn.first_audio_s = time.perf_counter() - t0
            turn.sentences.append(spoken)
            self.player.play(audio, text=spoken, on_start=lambda s=spoken: self.on_sentence(s))

        # Doubtful messages (short, or speaking of someone as 他/它) are checked by the router: talk not meant for the
        # pet gets no answer, garbled speech gets "I didn't catch that" (router.py; settings.json "router": true)
        if self.router is not None and router_mod.doubtful(question, router_mod.activity_of(self)):
            label = self.router.classify(question)
            turn.intent = label
            if label == "side":
                turn.route = "ignore"
                turn.ignored = True
                return turn
            if label == "garbled":
                turn.route = "clarify"
                return self._say_fixed(turn, config.phrase("not_heard", turn.lang, utterance.NOT_HEARD[turn.lang]), t0,
                                       topic="other", speak=speak)

        # Calling a parent (call_parent.py): fixed phrases, or the local model's dad/mom/both/none verdict on a
        # sentence that names a parent; the pet always asks first. No model judging while a riddle or story is on.
        in_game = (self.riddles.pending is not None or self.riddles.child_stage is not None
                   or self.story_waiting is not None or story.request(question) is not None)
        call = self.calls.handle(question, turn.lang, judge_ok=not in_game)
        if call is not None:
            self._switch_activity()  # one activity at a time: a call request ends a riddle or a story question
            turn.route = "call"
            return self._say_fixed(turn, call, t0, topic="call_parent", speak=speak)

        if heard == "fragment":
            text = config.phrase("not_heard", turn.lang, utterance.NOT_HEARD[turn.lang])
            turn.route = "clarify"
            return self._say_fixed(turn, text, t0, topic="other", speak=speak)

        # Memory the child chose (memory.py): keep a discovery, recall or forget interests
        store = getattr(self.usage, "store", None)
        if memory.wants_to_save(question) and store is not None:
            if self.last_exchange is None:
                turn.route = "memory"
                return self._say_fixed(turn, memory.TEXT[turn.lang]["nothing_to_save"], t0, topic="memory", speak=speak)
            store.add_discovery(*self.last_exchange)
            turn.route = "memory"
            return self._say_fixed(turn, memory.TEXT[turn.lang]["saved"], t0, topic="memory", speak=speak)
        if memory.asks_if_remembered(question):
            turn.route = "memory"
            return self._say_fixed(turn, memory.TEXT[turn.lang]["remember"], t0, topic="memory", speak=speak)
        if memory.asks_what_i_like(question) and store is not None:
            liked = store.interests()
            text = (memory.TEXT[turn.lang]["recall"].format(what=memory.names(liked, turn.lang)) if liked
                    else memory.TEXT[turn.lang]["recall_none"])
            turn.route = "memory"
            return self._say_fixed(turn, text, t0, topic="memory", speak=speak)
        forget = memory.stated_unlikes(question)
        if forget and store is not None:
            for t in forget:
                store.remove_interest(t)
            text = memory.TEXT[turn.lang]["unliked"].format(what=memory.names(forget, turn.lang))
            turn.route = "memory"
            return self._say_fixed(turn, text, t0, topic="memory", speak=speak)
        likes = memory.stated_likes(question)
        if likes and store is not None:
            new = [t for t in likes if t not in store.interests()]
            for t in likes:
                store.add_interest(t)
            if new:  # say it once, then answer her normally
                speak(memory.TEXT[turn.lang]["liked"].format(what=memory.names(new, turn.lang)), force_question=True)

        # The most serious messages, dangerous actions and the parent's blocked words get a fixed answer (safety.py)
        fixed_safety = safety.fixed_response(question, worries, turn.lang)
        if fixed_safety is None and self.guard is not None and not self.guard.question(question).safe:
            fixed_safety = ("guard", safety.FIXED["blocked"][turn.lang])
        if fixed_safety is not None:
            turn.route = "safety"
            return self._say_fixed(turn, fixed_safety[1], t0, topic="safety", speak=speak)

        if is_goodbye(question):
            turn.route = "goodbye"
            turn.answer = farewell(turn.lang)
            turn.topic = "chat"
            turn.ended = True
            speak(turn.answer)
            turn.total_s = time.perf_counter() - t0
            self._record(turn)
            self.end_session("goodbye")
            return turn

        # Story and bedtime modes (story.py): original stories, the child picks who and where, never online
        story_note = None
        wanted = story.request(question)
        if self.story_waiting and wanted is None:
            story_mode, about = self.story_waiting, question  # her answer to "who is it about?"
        elif wanted is not None:
            story_mode, about = wanted
            self._switch_activity(keep_story=True)
            if not about:
                self.story_waiting = story_mode
                turn.route = "story"
                return self._say_fixed(turn, story.TEXT[turn.lang]["ask"], t0, topic="story", speak=speak, force_question=True)
        self.story_waiting = None
        if story_mode:
            # Only real questions from today go into the story: not worries, safety turns, commands or fragments
            topics = [m["content"] for m in self.history if m["role"] == "user" and story_topic_ok(m["content"])][-3:]
            turn.route = "story"
            story_note = story.note(turn.lang, story_mode, about, topics)
            turn.topic = "story"
            ask_allowed = False

        # The child poses a riddle: say "go ahead" until it comes, then let the model guess it (never a riddle back)
        game = self.riddles
        # A riddle told without announcing it: an unmistakable riddle form, or one of the classics in the bank
        unannounced = (game.pending is None and game.child_stage is None and not child_poses(question)
                       and (looks_like_riddle(question)
                            or (could_be_told_riddle(question) and not SUPERLATIVE.search(question)
                                and game.recognize(question, turn.lang, threshold=0.8) is not None)))
        if story_note:
            pass
        elif child_poses(question) or unannounced:
            game.pending = None
            if not unannounced and not has_riddle_content(question):
                game.child_stage, game.child_turns = "waiting", 0
                text = config.phrase("ready", turn.lang, RIDDLE_TEXT[turn.lang]["ready"])
                turn.route = "riddle_child"
                return self._say_fixed(turn, text, t0, topic="riddle", speak=speak)
            game.child_stage, game.child_turns = "guessing", 0
            known = game.recognize(question, turn.lang)
            if known:  # a classic the pet knows: answer it instead of guessing
                text = RIDDLE_TEXT[turn.lang]["known"].format(a=known.a)
                turn.route = "riddle_child"
                return self._say_fixed(turn, text, t0, topic="riddle", speak=speak, force_question=True)
            turn.route = "riddle_child"
            riddle_note = CHILD_RIDDLE_NOTE[turn.lang]
        elif game.child_stage == "waiting":
            game.child_stage, game.child_turns = "guessing", 0
            known = game.recognize(question, turn.lang)
            if known:
                text = RIDDLE_TEXT[turn.lang]["known"].format(a=known.a)
                turn.route = "riddle_child"
                return self._say_fixed(turn, text, t0, topic="riddle", speak=speak, force_question=True)
            turn.route = "riddle_child"
            riddle_note = CHILD_RIDDLE_NOTE[turn.lang]
        elif (game.child_stage == "guessing" and not wants_riddle(question) and game.child_turns < 3
              and still_about_her_riddle(question)):
            game.child_turns += 1
            turn.route = "riddle_child"
            riddle_note = CHILD_RIDDLE_REPLY_NOTE[turn.lang]
        else:
            game.child_stage = None
        if riddle_note:
            turn.topic = "riddle"
        if riddle_note is CHILD_RIDDLE_NOTE[turn.lang]:
            ask_allowed = True  # "我猜对了吗?" belongs to guessing; after her reply the usual question limit applies

        # Riddles: the child is answering one, or asks for one. The answer is held by the program.
        if riddle_note or story_note:
            pass
        elif self.riddles.pending is not None:
            outcome = self.riddles.answer(question)
            if not outcome.dropped:
                turn.route = "riddle_pet"
                return self._say_fixed(turn, outcome.text, t0, topic="riddle", speak=speak)
        if not riddle_note and not story_note and (wants_riddle(question) or (self.riddles.last is not None and wants_another(question))):
            turn.route = "riddle_pet"
            return self._say_fixed(turn, self.riddles.next(turn.lang), t0, topic="riddle", speak=speak, force_question=True)

        fixed = None if riddle_note or story_note else clock.answer(question, turn.lang)
        if fixed is not None:
            # The model has no clock: dates and times come from the Mac
            turn.route = "time"
            return self._say_fixed(turn, fixed, t0, topic="time", speak=speak)

        claim = None if riddle_note or story_note else arith.parse_claim(question)
        if claim is not None:
            # The child states a result: the program checks it (the model invented reasoning for "三加四等于七")
            turn.route = "math"
            return self._say_fixed(turn, arith.explain_claim(*claim, turn.lang), t0, topic="math", speak=speak)
        expr = None if riddle_note or story_note else arith.parse(question)
        if expr is not None:
            # Arithmetic is computed, never asked of the model (it got 91 / 5 wrong)
            turn.route = "math"
            return self._say_fixed(turn, arith.explain(expr, turn.lang), t0, topic="math", speak=speak)

        reference = None
        source_label = None
        decision = None
        if self.researcher and not riddle_note and not story_note:  # riddles and stories are not looked up
            decision = self.researcher.decide(question, turn.lang)
            turn.lookup_reason = decision.reason
            turn.topic = decision.topic
            if decision.go:
                # A web lookup takes 1 to 2 extra seconds: say something first so the child does not wait in silence
                speak(filler(turn.lang))
                turn.looked_up = True
                try:
                    result = self.researcher.fetch(decision, turn.lang)
                except Exception as e:  # noqa: BLE001  network down or a broken source: answer without material
                    log.warning("lookup failed: %s", type(e).__name__)
                    result = None
                if result:
                    reference = (result.title, result.text)
                    source_label = search_label(result.host, turn.lang)
                    turn.source = f"{source_label}: {result.title}"

        if riddle_note or story_note:
            knowledge = False
        elif decision is not None and decision.kind:
            knowledge = decision.kind == "knowledge"
        else:
            knowledge = looks_like_knowledge_question(question)
        # The character card only when the child asks about the character or its world (keeps other turns fast)
        card_note = None if riddle_note or story_note else character_note(question, turn.lang, config.PERSONA, config.card_keywords())
        ability_note = ABILITY_NOTE[turn.lang] if utterance.asks_about_abilities(question) else None
        # "你是谁?" asked of the pet is answered from its card, not marked as a guess
        about_pet = card_note is not None and re.search(r"你|\byou\b|\byour\b", question, re.IGNORECASE)
        guess = reference is None and knowledge and about_specific_things(question) and not about_pet
        if guess:
            turn.guessed = True
            speak(GUESS_SPOKEN[turn.lang])
            if self.usage:
                self.usage.unanswered(question, turn.lang, turn.topic)

        msgs = build_messages(
            question, turn.lang, self.history, reference=reference, ask=ask_allowed, care=care, guess=guess,
            date_note=clock.date_note(turn.lang) if clock.mentions_time(question) else None, source=source_label,
            note="\n".join(n for n in (card_note, riddle_note, ability_note, story_note) if n) or None,
        )
        normal_speed = getattr(self.tts, "speed", None)
        if story_mode == "bedtime" and normal_speed is not None:
            self.tts.speed = story.BEDTIME_SPEED
        try:
            for piece in stream_chat(msgs):
                if cancelled():
                    turn.cancelled = True
                    return turn
                if turn.first_token_s is None:
                    turn.first_token_s = time.perf_counter() - t0
                turn.answer += piece
                for sentence in splitter.feed(piece):
                    if turn.first_sentence_s is None:
                        turn.first_sentence_s = time.perf_counter() - t0
                    speak(sentence)
            for sentence in splitter.flush():
                if turn.first_sentence_s is None:
                    turn.first_sentence_s = time.perf_counter() - t0
                speak(sentence)
        except PetUnavailable:
            # Local model unavailable: read the fixed notice aloud, never fall back to an external service
            turn.unavailable = True
            turn.answer = UNAVAILABLE_TEXT[turn.lang]
            speak(turn.answer)
            self._record(turn)
            turn.route = "unavailable"
            return turn
        finally:
            if story_mode == "bedtime" and normal_speed is not None:
                self.tts.speed = normal_speed
            turn.total_s = time.perf_counter() - t0
        if story_mode == "bedtime" and not cancelled():
            if normal_speed is not None:
                self.tts.speed = story.BEDTIME_SPEED
            speak(story.TEXT[turn.lang]["goodnight"], force_question=True)
            if normal_speed is not None:
                self.tts.speed = normal_speed
            turn.ended = True  # bedtime ends the exploration after the story

        # Store what was actually spoken in history (extra meows removed), so the model does not learn to meow more and more
        said = [x for x in turn.sentences if x != filler(turn.lang)]
        self.history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": "".join(said) if turn.lang == "zh" else " ".join(said)},
        ]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.followup.after_turn(asked=bool(turn.sentences) and ends_with_question(turn.sentences[-1]))
        turn.route = turn.route or ("lookup" if turn.looked_up else "model")
        self._record(turn)
        if turn.ended:
            self.end_session("bedtime")
        return turn

    def _say_fixed(self, turn: Turn, text: str, t0: float, topic: str, speak, force_question: bool = False) -> Turn:
        """Speak program-made text (riddle, arithmetic) without the model, keeping history and records in step."""
        turn.answer = text
        turn.topic = topic
        # Program-made text is deliberate: a riddle, or a hint phrased as a question, is never filtered out.
        # One splitter instance: feed then flush, so a final English sentence without a trailing space is kept.
        fixed = SentenceSplitter(merge_short_first=False)
        for sentence in fixed.feed(text) + fixed.flush():
            speak(sentence, force_question=True)
        turn.total_s = time.perf_counter() - t0
        self.history += [{"role": "user", "content": turn.question}, {"role": "assistant", "content": "".join(turn.sentences)}]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.followup.after_turn(asked=False)
        self._record(turn)
        return turn

    def _switch_activity(self, keep_story: bool = False):
        """Starting something new ends whatever was going on (a riddle, a story question), so it cannot take over later
        messages; a riddle state once captured "你可以帮我叫一下爸爸吗?" and "好,谢谢,拜拜"."""
        self.riddles.pending = None
        self.riddles.child_stage = None
        if not keep_story:
            self.story_waiting = None

    def _record(self, turn: Turn):
        if self.usage and not turn.cancelled:
            self.usage.record(turn)

    def end_session(self, reason: str = "end"):
        """End an exploration: clear the session history; when logging, record how it ended (said goodbye, pressed end, just left)."""
        self.history = []
        self.started_at = None
        self.last_exchange = None
        self.story_waiting = None
        self.calls.reset()
        # The question limit is kept across stop/start (the child restarted 28 times in one afternoon, and the
        # first turn of each restart used to allow a question); FollowUpPolicy starts afresh after a long pause
        self.riddles.reset()
        if self.usage:
            self.usage.end(reason)
