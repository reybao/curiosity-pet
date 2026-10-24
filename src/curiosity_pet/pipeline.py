"""一次问答的完整流程:ASR -> 语言判定 -> 流式生成 -> 逐句 TTS -> 放音。

计时都从"判定孩子说完"那一刻算起。守卫(阶段 5)和检索(阶段 4)以后插在生成之前。
会话历史只存在内存里,进程结束即消失,不落盘(硬性约束第 2 条)。
"""

import time
from dataclasses import dataclass, field

import numpy as np

from curiosity_pet.audio import Player, thinking_cue
from curiosity_pet.lang import detect_language
from curiosity_pet.llm import UNAVAILABLE_TEXT, PetUnavailable, stream_chat
from curiosity_pet.lookup import FILLER
from curiosity_pet.prompts import build_messages
from curiosity_pet.sentences import SentenceSplitter
from curiosity_pet.textclean import MeowLimiter, clean_for_speech

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
    first_audio_s: float | None = None  # 第一句音频合成完毕、开始播放
    tts_s: list[float] = field(default_factory=list)  # 每句合成耗时
    lookup_reason: str = ""  # 没联网的原因(只记原因,不记内容)
    looked_up: bool = False  # 是否联网查询了
    source: str | None = None  # 回答依据的维基百科条目标题
    total_s: float | None = None
    unavailable: bool = False


GOODBYE_WORDS = ("再见", "拜拜", "bye", "goodbye")
# 结束语固定,不交给模型:模型曾在道别时追问"你今天过得怎么样",属于情绪探询
FAREWELL = {"zh": "好的,下次见,喵!", "en": "Okay, see you next time. Meow!"}


def is_goodbye(text: str) -> bool:
    t = "".join(c for c in text.lower() if c.isalnum())
    return t in GOODBYE_WORDS


class Pet:
    def __init__(self, asr, tts, player: Player, on_sentence=None, on_question=None, researcher=None):
        self.researcher = researcher  # 联网查询(lookup.Researcher),None 表示不联网
        self.asr = asr
        self.tts = tts
        self.player = player
        self.on_sentence = on_sentence or (lambda s: None)
        self.on_question = on_question or (lambda q, lang: None)
        self.history: list[dict] = []

    def handle_audio(self, audio: np.ndarray, play_cue: bool = True) -> Turn:
        """VAD 判定说完后调用。先播提示音,再识别和回答。

        网页模式下提示音由 iPad 本地播放(更快),这里传 play_cue=False。
        """
        t0 = time.perf_counter()
        if play_cue:
            self.player.play(thinking_cue())
        text, asr_lang = self.asr.transcribe(audio)
        # answer() 里的 asr_s 记的是从 t0 到开始生成,这里即识别耗时
        return self.answer(text, asr_lang, t0=t0)

    def answer(self, question: str, asr_lang: str | None = None, t0: float | None = None) -> Turn:
        t0 = t0 if t0 is not None else time.perf_counter()
        turn = Turn(question=question)
        turn.asr_s = time.perf_counter() - t0
        turn.lang = detect_language(question, fallback=asr_lang or "zh")
        if not question:
            return turn
        self.on_question(question, turn.lang)
        splitter = SentenceSplitter()
        meow = MeowLimiter()

        def speak(sentence):
            spoken = meow(clean_for_speech(sentence))
            if not spoken:
                return
            ts = time.perf_counter()
            audio = self.tts.synthesize(spoken, turn.lang)
            turn.tts_s.append(time.perf_counter() - ts)
            if turn.first_audio_s is None:
                turn.first_audio_s = time.perf_counter() - t0
            turn.sentences.append(spoken)
            self.player.play(audio, text=spoken, on_start=lambda s=spoken: self.on_sentence(s))

        if is_goodbye(question):
            turn.answer = FAREWELL[turn.lang]
            speak(turn.answer)
            turn.total_s = time.perf_counter() - t0
            return turn

        reference = None
        if self.researcher:
            decision = self.researcher.decide(question, turn.lang)
            turn.lookup_reason = decision.reason
            if decision.go:
                # 联网要多花 1 至 2 秒:先说一句,孩子不用干等
                speak(FILLER[turn.lang])
                turn.looked_up = True
                result = self.researcher.fetch(decision, turn.lang)
                if result:
                    reference = (result.title, result.text)
                    turn.source = result.title

        msgs = build_messages(question, turn.lang, self.history, reference=reference)
        try:
            for piece in stream_chat(msgs):
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
            # 本地模型不可用:朗读固定提示,不转外部服务
            turn.unavailable = True
            turn.answer = UNAVAILABLE_TEXT[turn.lang]
            speak(turn.answer)
            return turn
        finally:
            turn.total_s = time.perf_counter() - t0

        # 历史里存实际念出来的内容(多余的喵已删),免得模型学着越喵越多
        said = [x for x in turn.sentences if x != FILLER[turn.lang]]
        self.history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": "".join(said) if turn.lang == "zh" else " ".join(said)},
        ]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        return turn

    def end_session(self):
        self.history = []
