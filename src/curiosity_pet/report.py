"""Weekly discovery report (CLAUDE.md "Weekly report"): `uv run pet-report [--week 2026-W43]`.

For the child and parent to read together. Only facts and counts: the questions she asked (verbatim), saved discoveries,
topic counts, questions without material, an "interaction habits" section of countable facts, and two or three activity
ideas from the local model. No adjectives about the child, no labels, no comparisons, no causes; a word-list check removes
any line that slips (the model's ideas included). The parent-only "worth knowing" notes are never in this report.

Written to DATA_DIR/reports/<week>.md (local only). settings.json "weekly_report": false turns it off;
`pet-report --delete <week>` deletes a week.
"""

import argparse
import datetime as dt
import re
import time
from pathlib import Path

from curiosity_pet import config
from curiosity_pet.concern import concerns
from curiosity_pet.store import Store
from curiosity_pet.utterance import kind

# Words that describe or judge the child, or interpret a trend; any line containing one is dropped
EVALUATIVE = re.compile(
    r"好奇心强|很好奇|聪明|内向|外向|专注|注意力|懒|笨|优秀|棒|厉害|天才|性格|越来越喜欢|兴趣浓厚|善于|擅长|进步|退步|"
    r"比别的|比同龄|平均|正常孩子|有天赋|害羞|胆小|勇敢|乖|"
    r"\bcurious\b|\bsmart\b|\bclever\b|\bintroverted\b|\bextroverted\b|\bfocused\b|\battention\b|\blazy\b|\bgifted\b|"
    r"\btalented\b|\bpersonality\b|\bmore and more\b|\bshy\b|\bbrave\b|\baverage\b",
    re.IGNORECASE,
)
WHY = re.compile(r"为什么|为啥|\bwhy\b", re.IGNORECASE)
HOW = re.compile(r"怎么|如何|怎样|\bhow\b", re.IGNORECASE)
WHAT = re.compile(r"什么|是谁|哪|\bwhat\b|\bwho\b|\bwhich\b|\bwhere\b", re.IGNORECASE)
TOPIC_ZH = {
    "animals": "动物", "dinosaurs": "恐龙", "space": "太空", "nature": "自然", "weather": "天气", "body": "身体",
    "science": "科学", "plants": "植物", "cartoons_stories": "动画和故事", "people": "人物", "places": "地方",
    "history": "历史", "food": "食物", "vehicles": "交通工具", "math": "算数", "riddle": "谜语", "time": "时间",
    "story": "讲故事", "memory": "收藏和兴趣", "chat": "聊天", "other": "其他", "safety": "安全提醒",
}
FOLLOW = {"simpler": "再简单一点", "example": "举个例子", "how_know": "你怎么知道的", "more": "再讲一点", "correction": "纠正小伙伴"}
END = {"goodbye": "说再见", "end_button": "自己按结束", "wrap_up": "到时间自然收尾", "bedtime": "睡前故事讲完",
       "disconnect": "直接离开", "skin_change": "换角色", "stale": "长时间无动静"}


def week_bounds(week: str) -> tuple[float, float]:
    year, w = week.split("-W")
    start = dt.datetime.fromisocalendar(int(year), int(w), 1)
    return start.timestamp(), (start + dt.timedelta(days=7)).timestamp()


def this_week(now=None) -> str:
    return time.strftime("%G-W%V", time.localtime(now or time.time()))


def clean(lines: list[str]) -> list[str]:
    return [line for line in lines if not EVALUATIVE.search(line)]


def collect(store: Store, week: str) -> dict:
    start, end = week_bounds(week)
    turns = [dict(zip(("ts", "lang", "question", "topic", "follow_up", "looked_up", "source"), r)) for r in store.db.execute(
        "SELECT ts, lang, question, topic, follow_up, looked_up, source FROM turns WHERE ts >= ? AND ts < ? ORDER BY ts",
        (start, end))]
    sessions = [dict(zip(("start_ts", "end_ts", "end_reason", "turns"), r)) for r in store.db.execute(
        "SELECT start_ts, end_ts, end_reason, turns FROM sessions WHERE start_ts >= ? AND start_ts < ?", (start, end))]
    unanswered = [r[0] for r in store.db.execute(
        "SELECT question FROM unanswered WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end))]
    found = [d for d in store.discoveries() if start <= d["ts"] < end]
    return {"turns": turns, "sessions": sessions, "unanswered": unanswered, "discoveries": found}


def build(data: dict, week: str, ideas: list[str] | None = None) -> str:
    turns, sessions = data["turns"], data["sessions"]
    lines = [f"# 本周发现 {week}", ""]
    if not turns:
        return "\n".join(lines + ["这一周没有记录。", ""])
    # Not in a report read with the child: fillers and lone words, safety turns, and anything in the parent-only notes
    asked = [t for t in turns if t["question"] and t["topic"] not in ("memory", "safety")
             and kind(t["question"]) == "ok" and not concerns(t["question"])]
    lines += ["## 这周问过的问题", ""] + [f"- {time.strftime('%m-%d', time.localtime(t['ts']))} {t['question']}" for t in asked] + [""]
    if data["discoveries"]:
        lines += ["## 收藏的发现", ""]
        lines += [f"- {d['question']}:{d['answer']}" for d in data["discoveries"]] + [""]
    counts: dict[str, int] = {}
    for t in asked:
        counts[t["topic"] or "other"] = counts.get(t["topic"] or "other", 0) + 1
    lines += ["## 话题", ""] + [f"- {TOPIC_ZH.get(k, k)}:{n}" for k, n in sorted(counts.items(), key=lambda x: -x[1])] + [""]
    if data["unanswered"]:
        lines += ["## 没查到资料的问题(可以一起查一查)", ""] + [f"- {q}" for q in data["unanswered"]] + [""]
    qs = [t["question"] for t in asked]
    follow = {}
    for t in asked:
        if t["follow_up"]:
            follow[t["follow_up"]] = follow.get(t["follow_up"], 0) + 1
    zh = sum(t["lang"] == "zh" for t in asked)
    ends = {}
    for s in sessions:
        if s["end_reason"]:
            ends[s["end_reason"]] = ends.get(s["end_reason"], 0) + 1
    durations = [(s["end_ts"] - s["start_ts"]) / 60 for s in sessions if s["end_ts"]]
    stories = [t["question"] for t in asked if t["topic"] == "story"]
    lines += ["## 互动里的事实", ""]
    lines += [f"- 问题 {len(qs)} 个:\"为什么\" {sum(bool(WHY.search(q)) for q in qs)} 个,\"怎么\" {sum(bool(HOW.search(q)) for q in qs)} 个,"
              f"\"是什么/是谁\" {sum(bool(WHAT.search(q)) for q in qs)} 个"]
    if follow:
        lines.append("- 接着问:" + ",".join(f"{FOLLOW.get(k, k)} {n} 次" for k, n in follow.items()))
    lines.append(f"- 探索 {len(sessions)} 次" + (f",每次 {min(durations):.0f} 到 {max(durations):.0f} 分钟" if durations else ""))
    if ends:
        lines.append("- 怎么结束的:" + ",".join(f"{END.get(k, k)} {n} 次" for k, n in ends.items()))
    lines.append(f"- 中文提问 {zh} 个,英文提问 {len(asked) - zh} 个")
    lines.append(f"- 收藏 {len(data['discoveries'])} 条")
    if stories:
        lines.append("- 她给故事定的主角和地方:" + ";".join(stories))
    lines.append("")
    if ideas:
        lines += ["## 可以一起做的小活动", ""] + [f"- {i}" for i in ideas] + [""]
    return "\n".join(clean(lines))


def activity_ideas(counts_text: str) -> list[str]:
    """Two or three parent-child activities from the local model, checked by the word list."""
    from curiosity_pet.llm import PetUnavailable, stream_chat

    prompt = (f"这周一个 7 岁孩子问到的话题:{counts_text}。请给家长两三个周末可以和孩子一起做的小活动,"
              "每个一句话,只写活动本身,不要评价孩子,不要形容孩子的性格或能力。每行一个,不要编号。")
    try:
        text = "".join(stream_chat([{"role": "user", "content": prompt}]))
    except PetUnavailable:
        return []
    ideas = [re.sub(r"^[\s\-*•\d.、)]+", "", line).strip() for line in text.splitlines()]
    return clean([i for i in ideas if 4 <= len(i) <= 80])[:3]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Curiosity Pet: weekly discovery report (facts only)")
    ap.add_argument("--week", help="ISO week like 2026-W43 (default: this week)")
    ap.add_argument("--db", help="database path")
    ap.add_argument("--no-ideas", action="store_true", help="skip the activity ideas (no model call)")
    ap.add_argument("--delete", metavar="WEEK", help="delete that week's saved report")
    args = ap.parse_args(argv)
    out_dir = config.DATA_DIR / "reports"
    if args.delete:
        (out_dir / f"{args.delete}.md").unlink(missing_ok=True)
        print(f"已删除 {args.delete} 的周报。")
        return
    if config.load_settings().get("weekly_report", True) is False:
        print("周报已在 settings.json 里关闭(\"weekly_report\": false)。")
        return
    week = args.week or this_week()
    data = collect(Store(args.db), week)
    ideas = None
    if not args.no_ideas and data["turns"]:
        counts = {}
        for t in data["turns"]:
            counts[TOPIC_ZH.get(t["topic"], t["topic"])] = counts.get(TOPIC_ZH.get(t["topic"], t["topic"]), 0) + 1
        ideas = activity_ideas("、".join(f"{k}{n}次" for k, n in counts.items()))
    text = build(data, week, ideas)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = Path(out_dir / f"{week}.md")
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"(已保存到 {path})")


if __name__ == "__main__":
    main()
