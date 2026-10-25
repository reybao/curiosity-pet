"""Parent view of the usage log: `uv run pet-log [--days 7]`.

Prints facts only: time, duration, questions, topics, follow-up types, whether material was looked up, timing for each exploration, plus counts.
Answer text is deleted after 7 days, so it only shows within 7 days. No evaluation of any kind.
"""

import argparse
import time

from curiosity_pet.store import Store

FOLLOW_UP_NAMES = {
    "simpler": "再简单一点", "example": "举个例子", "how_know": "你怎么知道的",
    "correction": "纠正宠物", "more": "再讲一点",
}
END_NAMES = {"goodbye": "说再见", "end_button": "按结束", "disconnect": "直接离开", "end": "结束", "wrap_up": "自然收尾",
             "skin_change": "换角色", "stale": "长时间无动静"}


def fmt_time(ts):
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


def show_notes(store):
    """What the child said that a parent may want to know about: her own words, time and a plain category, nothing more."""
    from curiosity_pet.concern import NAMES, NOTE_RETENTION_DAYS

    notes = store.notes(days=NOTE_RETENTION_DAYS)
    if not notes:
        return
    print(f"== 需要留意的话(最近 {NOTE_RETENTION_DAYS} 天,{len(notes)} 条;原话照录,不做判断;删除:pet-log --clear-notes)")
    for n in notes:
        cats = "、".join(NAMES.get(c, c) for c in n["categories"])
        print(f"  {fmt_time(n['ts'])}  [{cats}]  {n['said']}")


def show_memory(store):
    """Interest cards and saved discoveries: what the child chose to keep."""
    from curiosity_pet.memory import INTERESTS

    liked = store.interests()
    if liked:
        print("== 兴趣卡片(她自己说的;删除:pet-log --forget-interest 名称)")
        print("  " + "  ".join(f"{INTERESTS[t][0]}({t})" for t in liked if t in INTERESTS))
    found = store.discoveries()
    if found:
        print(f"== 我的发现({len(found)} 条;删除:pet-log --delete-discovery 编号)")
        for d in found:
            print(f"  #{d['id']} {fmt_time(d['ts'])}  {d['question']}\n         {d['answer']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Curiosity Pet: usage log (facts only, no evaluation)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--db", help="database path, default PET_DATA_DIR/pet.db")
    ap.add_argument("--answers", action="store_true", help="also show answer text (only available within 7 days)")
    ap.add_argument("--clear-notes", action="store_true", help="delete all 'worth knowing' notes")
    ap.add_argument("--forget-interest", metavar="TOPIC", help="remove one interest card (e.g. dinosaurs)")
    ap.add_argument("--delete-discovery", type=int, metavar="ID", help="delete one saved discovery")
    args = ap.parse_args(argv)

    store = Store(args.db)
    if args.clear_notes:
        store.clear_notes()
        print("已删除全部需要留意的记录。")
        return
    if args.forget_interest:
        store.remove_interest(args.forget_interest)
        print(f"已删除兴趣卡片:{args.forget_interest}")
        return
    if args.delete_discovery:
        store.delete_discovery(args.delete_discovery)
        print(f"已删除发现 {args.delete_discovery}")
        return
    show_notes(store)
    show_memory(store)
    sessions = store.recent_sessions(days=args.days)
    if not sessions:
        print(f"最近 {args.days} 天没有记录。")
        return

    for s in sessions:
        dur = f"{(s['end_ts'] - s['start_ts']) / 60:.1f} 分钟" if s["end_ts"] else "未结束"
        end = END_NAMES.get(s["end_reason"], s["end_reason"] or "")
        print(f"\n== {fmt_time(s['start_ts'])}  {dur}  {s['turns']} 个问题  {end}")
        for t in s["turn_list"]:
            tags = [t["lang"], t["topic"]]
            if t["follow_up"]:
                tags.append(FOLLOW_UP_NAMES.get(t["follow_up"], t["follow_up"]))
            if t["looked_up"]:
                tags.append(f"查了资料:{t['source']}" if t["source"] else "查了资料,没找到")
            if t["unavailable"]:
                tags.append("模型不可用")
            fa = f"{t['first_audio_s']:.1f}s" if t["first_audio_s"] is not None else "-"
            print(f"  {time.strftime('%H:%M', time.localtime(t['ts']))}  {t['question']}  [{', '.join(tags)}]  开口 {fa}")
            if args.answers and t["answer"]:
                print(f"         小猫:{t['answer']}")

    unanswered = store.unanswered(days=args.days)
    if unanswered:
        print(f"\n== 没查到资料、小猫说是猜想的问题({len(unanswered)}),可以补进知识库:")
        for u in unanswered:
            print(f"  {time.strftime('%m-%d', time.localtime(u['ts']))}  {u['question']}  [{u['lang']}, {u['topic']}]")

    from curiosity_pet.call_parent import report_lines

    calls = report_lines(store.db, days=args.days)
    if calls:
        print("\n== 帮孩子给家长发的消息(Telegram):")
        print("\n".join(calls))

    st = store.stats(days=args.days)
    print(f"\n== 最近 {args.days} 天统计")
    print(f"探索 {st['sessions']} 次,问题 {st['questions']} 个")
    if st["median_session_s"] is not None:
        print(f"每次探索时长中位数 {st['median_session_s'] / 60:.1f} 分钟")
    print("每天问题数:" + ", ".join(f"{d} {n}" for d, n in sorted(st["by_day"].items())))
    print("语言:" + ", ".join(f"{k} {v}" for k, v in st["by_lang"].items()))
    print("主题:" + ", ".join(f"{k} {v}" for k, v in sorted(st["by_topic"].items(), key=lambda x: -x[1])))
    if st["follow_ups"]:
        print("追问:" + ", ".join(f"{FOLLOW_UP_NAMES.get(k, k)} {v}" for k, v in st["follow_ups"].items()))
    print(f"查了资料 {st['looked_up']} 次;结束方式:" + ", ".join(f"{END_NAMES.get(k, k)} {v}" for k, v in st["end_reasons"].items()))
    if st["median_first_audio_s"] is not None:
        print(f"说完到开口中位数 {st['median_first_audio_s']:.1f} 秒")


if __name__ == "__main__":
    main()
