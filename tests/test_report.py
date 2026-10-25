"""Weekly discovery report: facts and counts only, no evaluative words, nothing from the parent-only notes."""

import time

from curiosity_pet import report
from curiosity_pet.report import build, clean, collect, week_bounds
from curiosity_pet.store import Store


def test_word_list_drops_lines_that_describe_the_child():
    lines = ["- 问题 12 个", "她是一个好奇心强的孩子", "She is very curious.", "越来越喜欢太空了", "- 太空:3"]
    assert clean(lines) == ["- 问题 12 个", "- 太空:3"]


def test_report_has_facts_and_leaves_out_noise_and_worries(tmp_path):
    store = Store(tmp_path / "pet.db")
    start, _ = week_bounds("2026-W43")
    now = start + 3600
    sid = store.start_session("ipad", now=now)
    for q, topic, follow in [("为什么天空是蓝色的?", "science", None), ("再简单一点", "science", "simpler"),
                             ("Ha ha ha!", "other", None), ("我想打我弟弟", "safety", None),
                             ("我今天被欺负了", "other", None), ("讲一个小兔子在森林里的故事", "story", None)]:
        store.record_turn(sid, lang="zh", question=q, answer="a", topic=topic, follow_up=follow, looked_up=False,
                          source=None, asr_s=0.1, first_audio_s=1.0, total_s=2.0, unavailable=False, now=now)
    store.end_session(sid, "wrap_up", now=now + 600)
    store.add_discovery("zh", "为什么天空是蓝色的?", "因为阳光里的蓝光被散开了。", now=now)
    text = build(collect(store, "2026-W43"), "2026-W43", ideas=["一起去看日落,数一数天空有几种颜色。", "她真聪明,多夸夸她。"])
    assert "为什么天空是蓝色的?" in text and "收藏 1 条" in text and "\"为什么\" 1 个" in text
    assert "再简单一点 1 次" in text and "到时间自然收尾 1 次" in text and "小兔子在森林里" in text
    assert "Ha ha ha" not in text and "我想打我弟弟" not in text and "被欺负" not in text
    assert "一起去看日落" in text and "聪明" not in text


def test_turned_off_and_delete(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(report.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(report.config, "load_settings", lambda *a: {"weekly_report": False})
    report.main(["--db", str(tmp_path / "pet.db"), "--no-ideas"])
    assert "关闭" in capsys.readouterr().out
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "2026-W40.md").write_text("x")
    report.main(["--delete", "2026-W40"])
    assert not (tmp_path / "reports" / "2026-W40.md").exists()
