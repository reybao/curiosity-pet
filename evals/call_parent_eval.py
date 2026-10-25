"""The call-a-parent judge against the real local model: does it find requests by meaning, and say none to look-alikes?

Every sentence goes through CallParent's own recognition (fixed phrases first, then the pre-filter, then the judge),
so the result is what the pet would do. Nothing is sent: no Telegram call is made. Sentences are made up, not the
child's. Most are held out, not among the examples in the judge prompt.
A false positive costs one question ("要我告诉爸爸吗?"), never a message, but it should still be rare.

Usage: uv run python evals/call_parent_eval.py [--model pet-chat-9b] [--out evals/results/<date>-call-parent.md]
"""

import argparse
import time

from curiosity_pet import call_parent, config

# (sentence, expected target or "none")
CASES = [
    # requests, by meaning
    ("我想找爸爸", "dad"), ("爸爸在哪儿", "dad"), ("爸爸在哪里呀?", "dad"), ("我要妈妈", "mom"),
    ("让妈妈来一下", "mom"), ("我想爸爸了", "dad"), ("妈妈快来!", "mom"), ("妈妈你在哪", "mom"),
    ("我要爸爸妈妈", "both"), ("你们快来看", "both"), ("爸爸妈妈快过来", "both"), ("我想让妈妈陪我", "mom"),
    ("tell mommy I'm hungry", "mom"), ("where's daddy", "dad"), ("Where is my mom?", "mom"),
    ("I want my mom and dad", "both"), ("I need daddy", "dad"), ("Can mommy come here?", "mom"),
    ("I miss my dad", "dad"), ("get my parents please", "both"), ("I want my daddy", "dad"),
    ("where's mommy", "mom"), ("我想 mommy 了", "mom"), ("daddy 在哪里?", "dad"), ("Mommy, come here!", "mom"),
    # look-alikes: about a parent, not a request
    ("我爸爸是医生", "none"), ("妈妈说我可以看电视", "none"), ("爸爸的生日是几号?", "none"),
    ("讲一个熊爸爸和熊妈妈的故事", "none"), ("小蝌蚪找妈妈是什么故事?", "none"), ("为什么爸爸有胡子?", "none"),
    ("我妈妈做的饭很好吃", "none"), ("袋鼠妈妈怎么带宝宝?", "none"), ("不要告诉妈妈", "none"),
    ("我和爸爸昨天去了动物园", "none"), ("妈妈的妈妈叫什么?", "none"), ("爸爸妈妈是怎么认识的?", "none"),
    ("My dad is tall", "none"), ("Why do daddies have beards?", "none"), ("My mom says I can have a cookie", "none"),
    ("Tell me a story about a baby bear and his mommy", "none"), ("Do penguin dads keep the eggs warm?", "none"),
    ("Don't tell mom", "none"), ("What's a mother hen?", "none"), ("Mom and dad went shopping", "none"),
    ("my dad is a doctor", "none"), ("mom said I can watch TV", "none"), ("what's daddy's birthday?", "none"),
    ("我的 daddy 会修车", "none"), ("Peppa's daddy pig is funny", "none"),
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=config.HELPER_MODEL)
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    def judge(text, lang):
        return call_parent.judge_with_model(text, lang, model=args.model)

    rows, times = [], []
    for text, want in CASES:
        req = call_parent.detect(text)
        if req is None and call_parent.mentions_parent(text):
            t0 = time.perf_counter()
            got = judge(text, "en" if text.isascii() else "zh")
            times.append(time.perf_counter() - t0)
            how = "judge"
        else:
            got = req.parent if req else "none"
            how = "fixed" if req else "prefilter"
        rows.append((text, want, got, how))
        print(f"{'ok ' if got == want else 'BAD'} {how:9} want={want:4} got={got:4} {text}")

    pos = [r for r in rows if r[1] != "none"]
    neg = [r for r in rows if r[1] == "none"]
    found = sum(r[2] == r[1] for r in pos)
    false_pos = sum(r[2] != "none" for r in neg)
    wrong_target = sum(r[2] not in ("none", r[1]) for r in pos)
    times.sort()
    summary = [
        f"model {args.model}: requests found {found}/{len(pos)} (wrong target {wrong_target}), "
        f"look-alikes asked about {false_pos}/{len(neg)}",
        f"judge calls {len(times)}, median {times[len(times) // 2]:.2f} s, max {times[-1]:.2f} s" if times else "no judge calls",
    ]
    print("\n".join(summary))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(f"# Call-a-parent judge ({time.strftime('%Y-%m-%d')})\n\n" + "\n\n".join(summary) + "\n\n")
            f.write("| sentence | expected | got | path |\n|---|---|---|---|\n")
            for text, want, got, how in rows:
                f.write(f"| {text} | {want} | {got}{'' if got == want else ' ✗'} | {how} |\n")


if __name__ == "__main__":
    main()
