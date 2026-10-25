"""Local library ranking check: typical rewritten queries and the article the pet should use (first result).

Runs against the built library (DATA_DIR/library/library.db), no model and no network.
"-" as the expected title means the library should return nothing, so the lookup goes online.
Usage: uv run python evals/library_eval.py
"""

import time

from curiosity_pet.library import Library

CASES = [
    ("彩虹", "zh", "彩虹"), ("七龙珠 孙悟空", "zh", "孙悟空 (七龙珠)"), ("春节 放鞭炮", "zh", "春节"),
    ("长颈鹿 脖子", "zh", "长颈鹿"), ("小猫 打呼噜", "zh", "猫"), ("星星 眨眼", "zh", "-"), ("黑洞", "zh", "黑洞"),
    ("斑马 条纹", "zh", "斑马"), ("皮卡丘", "zh", "皮卡丘"), ("长城", "zh", "长城"), ("中秋节 月饼", "zh", "中秋节"),
    ("熊猫 竹子", "zh", "大熊猫"), ("月亮 白天", "zh", "月球"), ("恐龙 灭绝", "zh", "白垩纪—古近纪灭绝事件"),
    ("zebras stripes", "en", "Zebra"), ("bees make honey", "en", "Honey bee"), ("Goku Dragon Ball", "en", "Goku"),
    ("volcano erupt", "en", "Volcano"), ("cats purr", "en", "Cat"), ("sky blue", "en", "Sky"), ("black hole", "en", "Black hole"),
    ("birds fly", "en", "Bird"), ("dinosaurs extinct", "en", "Dinosaur"), ("Pikachu", "en", "Pikachu"),
    ("Great Wall China", "en", "Great Wall of China"), ("photosynthesis", "en", "Photosynthesis"),
    # Extra child-level sources (library_sources.py)
    ("守株待兔", "zh", "守株待兔"), ("画蛇添足", "zh", "画蛇添足"), ("床前明月光", "zh", "静夜思"), ("春眠不觉晓", "zh", "春晓"),
    ("人之初", "zh", "三字经(第1段)"), ("海滩上的沙子", "zh", "海滩上的沙子"), ("白日依山尽", "zh", "登鹳雀楼"),
    ("Belling the Cat", "en", "Belling the Cat (The Aesop for Children)"), ("tortoise hare", "en", "The Tortoise and the Hare"),
    ("camel hump", "en", "Camel"), ("how the camel got his hump", "en", "How the Camel Got his Hump (Just So Stories)"), ("Peter Rabbit", "en", "Peter Rabbit"), ("Tale of Peter Rabbit", "en", "The Tale of Peter Rabbit"),
    ("Hey diddle diddle", "en", "Hey Diddle Diddle"), ("cat fiddle cow moon", "en", "The Cat and the Fiddle (The Real Mother Goose)"), ("Snow Queen", "en", "The Snow Queen (Andersen's Fairy Tales)"),
    ("purr meaning", "en", "purr"),
    # School poems (data/school_poems.json)
    ("锄禾日当午", "zh", "悯农"), ("春种一粒粟", "zh", "悯农"), ("鹅鹅鹅", "zh", "咏鹅"), ("曲项向天歌", "zh", "咏鹅"),
    ("小荷才露尖尖角", "zh", "小池"), ("咬定青山不放松", "zh", "竹石"), ("草长莺飞二月天", "zh", "村居"), ("敕勒川", "zh", "敕勒歌"),
    ("李白 赠汪伦", "zh", "赠汪伦"), ("游子吟", "zh", "游子吟"),
]


def main():
    lib = Library()
    if not lib.available():
        raise SystemExit("No library.db: run `uv run pet-library build` first")
    ok, times = 0, []
    print("| Query | Expected | First result | OK |\n|---|---|---|---|")
    for q, lang, expect in CASES:
        t0 = time.perf_counter()
        results = lib.search(q, lang)
        times.append((time.perf_counter() - t0) * 1000)
        got = results[0].title if results else "-"
        ok += got == expect
        print(f"| {q} | {expect} | {got} | {'yes' if got == expect else 'NO'} |")
    times.sort()
    print(f"\n{ok}/{len(CASES)} as expected; search time median {times[len(times) // 2]:.1f} ms, max {times[-1]:.1f} ms")
    print(lib.info())


if __name__ == "__main__":
    main()
