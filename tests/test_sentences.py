"""流式断句:模型逐块吐字,每凑够一句就送 TTS;过短的第一句与第二句合并。"""

from curiosity_pet.sentences import SentenceSplitter


def feed_all(pieces, **kwargs):
    sp = SentenceSplitter(**kwargs)
    out = []
    for p in pieces:
        out.extend(sp.feed(p))
    out.extend(sp.flush())
    return out


def test_chinese_sentences_split_on_punctuation():
    pieces = ["月亮自己", "不会发光。", "它反射太阳", "的光!你看", "到了吗?"]
    assert feed_all(pieces, merge_short_first=False) == [
        "月亮自己不会发光。",
        "它反射太阳的光!",
        "你看到了吗?",
    ]


def test_english_sentences_split_on_punctuation_and_space():
    pieces = ["The sky ", "is blue. Light ", "bounces around! ", "Cool?"]
    assert feed_all(pieces, merge_short_first=False) == [
        "The sky is blue.",
        "Light bounces around!",
        "Cool?",
    ]


def test_decimal_point_is_not_sentence_end():
    pieces = ["The moon is 3.5 ", "times smaller. Wow."]
    assert feed_all(pieces, merge_short_first=False) == [
        "The moon is 3.5 times smaller.",
        "Wow.",
    ]


def test_short_first_sentence_is_merged_with_second():
    # "嗯!" 太短,Kokoro 念短句效果差,与下一句合并
    pieces = ["嗯!", "月亮不会自己发光。", "它反射太阳光。"]
    assert feed_all(pieces) == ["嗯!月亮不会自己发光。", "它反射太阳光。"]


def test_long_first_sentence_is_not_merged():
    pieces = ["月亮自己其实不会发光哦。", "它反射太阳光。"]
    assert feed_all(pieces) == ["月亮自己其实不会发光哦。", "它反射太阳光。"]


def test_flush_returns_unfinished_tail():
    assert feed_all(["没有标点的结尾"], merge_short_first=False) == ["没有标点的结尾"]


def test_first_chunk_may_cut_at_comma_when_long_enough():
    # 合成和生成抢 GPU,第一块越短越早开口;只对第一块生效,后面仍按句号断
    pieces = ["月亮自己不会发光,", "它是反射太阳的光,", "所以白天也能看到。", "你看,", "到了吗?"]
    assert feed_all(pieces) == [
        "月亮自己不会发光,",
        "它是反射太阳的光,所以白天也能看到。",
        "你看,到了吗?",
    ]


def test_first_chunk_does_not_cut_at_short_comma():
    pieces = ["好的,", "月亮自己不会发光。"]
    assert feed_all(pieces) == ["好的,月亮自己不会发光。"]


def test_english_first_chunk_cuts_at_comma():
    pieces = ["When sunlight comes in, ", "it bounces around. ", "Cool."]
    assert feed_all(pieces) == ["When sunlight comes in,", "it bounces around.", "Cool."]


def test_full_width_punctuation_from_model():
    # 模型实际输出全角标点;源码里用转义写,防止被编辑器换成半角
    pieces = ["月亮自己不会发光，", "它反射太阳的光！", "你看到了吗？"]
    assert feed_all(pieces) == [
        "月亮自己不会发光，",
        "它反射太阳的光！",
        "你看到了吗？",
    ]


def test_english_first_chunk_cuts_before_conjunction():
    pieces = ["Cats make a special sound called a purr ", "when they are happy. ", "It is cute."]
    assert feed_all(pieces) == [
        "Cats make a special sound called a purr",
        "when they are happy.",
        "It is cute.",
    ]


def test_conjunction_cut_needs_enough_words():
    # 连词前只有 2 个词,不在 "when" 前断
    pieces = ["Cats purr when happy. ", "Cute."]
    assert feed_all(pieces) == ["Cats purr when happy.", "Cute."]


def test_only_first_sentence_is_merged():
    pieces = ["好!", "一。", "二。", "三。"]
    assert feed_all(pieces) == ["好!一。", "二。", "三。"]
