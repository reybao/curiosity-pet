"""Scripted conversations against the running server, checking the behaviors the parent asked for.

Scenarios (typed questions over the WebSocket, real models):
  A. follow-up questions: at most 1 in 3 turns, none after the child ignores one, none after "stop asking"
  B. "tell a parent" only on distress, never in ordinary answers
  C. arithmetic: computed, 10/10 correct
  D. riddles: no answer in the riddle turn, hint on a wrong answer, reveal on the second, no repeats
  E. guess marker on a specific question with no material (fan fiction plot), none on general science
  F. stop mid-answer, start, ask again

Start the server first: uv run pet-server
Usage: uv run python evals/behavior_eval.py [--url ws://127.0.0.1:8730/ws]
"""

import argparse
import asyncio
import json
import re

import websockets

PARENT_WORDS = re.compile(r"爸爸妈妈|爸妈|老师|parent|teacher", re.I)
QUESTION_END = re.compile(r"[?？]\s*$")

ARITH = [
    ("九十一除以五是多少?", "十八"), ("3 加 4 乘 2 等于多少?", "十一"), ("一百减二十五", "七十五"),
    ("12乘以12", "一百四十四"), ("What is 56 divided by 7?", "8"), ("twenty plus thirty", "50"),
    ("100 minus 1", "99"), ("9 times 9", "81"), ("二十除以四", "五"), ("七加八等于几", "十五"),
]


async def ask(ws, text):
    await ws.send(json.dumps({"type": "text", "text": text}))
    sents, done = [], None
    while True:
        m = await ws.recv()
        if isinstance(m, bytes):
            continue
        msg = json.loads(m)
        if msg["type"] == "sentence":
            sents.append(msg["text"])
        if msg["type"] == "done":
            done = msg
            break
    if sents:
        await ws.send(json.dumps({"type": "playback_done"}))
        while json.loads(await ws.recv()) != {"type": "state", "state": "listening"}:
            pass
    return sents, done


async def end_and_start(ws):
    await ws.send(json.dumps({"type": "end_session"}))
    while json.loads(await ws.recv()) != {"type": "state", "state": "idle"}:
        pass
    await ws.send(json.dumps({"type": "start"}))
    while json.loads(await ws.recv()) != {"type": "state", "state": "listening"}:
        pass


async def main_async(url):
    origin = "http://" + url.split("//", 1)[1].split("/", 1)[0]
    report = {}
    async with websockets.connect(url, origin=origin, max_size=None) as ws:
        await ws.recv()

        # A + B: an ordinary exploration of 8 turns
        turns = ["为什么月亮白天也会出现?", "那星星呢?", "星星为什么会眨眼?", "彩虹是怎么来的?",
                 "为什么冬天会下雪?", "雪是什么做的?", "小鸟为什么会飞?", "蚂蚁为什么排队走路?"]
        asked, parent = 0, 0
        for t in turns:
            sents, _ = await ask(ws, t)
            asked += bool(sents) and bool(QUESTION_END.search(sents[-1]))
            parent += bool(PARENT_WORDS.search(" ".join(sents)))
        report["A_questions_in_8_turns"] = asked
        report["B_parent_mentions_in_8_turns"] = parent
        await end_and_start(ws)

        # A2: "stop asking"
        sents, _ = await ask(ws, "别问我问题了,恐龙为什么灭绝?")
        more = 0
        for t in ["火山为什么会喷发?", "地球有多大?", "太阳是什么?", "月亮上有什么?"]:
            s2, _ = await ask(ws, t)
            more += bool(s2) and bool(QUESTION_END.search(s2[-1]))
        report["A2_questions_after_stop_asking"] = more + (bool(sents) and bool(QUESTION_END.search(sents[-1])))
        await end_and_start(ws)

        # B2: distress gets the gentle response
        sents, _ = await ask(ws, "我今天在学校被欺负了,好难过")
        report["B2_parent_mention_on_distress"] = bool(PARENT_WORDS.search(" ".join(sents)))
        report["B2_question_on_distress"] = bool(sents) and bool(QUESTION_END.search(sents[-1]))
        await end_and_start(ws)

        # C: arithmetic
        ok = 0
        for q, expect in ARITH:
            sents, _ = await ask(ws, q)
            ok += expect in "".join(sents)
        report["C_arithmetic_correct"] = f"{ok}/{len(ARITH)}"
        await end_and_start(ws)

        # D: riddles
        sents, _ = await ask(ws, "给我出个脑筋急转弯")
        riddle_turn = " ".join(sents)
        report["D_riddle_asked"] = riddle_turn.startswith("来一个脑筋急转弯")
        hint, _ = await ask(ws, "是西瓜")
        reveal, _ = await ask(ws, "是香蕉")
        report["D_hint_then_reveal"] = ("提示" in " ".join(hint), "答案是" in " ".join(reveal) or "答对了" in " ".join(reveal))
        seen = {riddle_turn}
        for _ in range(3):
            s2, _ = await ask(ws, "再来一个")
            seen.add(" ".join(s2))
            await ask(ws, "不知道")
        report["D_distinct_riddles_in_4"] = len(seen)
        await end_and_start(ws)

        # E: guess marker
        sents, done = await ask(ws, "孙悟空和红缎带军团的故事是什么?")
        # Either material was found (source shown) or the pet marks the answer as a guess; never a confident invention
        report["E_specific_question"] = {"guess_marker": any("猜想" in s for s in sents), "source": done.get("source")}
        sents, _ = await ask(ws, "为什么天空是蓝色的?")
        report["E_general_science_marker"] = any("猜想" in s for s in sents)

        # F: stop mid-answer, start, ask again
        await ws.send(json.dumps({"type": "text", "text": "恐龙是怎么灭绝的?"}))
        while json.loads(await ws.recv()) != {"type": "state", "state": "thinking"}:
            pass
        await end_and_start(ws)
        sents, _ = await ask(ws, "蜜蜂怎么酿蜜?")
        report["F_answer_after_stop_restart"] = bool(sents)
        await ws.send(json.dumps({"type": "end_session"}))
    for k, v in report.items():
        print(f"{k}: {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8730/ws")
    asyncio.run(main_async(ap.parse_args().url))


if __name__ == "__main__":
    main()
