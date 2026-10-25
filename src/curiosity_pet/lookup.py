"""Lookup: decide whether to look up, rewrite into topic terms, search the local library and then the web, record the terms.

Order (all decided locally; only if every step passes is anything searched):
  parent switch and contact info (or a local library) -> is the original sensitive -> rough screen for knowledge
  questions -> local model classifies and rewrites -> rule check of topic terms -> local library -> web search -> Wikipedia
The local library is searched with the same checked topic terms; it needs no contact info and also works with online
lookup switched off, in which case only the library is searched.
If any step fails nothing is searched and the pet answers as usual (if nothing is found, it says it is a guess).
"""

import json
import random
import re
import time
from dataclasses import dataclass

import httpx

from curiosity_pet import config, privacy, wiki
from curiosity_pet.llm import LOCAL_HOSTS, PetUnavailable

TOPICS = [
    "animals", "dinosaurs", "space", "nature", "weather", "body", "science", "plants",
    "cartoons_stories", "people", "places", "history", "food", "vehicles", "other",
]
KINDS = ["knowledge", "personal", "feelings", "sensitive", "chat"]

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "topic": {"type": "string", "enum": TOPICS},
        "query": {"type": "string"},
    },
    "required": ["kind", "topic", "query"],
}

REWRITE_SYSTEM = {
    "zh": (
        "把孩子的话分类并改写成查百科的中性关键词(中文,2 到 4 个词,空格分开)。只留知识话题,去掉关于自己、家人、"
        "朋友、学校、地点、时间、心情的词;不加原句没有的内容;保留作品名等限定词,如\"七龙珠里的孙悟空是谁\"->\"七龙珠 孙悟空\"。"
        "kind:knowledge=一般知识;personal=自己或家里的事;feelings=心情;sensitive=死亡战争灾难身体安全困扰;chat=闲聊指令。只输出 JSON。"
    ),
    "en": (
        "Classify the child's message and rewrite it as neutral encyclopedia keywords (English, 2 to 4 words). Keep only the "
        "knowledge topic; drop words about the asker, family, friends, school, places, times, feelings; add nothing; keep "
        "qualifiers such as a show's title, e.g. \"Who is Goku in Dragon Ball\" -> \"Goku Dragon Ball\". "
        "kind: knowledge=general knowledge; personal=about the asker or home; feelings=sharing feelings; "
        "sensitive=death, war, disaster, body safety, distress; chat=small talk or commands. Output JSON only."
    ),
}


def filler(lang: str, persona: dict | None = None) -> str:
    """Said right away when a lookup starts, so the child does not wait in silence."""
    sound = (persona or config.PERSONA)["sound"][lang]
    default = f"{sound},我去查一查!" if lang == "zh" else f"{sound.capitalize()}, let me look that up!"
    return default if persona is not None else config.phrase("filler", lang, default)


FILLER = {lang: filler(lang) for lang in ("zh", "en")}


@dataclass
class Decision:
    go: bool
    reason: str
    query: str = ""
    topic: str | None = None  # only set after the model classifies; blocked by the rough screen means none
    kind: str | None = None  # model classification (knowledge, personal, feelings, sensitive, chat)
    online: bool = True  # False: only local providers (the library) may be searched
    intent: str | None = None  # "definition": the child asks what a word means or how a character is written
    # The model's name for the likely answer ("蓝鲸" for "世界上最大的动物是什么?"). Looked up in the local library only,
    # never sent online; used when an entry has exactly this title and mentions a word of the query.
    answer: str = ""
    # The child's question, kept (locally) when its answer is one named thing; the answer-name call is made in
    # fetch, after the "let me look it up" filler has started, so the filler is not delayed
    answer_question: str = ""
    # A prepared result (an idiom story, a poem, an approved Q&A answer): fetch returns it without searching
    entry: object = None
    # Approved Q&A entries close to the question: the model picks among them in fetch, after the filler started
    qa_question: str = ""


def rewrite_with_model(question: str, lang: str, model=config.HELPER_MODEL, base_url=config.OLLAMA_URL) -> dict:
    """Local model: classify and rewrite. Calls only the local Ollama."""
    from urllib.parse import urlparse

    if urlparse(base_url).hostname not in LOCAL_HOSTS:
        raise ValueError(f"Only a local model service is allowed: {base_url}")
    # Plain JSON mode, not a JSON Schema: with schema-constrained decoding the 9B (llama.cpp) produced
    # unrelated words ("恐龙" for Dragon Ball's Goku, "汽车" for a purring cat). The keys and the topic list are
    # in the prompt instead, and the result is validated here.
    label = "孩子的话" if lang == "zh" else "Child's message"
    user = (
        f"{label}:{question}\n"
        f'Output JSON: {{"kind": one of {KINDS}, "topic": one of {TOPICS}, "query": "..."}}'
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": REWRITE_SYSTEM[lang]},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    try:
        r = httpx.post(f"{base_url}/api/chat", json=body, timeout=30)
        r.raise_for_status()
        data = json.loads(r.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
        raise PetUnavailable(str(e)) from e
    if not isinstance(data, dict):
        raise PetUnavailable("rewrite did not return an object")
    return {
        "kind": data.get("kind") if data.get("kind") in KINDS else "chat",
        "topic": data.get("topic") if data.get("topic") in TOPICS else "other",
        "query": str(data.get("query", "")),
    }


# Questions whose answer is one named thing ("世界上最大的动物是什么?" -> 蓝鲸), where the answer's name is not in the
# question, so keyword search cannot reach it. Only these get the extra model call below.
ANSWER_ASK = re.compile(
    r"最(?:大|小|高|矮|长|短|快|慢|老|早|重|轻|深|远|热|冷|多|少|厉害|聪明)|世界上|第一个|谁(?:发明|发现|造|写)|哪个国家|哪座|哪条|"
    r"\b(?:biggest|largest|smallest|tallest|highest|longest|shortest|fastest|slowest|oldest|heaviest|deepest|hottest|coldest)\b|"
    r"\bfirst (?:person|man|woman|animal)\b|\bwho (?:invented|discovered|built|wrote)\b|\bwhich (?:country|city|planet|animal)\b",
    re.IGNORECASE,
)
GUESS_PROMPT = {
    "zh": "孩子问:{q}\n如果这个问题的答案是一个具体的东西、人、地方或概念,写出它在百科全书里的条目名(中文,尽量短);"
          "如果答案不是一个具体的东西,写空字符串。只输出 JSON:{{\"answer\": \"...\"}}",
    "en": "A child asks: {q}\nIf the answer is one specific thing, person, place or idea, write its encyclopedia article "
          "title (English, short); otherwise an empty string. Output JSON only: {{\"answer\": \"...\"}}",
}


def guess_answer(question: str, lang: str, model=config.HELPER_MODEL, base_url=config.OLLAMA_URL) -> str:
    """Local model: the name of the likely answer, used only to look up the local library (never sent online).
    A separate call: putting this field into the rewrite call made the 9B return whole questions as search
    queries (14 of 36 queries spoiled) and fill the answer only 5 times in 36."""
    from urllib.parse import urlparse

    if urlparse(base_url).hostname not in LOCAL_HOSTS:
        raise ValueError(f"Only a local model service is allowed: {base_url}")
    body = {"model": model, "messages": [{"role": "user", "content": GUESS_PROMPT[lang].format(q=question)}],
            "stream": False, "think": False, "format": "json", "options": {"temperature": 0}}
    try:
        r = httpx.post(f"{base_url}/api/chat", json=body, timeout=30)
        r.raise_for_status()
        data = json.loads(r.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
        raise PetUnavailable(str(e)) from e
    return str(data.get("answer") or "").strip()[:40] if isinstance(data, dict) else ""


def _terms(query: str) -> list[str]:
    """Split the search term into words for the relevance check; long Chinese words without spaces are split into two-character groups."""
    terms = []
    for t in query.lower().split():
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", t):
            terms += [t[i : i + 2] for i in range(0, len(t) - 1, 2)]
        else:
            terms.append(t)
    return terms


def relevance(query: str, result) -> float:
    """Relevance: the share of search words found in the opening paragraph, with a bonus for words found in the title."""
    terms = _terms(query)
    if not terms:
        return 0.0
    title, text = result.title.lower(), result.text[:400].lower()
    hits = sum((t in title) + (t in text) for t in terms)
    return hits / (2 * len(terms))


def relevant(query: str, result) -> bool:
    """Search words appear in the entry title or opening paragraph: with up to two words all must appear, with three or more at least two thirds.

    Measured: searching "天空蓝色成因" returned "蓝色弹珠" (a photo of Earth), and "猫 打呼噜" returned the children's author 杨红樱 (which only contains "猫"); both must be discarded.
    """
    terms = _terms(query)
    if not terms:
        return False
    haystack = (result.title + " " + result.text[:400]).lower()
    hits = sum(t in haystack for t in terms)
    if len(terms) <= 2:
        return hits == len(terms)
    return hits * 3 >= len(terms) * 2


def pick_best(query: str, results):
    """Pick the most relevant of the first few search results. Measured: for "天空 蓝色" the top hit was a film titled 知道天空有多蓝的人啊."""
    if results is None:
        return None
    if not isinstance(results, list):
        results = [results]
    candidates = [r for r in results if relevant(query, r)]
    if not candidates:
        return None
    # On equal scores keep Wikipedia's original ranking (max returns the first maximum)
    return max(candidates, key=lambda r: relevance(query, r))


class Researcher:
    def __init__(
        self,
        store=None,
        enabled: bool = config.ONLINE_LOOKUP,
        contact: str = config.WIKI_CONTACT,
        rewrite=rewrite_with_model,
        guess=guess_answer,
        search=None,
        family_terms=tuple(config.FAMILY_TERMS),
        blacklist=tuple(config.BLACKLIST),
        providers=None,
        qa=None,
        qa_judge="model",
    ):
        """search: legacy callable (query, lang, contact=) returning results; providers: objects with
        .name and .search(query, lang), tried in order until something relevant turns up."""
        self.store = store
        self.enabled = enabled
        self.contact = contact
        self.rewrite = rewrite
        self.guess = guess  # (question, lang) -> answer name, or None to never guess
        self.search = search
        self.providers = providers
        self.family_terms = tuple(family_terms)
        self.blacklist = tuple(blacklist)
        self.qa_store = qa  # qa.QAStore; created on first use when a library is available
        if qa_judge == "model":
            from curiosity_pet.qa import judge_with_model

            qa_judge = judge_with_model
        self.qa_judge = qa_judge  # (question, candidates, lang) -> 1-based pick or 0; None: exact matches only
        self.last = None  # (result, kind, time): the entry used last, for "这首诗..." and "不是这个意思"
        self.recent: list[str] = []  # idioms and poems served lately, so "another one" is a different one

    LAST_FOR_S = 600

    def _library(self):
        return next((p.library for p in self._providers() if hasattr(p, "library")), None)

    def _qa(self):
        if self.qa_store is None and self._library() is not None:
            from curiosity_pet.qa import QAStore

            self.qa_store = QAStore()
        return self.qa_store

    def _fresh_last(self):
        return self.last if self.last and time.time() - self.last[2] < self.LAST_FOR_S else None

    def _pick(self, titles: list) -> str | None:
        fresh = [t for t in titles if t not in self.recent] or titles
        return random.choice(fresh) if fresh else None

    def library_entry(self, question: str, lang: str):
        """An idiom story, a poem, or the entry used last, answered from the library (see library.library_request)."""
        from curiosity_pet.library import POEM_THEMES, HOST, library_request
        from curiosity_pet.wiki import WikiResult

        lib = self._library()
        req = library_request(question, lang) if lib is not None else None
        if not req:
            return None
        kind, detail = req
        qa = self._qa()
        last = self._fresh_last()
        if kind == "again":
            if not last:
                return None
            title, last_kind = last[0].title, last[1]
            if last_kind == "idiom":
                return lib.idiom_entry(title, qa)
            if last_kind == "poem":
                return lib.poem_entry(title, qa, meaning=True)
            return last[0]
        if kind in ("idiom", "meaning", "idiom_meaning"):
            name = lib.find_idiom(question)
            if name:
                return lib.idiom_entry(name, qa)
            if kind == "idiom_meaning":
                return lib.idiom_entry(last[0].title, qa) if last and last[1] == "idiom" else None
            if kind == "idiom":
                if "成语" not in question:
                    return None  # "讲讲恐龙": an ordinary question
                name = self._pick(lib.story_idioms())
                return lib.idiom_entry(name, qa) if name else None
        if kind in ("poem_meaning", "meaning", "poem"):
            title = lib.find_poem(question)
            if title:
                return lib.poem_entry(title, qa, meaning=kind != "poem")
            if kind == "poem_meaning":
                return lib.poem_entry(last[0].title, qa, meaning=True) if last and last[1] == "poem" else None
            if kind == "poem":
                pool = lib.school_poems()
                if "唐诗" in question:
                    pool = [p for p in pool if "唐·" in p[1]] or pool
                title = self._pick([p[0] for p in pool])
                return lib.poem_entry(title, qa) if title else None
            return None
        if kind == "poem_theme":
            chars = POEM_THEMES.get(detail, detail)
            scored = [(sum(p[1].split(":", 1)[-1].count(c) for c in chars), p[0]) for p in lib.school_poems()]
            best = max((n for n, _ in scored), default=0)
            # poems that mention the theme most ("关于冬天的诗": 江雪, 雪梅 rather than a war poem with one 雪山)
            pool = [t for n, t in scored if n >= min(best, 2) and n > 0]
            title = self._pick(pool)
            return lib.poem_entry(title, qa) if title else None
        if kind == "poem_count":
            poems = lib.school_poems()
            names = "、".join(f"《{p[0]}》" for p in poems[:: max(1, len(poems) // 6)][:6])
            return WikiResult(title="小图书馆里的古诗",
                              text=f"小图书馆里有{len(poems)}首小学古诗,还有《唐诗三百首》和《千家诗》。比如{names}。想听哪一首,说诗名或者第一句就行。",
                              url="library:poems", host=HOST)
        return None

    def _remember(self, result) -> None:
        lib = self._library()
        kind = "other"
        if lib is not None and result is not None:
            if result.title in lib.idiom_titles():
                kind = "idiom"
            elif result.title in set(lib.poem_titles()):
                kind = "poem"
        if result is not None:
            self.last = (result, kind, time.time())
            if kind in ("idiom", "poem"):
                self.recent = (self.recent + [result.title])[-12:]

    def _has_local(self) -> bool:
        return any(getattr(p, "local", False) for p in self._providers())

    def decide(self, question: str, lang: str, assume_knowledge: bool = False) -> Decision:
        """assume_knowledge: the router already judged this a knowledge question with the conversation's context, so
        the keyword prefilter is skipped and a "chat" classification is overridden. The privacy checks (sensitive
        topic, grounding and scrubbing, the query rules) all still apply."""
        online = self.enabled and bool(self.contact)
        if not online and not self._has_local():
            return Decision(False, "联网已关闭" if not self.enabled else "没有设置维基百科联系方式")
        if privacy.original_is_sensitive(question):
            return Decision(False, "敏感话题")
        # Idiom stories, poems and follow-ups about them: the library entry, never the model's memory alone
        entry = self.library_entry(question, lang) if self._has_local() else None
        if entry is not None:
            return Decision(True, "", query=entry.title, topic="other", kind="knowledge", online=False, intent="library", entry=entry)
        # A parent-approved answer from the child Q&A library ranks above everything else. An exact match is used
        # here (no rewrite needed); close candidates are left to the model's pick in fetch.
        qa = self._qa() if self._has_local() else None
        qa_question = question if qa is not None and qa.candidates(question, lang) else ""
        hit = qa.match(question, lang) if qa_question else None
        if hit is not None:
            return Decision(True, "", query=hit.q, topic="other", kind="knowledge", online=False, intent="qa",
                            entry=self._qa_result(hit))
        # A poem line or a character, taken from the child's own words: library only, no model rewrite
        from curiosity_pet.library import local_target

        target = local_target(question, lang) if self._has_local() else None
        if target and privacy.check_query(target[1], self.family_terms, self.blacklist)[0]:
            local = [p for p in self._providers() if getattr(p, "local", False)]
            # Only when the library has it (a few ms); otherwise the usual flow, so no "let me look it up" for nothing
            if any(p.search(target[1], lang, intent=target[0]) for p in local if getattr(p, "accepts_intent", False)):
                return Decision(True, "", query=target[1], topic="other", kind="knowledge", online=False, intent=target[0])
        if not assume_knowledge and not privacy.looks_like_knowledge_question(question, self.family_terms):
            return Decision(False, "不像知识提问")
        try:
            r = self.rewrite(question, lang)
        except PetUnavailable:
            return Decision(False, "改写失败")
        topic = r.get("topic") if r.get("topic") in TOPICS else "other"
        kind = r.get("kind")
        if assume_knowledge and kind in ("chat", None):
            kind = "knowledge"
        if kind != "knowledge":
            return Decision(False, f"分类为 {kind}", topic=topic, kind=kind)
        query = privacy.ground_and_scrub(str(r.get("query", "")), question)
        ok, reason = privacy.check_query(query, self.family_terms, self.blacklist)
        if not ok:
            return Decision(False, f"搜索词未通过检查:{reason}", topic=topic, kind=kind)
        from curiosity_pet.library import definition_intent

        wants_name = bool(self.guess and ANSWER_ASK.search(question) and any(hasattr(p, "search_answer") for p in self._providers()))
        return Decision(True, "", query=query, topic=topic, kind=kind, online=online,
                        intent=definition_intent(question, lang), answer_question=question if wants_name else "",
                        qa_question=qa_question)

    @staticmethod
    def _qa_result(hit):
        from curiosity_pet.library import HOST
        from curiosity_pet.wiki import WikiResult

        return WikiResult(title=hit.q, text=hit.a, url=f"qa:{hit.id}", host=HOST)

    def _providers(self):
        if self.providers is not None:
            return self.providers
        if self.search is not None:
            search = self.search
            contact = self.contact

            class Legacy:
                name = "wikipedia"

                def search(self, query, lang):
                    return search(query, lang, contact=contact)

            return [Legacy()]
        from curiosity_pet.search import from_settings

        self.providers = from_settings(contact=self.contact)
        return self.providers

    def fetch(self, decision: Decision, lang: str):
        """Try the providers in order (online ones only when the decision allows); an irrelevant result is
        dropped rather than used, and the answer is then marked as a guess. A ranked provider (the library)
        has already vetted its results, so its first one is used as is."""
        result = decision.entry
        if result is None and decision.qa_question and self.qa_judge is not None and self._qa() is not None:
            hit = self._qa().match(decision.qa_question, lang, judge=self.qa_judge)
            result = self._qa_result(hit) if hit is not None else None
        if result is not None:
            if self.store:
                self.store.record_lookup(lang, decision.query, decision.topic, result.title, found=True)
            self._remember(result)
            return result
        if decision.answer_question and not decision.answer and self.guess:
            try:
                decision.answer = self.guess(decision.answer_question, lang)
            except PetUnavailable:
                decision.answer = ""
        if decision.answer:  # the model's answer name, checked against the local library first
            for provider in self._providers():
                if hasattr(provider, "search_answer"):
                    result = provider.search_answer(decision.answer, decision.query, lang)
                    if result:
                        break
        for provider in [] if result else self._providers():
            if not decision.online and not getattr(provider, "local", False):
                continue
            if getattr(provider, "accepts_intent", False):
                results = provider.search(decision.query, lang, intent=decision.intent)
            else:
                results = provider.search(decision.query, lang)
            if getattr(provider, "ranked", False):
                result = results[0] if results else None
            else:
                result = pick_best(decision.query, results)
            if result:
                break
        if self.store:
            self.store.record_lookup(
                lang, decision.query, decision.topic, result.title if result else None, found=bool(result)
            )
            if result:
                self.store.save_pending(lang, result.title, result.url, result.text)
        self._remember(result)
        return result
