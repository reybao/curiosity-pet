"""联网查询:决定要不要查,改写成话题词,查维基百科,记录搜索词。

顺序(全部在本机判断,通过了才联网):
  家长开关和联系方式 -> 原话是否敏感 -> 粗筛像不像知识提问 -> 本地模型分类并改写 -> 规则检查话题词 -> 维基百科
任何一步不通过就不联网,宠物照常回答(查不到就说是猜想)。
"""

import json
import re
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
        "你是一个分类和改写工具。把孩子的问题改写成用于查百科的中性关键词。"
        "只保留知识话题(人物、事物、现象的名称),去掉所有关于提问者自己、家人、朋友、学校、地点、时间、心情的内容;"
        "不要添加原句没有的内容。用中文,2 到 4 个词,空格分开;保留作品名、种类等限定词,"
        "例如\"七龙珠里的孙悟空是谁\" -> \"七龙珠 孙悟空\",\"为什么天空是蓝色的\" -> \"天空 蓝色\"。"
        "kind:knowledge=一般知识问题;personal=关于自己、家人、朋友、学校或家里的事;feelings=表达心情;"
        "sensitive=死亡、战争、灾难、身体安全或困扰;chat=闲聊或指令。topic 从给定列表选一个。只输出 JSON。"
    ),
    "en": (
        "You are a classify-and-rewrite tool. Rewrite the child's question into neutral keywords for an encyclopedia search. "
        "Keep only the knowledge topic (names of people, things, phenomena); remove anything about the asker, family, friends, "
        "school, places, times or feelings; never add anything not in the question. English, 2 to 4 words, space separated; "
        "keep qualifiers such as the title of a show or book, e.g. \"Who is Goku in Dragon Ball\" -> \"Goku Dragon Ball\", "
        "\"Why is the sky blue\" -> \"sky blue\". "
        "kind: knowledge=general knowledge question; personal=about the asker, family, friends, school or home; "
        "feelings=sharing feelings; sensitive=death, war, disasters, body safety or distress; chat=small talk or commands. "
        "Pick one topic from the list. Output JSON only."
    ),
}

FILLER = {"zh": "喵,我去查一查!", "en": "Meow, let me look that up!"}


@dataclass
class Decision:
    go: bool
    reason: str
    query: str = ""
    topic: str = "other"


def rewrite_with_model(question: str, lang: str, model=config.CHAT_MODEL, base_url=config.OLLAMA_URL) -> dict:
    """本地模型:分类并改写。只调用本机 Ollama。"""
    from urllib.parse import urlparse

    if urlparse(base_url).hostname not in LOCAL_HOSTS:
        raise ValueError(f"只允许本机模型服务: {base_url}")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": REWRITE_SYSTEM[lang]},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "think": False,
        "format": REWRITE_SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        r = httpx.post(f"{base_url}/api/chat", json=body, timeout=30)
        r.raise_for_status()
        return json.loads(r.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
        raise PetUnavailable(str(e)) from e


def _terms(query: str) -> list[str]:
    """把搜索词拆成用于相关性检查的词;没有空格的长中文词拆成两字一组。"""
    terms = []
    for t in query.lower().split():
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", t):
            terms += [t[i : i + 2] for i in range(0, len(t) - 1, 2)]
        else:
            terms.append(t)
    return terms


def relevance(query: str, result) -> float:
    """相关度:搜索词在开头一段里出现的比例,出现在标题里的额外加分。"""
    terms = _terms(query)
    if not terms:
        return 0.0
    title, text = result.title.lower(), result.text[:400].lower()
    hits = sum((t in title) + (t in text) for t in terms)
    return hits / (2 * len(terms))


def relevant(query: str, result) -> bool:
    """搜索词出现在条目标题或开头一段里:两个词以内要全部出现,三个及以上至少三分之二。

    实测:"天空蓝色成因" 搜到 "蓝色弹珠"(一张地球照片);"猫 打呼噜" 搜到儿童作家杨红樱(只含"猫"),都要丢掉。
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
    """从前几个搜索结果里挑最相关的。实测"天空 蓝色"排第一的是一部叫《知道天空有多蓝的人啊》的电影。"""
    if results is None:
        return None
    if not isinstance(results, list):
        results = [results]
    candidates = [r for r in results if relevant(query, r)]
    if not candidates:
        return None
    # 同分时保留维基百科原来的排名(max 取第一个最大值)
    return max(candidates, key=lambda r: relevance(query, r))


class Researcher:
    def __init__(
        self,
        store=None,
        enabled: bool = config.ONLINE_LOOKUP,
        contact: str = config.WIKI_CONTACT,
        rewrite=rewrite_with_model,
        search=wiki.search_all,
        family_terms=tuple(config.FAMILY_TERMS),
        blacklist=tuple(config.BLACKLIST),
    ):
        self.store = store
        self.enabled = enabled
        self.contact = contact
        self.rewrite = rewrite
        self.search = search
        self.family_terms = tuple(family_terms)
        self.blacklist = tuple(blacklist)

    def decide(self, question: str, lang: str) -> Decision:
        if not self.enabled:
            return Decision(False, "联网已关闭")
        if not self.contact:
            return Decision(False, "没有设置维基百科联系方式")
        if privacy.original_is_sensitive(question):
            return Decision(False, "敏感话题")
        if not privacy.looks_like_knowledge_question(question, self.family_terms):
            return Decision(False, "不像知识提问")
        try:
            r = self.rewrite(question, lang)
        except PetUnavailable:
            return Decision(False, "改写失败")
        topic = r.get("topic") if r.get("topic") in TOPICS else "other"
        if r.get("kind") != "knowledge":
            return Decision(False, f"分类为 {r.get('kind')}", topic=topic)
        query = privacy.ground_and_scrub(str(r.get("query", "")), question)
        ok, reason = privacy.check_query(query, self.family_terms, self.blacklist)
        if not ok:
            return Decision(False, f"搜索词未通过检查:{reason}", topic=topic)
        return Decision(True, "", query=query, topic=topic)

    def fetch(self, decision: Decision, lang: str):
        # 搜到不相关的条目时宁可不用,回答标注"这是我的猜想"
        result = pick_best(decision.query, self.search(decision.query, lang, contact=self.contact))
        if self.store:
            self.store.record_lookup(
                lang, decision.query, decision.topic, result.title if result else None, found=bool(result)
            )
            if result:
                self.store.save_pending(lang, result.title, result.url, result.text)
        return result
