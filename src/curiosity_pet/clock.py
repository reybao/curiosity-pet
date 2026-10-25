"""Date and time questions are answered from the Mac's clock, not by the model.

The parent's example: "今天星期几" was answered "Wednesday" by the model, which has no clock.
Direct questions (what day / date / time is it, what about tomorrow or yesterday) get a fixed answer;
other questions that mention time words get a short date note in the prompt so the model can reason
about "next week" or "how many days until" without guessing today's date.
"""

import datetime as dt
import re

WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]
WEEKDAY_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

DAY_WORDS = re.compile(r"今天|明天|昨天|后天|前天|星期|礼拜|周几|几号|日期|几月|几点|现在.*时间|什么时候|"
                       r"\b(today|tomorrow|yesterday|date|day of the week|what day|what time|time is it|o'?clock|days?|weeks?|month|year)\b", re.I)
ASK_WEEKDAY = re.compile(r"(今天|明天|昨天|后天|前天)?.*(星期几|礼拜几|周几)|what day (is it|is today|is tomorrow|was yesterday)|day of the week", re.I)
ASK_DATE = re.compile(r"(今天|明天|昨天|后天|前天)?.*(几号|几月几|日期|什么日子)|what('?s| is) (the date|today'?s date)|which day of the month", re.I)
ASK_TIME = re.compile(r"现在.*几点|几点了|什么时间|现在是什么时候|what time is it|what'?s the time|current time|\btime now\b", re.I)
ASK_YEAR = re.compile(r"今年.*(哪一年|几几年|什么年)|which year|what year is it|what'?s the year", re.I)
OFFSETS = {"今天": 0, "明天": 1, "后天": 2, "昨天": -1, "前天": -2, "today": 0, "tomorrow": 1, "yesterday": -1}


def _offset(text: str) -> int:
    for word, off in OFFSETS.items():
        if re.search(word, text, re.I):
            return off
    return 0


def zh_num(n: int) -> str:
    digits = "零一二三四五六七八九"
    if n < 10:
        return digits[n]
    if n < 20:
        return "十" + ("" if n == 10 else digits[n % 10])
    return digits[n // 10] + "十" + ("" if n % 10 == 0 else digits[n % 10])


def date_sentence(day: dt.date, lang: str, offset: int = 0) -> str:
    w = day.weekday()
    if lang == "zh":
        label = {0: "今天", 1: "明天", 2: "后天", -1: "昨天", -2: "前天"}[offset]
        year = "".join("零一二三四五六七八九"[int(c)] for c in str(day.year))
        return f"{label}是{year}年{zh_num(day.month)}月{zh_num(day.day)}日,星期{WEEKDAY_ZH[w]}。"
    label = {0: "Today is", 1: "Tomorrow is", 2: "The day after tomorrow is", -1: "Yesterday was", -2: "The day before yesterday was"}[offset]
    return f"{label} {WEEKDAY_EN[w]}, {MONTH_EN[day.month - 1]} {day.day}, {day.year}."


def time_sentence(now: dt.datetime, lang: str) -> str:
    h, m = now.hour, now.minute
    if lang == "zh":
        part = "早上" if 5 <= h < 9 else "上午" if h < 12 else "中午" if h < 13 else "下午" if h < 18 else "晚上" if h < 23 else "深夜"
        h12 = h % 12 or 12
        minutes = "整" if m == 0 else "半" if m == 30 else f"{zh_num(m)}分"
        return f"现在是{part}{zh_num(h12)}点{minutes}。"
    part = "in the morning" if h < 12 else "in the afternoon" if h < 18 else "in the evening"
    h12 = h % 12 or 12
    return f"It's {h12}:{m:02d} {part}."


def answer(text: str, lang: str, now: dt.datetime | None = None) -> str | None:
    """A fixed answer for a direct date or time question, else None."""
    now = now or dt.datetime.now()
    if ASK_TIME.search(text):
        return time_sentence(now, lang)
    if ASK_WEEKDAY.search(text) or ASK_DATE.search(text):
        off = _offset(text)
        return date_sentence(now.date() + dt.timedelta(days=off), lang, off)
    if ASK_YEAR.search(text):
        return date_sentence(now.date(), lang)
    return None


def mentions_time(text: str) -> bool:
    return bool(DAY_WORDS.search(text))


def date_note(lang: str, now: dt.datetime | None = None) -> str:
    """Short note for the prompt when the question mentions days or dates."""
    now = now or dt.datetime.now()
    d = now.date()
    if lang == "zh":
        return f"(今天是{d.year}年{d.month}月{d.day}日,星期{WEEKDAY_ZH[d.weekday()]})"
    return f"(Today is {WEEKDAY_EN[d.weekday()]}, {MONTH_EN[d.month - 1]} {d.day}, {d.year})"
