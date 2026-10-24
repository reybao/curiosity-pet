"""隐私关卡:能发去维基百科的只有中性话题词。

孩子原话里的个人信息、家庭信息、心情、敏感话题,一个都不能出现在发出的搜索词里。
这里测程序规则(第二道关);模型改写(第一道关)的泄漏率在 evals/privacy_eval.py 里实测。
"""

import pytest

from curiosity_pet.privacy import check_query, looks_like_knowledge_question, original_is_sensitive

# ---------- 粗筛:像不像知识提问 ----------


@pytest.mark.parametrize(
    "text",
    [
        "七龙珠里的孙悟空是谁?",
        "为什么天空是蓝色的?",
        "恐龙是怎么灭绝的?",
        "火山为什么会喷发",
        "Who is Goku in Dragon Ball?",
        "Why do cats purr?",
        "How big is the sun?",
        "What is a black hole?",
    ],
)
def test_knowledge_questions_pass_prefilter(text):
    assert looks_like_knowledge_question(text)


@pytest.mark.parametrize(
    "text",
    [
        "我今天好难过",
        "我讨厌弟弟",
        "你好呀",
        "讲个故事吧",
        "再简单一点",
        "I am sad today",
        "Tell me a story",
        "我们家的狗叫什么名字?",  # 关于自己家,不是一般知识
        "我妈妈几点下班?",
        "What is my teacher's name?",
    ],
)
def test_personal_or_chat_fails_prefilter(text):
    assert not looks_like_knowledge_question(text)


# ---------- 第二道关:检查改写后的搜索词 ----------


@pytest.mark.parametrize(
    "query",
    ["七龙珠 孙悟空", "瑞利散射", "恐龙 灭绝", "Goku Dragon Ball", "black hole", "火山 喷发 原因"],
)
def test_clean_topic_queries_are_allowed(query):
    ok, reason = check_query(query)
    assert ok, reason


@pytest.mark.parametrize(
    "query, why",
    [
        ("我 七龙珠", "第一人称"),
        ("我家 小狗", "第一人称"),
        ("my dog breed", "第一人称"),
        ("我们 学校 运动会", "第一人称"),
        ("妈妈 工作", "家人"),
        ("弟弟 生日", "家人"),
        ("grandma hospital", "家人"),
        ("teacher name", "家人"),
        ("阳光小学", "学校"),
        ("Lincoln Elementary School", "学校"),
        ("幸福路 23 号", "地址"),
        ("Main Street address", "地址"),
        ("13812345678", "数字"),
        ("电话 5551234", "数字"),
        ("难过 怎么办", "情绪"),
        ("feel lonely", "情绪"),
        ("讨厌 弟弟", "情绪"),
        ("秘密", "秘密"),
        ("怎么 自杀", "敏感"),
        ("人 死了 会去哪", "敏感"),
        ("war deaths", "敏感"),
        ("someone@example.com", "联系方式"),
        ("", "空"),
        ("七龙珠 孙悟空 赛亚人 龟仙人 天下第一武道会 比克 贝吉塔 弗利萨 魔人布欧", "太长"),
    ],
)
def test_personal_queries_are_blocked(query, why):
    ok, reason = check_query(query)
    assert not ok, f"{why}: {query!r} 不应放行"


def test_family_names_from_settings_are_blocked():
    # 家长可在设置里填家人和孩子的名字、小名
    assert not check_query("小米 恐龙", family_terms=["小米"])[0]
    assert check_query("恐龙", family_terms=["小米"])[0]


def test_parent_blacklist_is_blocked():
    assert not check_query("某游戏", blacklist=["某游戏"])[0]


# ---------- 原话涉及敏感话题时整句不联网 ----------


@pytest.mark.parametrize(
    "text",
    ["人死了会去哪里?", "为什么会打仗?", "地震会把房子震倒吗", "Why do people die?", "What happens in a war?"],
)
def test_sensitive_originals_never_go_online(text):
    assert original_is_sensitive(text)


@pytest.mark.parametrize("text", ["七龙珠里的孙悟空是谁?", "恐龙为什么灭绝?", "Why is the sky blue?"])
def test_normal_originals_are_not_sensitive(text):
    assert not original_is_sensitive(text)


# ---------- 只删不加:落地检查与处境词 ----------

from curiosity_pet.privacy import ground_and_scrub  # noqa: E402


def test_words_not_in_original_are_dropped():
    # 实测:模型把示例里的"七龙珠"加进了"小美说孙悟空会飞"
    assert ground_and_scrub("七龙珠 孙悟空", "小美说孙悟空会飞,是真的吗?") == "孙悟空"


def test_time_and_place_context_is_dropped():
    # 实测泄漏:"昨天在公园看到的蘑菇能吃吗" -> "公园 蘑菇 食用"
    assert ground_and_scrub("公园 蘑菇 食用", "昨天在公园看到的蘑菇能吃吗?") == "蘑菇"


def test_grounded_queries_are_kept():
    assert ground_and_scrub("七龙珠 孙悟空", "七龙珠里的孙悟空是谁?") == "七龙珠 孙悟空"
    assert ground_and_scrub("天空 蓝色", "为什么天空是蓝色的?") == "天空 蓝色"
    assert ground_and_scrub("bees honey making", "How do bees make honey?") == "bees honey making"
    assert ground_and_scrub("penguins flying", "Why can't penguins fly?") == "penguins flying"


def test_mixed_language_allows_translation():
    assert ground_and_scrub("恐龙 灭绝", "为什么 dinosaurs 会 extinct?") == "恐龙 灭绝"


def test_scrub_only_removes_never_adds():
    q = "猫 打呼噜"
    assert set(ground_and_scrub(q, "小猫为什么会打呼噜?").split()) <= set(q.split())
