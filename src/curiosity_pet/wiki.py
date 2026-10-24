"""维基百科查询(联网查询的唯一来源)。

只连维基百科;请求里唯一的自由文本是隐私关卡放行的搜索词;不保存、不发送 cookie;
网络失败、超时、没找到都返回 None,不影响宠物继续回答。
中文用 zh.wikipedia 并转成简体;英文先查 Simple English Wikipedia(更适合孩子),没有再查英文维基。
"""

from dataclasses import dataclass

import httpx

ALLOWED_HOSTS = {"zh.wikipedia.org", "en.wikipedia.org", "simple.wikipedia.org"}
HOSTS_BY_LANG = {"zh": ["zh.wikipedia.org"], "en": ["simple.wikipedia.org", "en.wikipedia.org"]}
# 维基媒体的 User-Agent 政策(https://w.wiki/4wJS)要求自动程序附联系方式,否则会被拦(实测 403)。
# 联系方式由家长在配置里填(建议专用邮箱);没填时不联网。不用改请求头的办法绕过他们的机器人检测。
USER_AGENT_TEMPLATE = "CuriosityPet/0.1 (non-commercial home learning app; {contact})"


def user_agent(contact: str) -> str:
    return USER_AGENT_TEMPLATE.format(contact=contact)
TIMEOUT_S = 3.0
MAX_CHARS = 1200
FIXED_PARAMS = {
    "action": "query",
    "format": "json",
    "formatversion": "2",
    "generator": "search",
    "gsrlimit": "3",
    "prop": "extracts|info",
    "exintro": "1",
    "explaintext": "1",
    "inprop": "url",
    "redirects": "1",
}
# 按条目名直接取(搜索词里的每个词各取一次),补全文搜索的不足
TITLE_PARAMS = {
    "action": "query",
    "format": "json",
    "formatversion": "2",
    "prop": "extracts|info",
    "exintro": "1",
    "explaintext": "1",
    "inprop": "url",
    "redirects": "1",
}
FIXED_PARAM_KEYS = set(FIXED_PARAMS) | set(TITLE_PARAMS) | {"variant"}
DISAMBIGUATION_MARKERS = ("可以指", "可能是指", "may refer to", "can refer to")


@dataclass
class WikiResult:
    title: str
    text: str
    url: str
    host: str


def api_url(host: str) -> str:
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"只允许维基百科: {host}")
    return f"https://{host}/w/api.php"


def trim(text: str, limit: int = MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # 尽量在句末截断
    for mark in ("。", ". ", "!", "?", "\n"):
        pos = cut.rfind(mark)
        if pos > limit // 2:
            return cut[: pos + 1].strip()
    return cut


def _query_host(client: httpx.Client, host: str, query: str) -> list[WikiResult]:
    params = dict(FIXED_PARAMS, gsrsearch=query)
    return _fetch(client, host, params)


def _title_host(client: httpx.Client, host: str, query: str) -> list[WikiResult]:
    """把搜索词里的每个词当作条目名直接取,例如"天空 蓝色"取《天空》《蓝色》。"""
    params = dict(TITLE_PARAMS, titles="|".join(query.split()[:3]))
    return [r for r in _fetch(client, host, params) if r.url]


def _fetch(client: httpx.Client, host: str, params: dict) -> list[WikiResult]:
    if host == "zh.wikipedia.org":
        params["variant"] = "zh-cn"
    try:
        r = client.get(api_url(host), params=params, timeout=TIMEOUT_S)
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    out = []
    for page in sorted(r.json().get("query", {}).get("pages", []), key=lambda p: p.get("index", 0)):
        if page.get("missing"):
            continue
        text = (page.get("extract") or "").strip()
        if not text or any(m in text[:200] for m in DISAMBIGUATION_MARKERS):
            continue
        out.append(WikiResult(title=page.get("title", ""), text=trim(text), url=page.get("fullurl", ""), host=host))
    return out


def search(
    query: str, lang: str, client: httpx.Client | None = None, contact: str | None = None
) -> WikiResult | None:
    """返回排名第一的有效条目。"""
    results = search_all(query, lang, client=client, contact=contact)
    return results[0] if results else None


def search_all(
    query: str, lang: str, client: httpx.Client | None = None, contact: str | None = None
) -> list[WikiResult]:
    """返回前几个有效条目(按维基百科的搜索排名),由调用方挑最相关的。"""
    own = client is None
    if own:
        if not contact:
            return []  # 没有联系方式就不联网,见 USER_AGENT_TEMPLATE
        # 每次新建客户端:不留 cookie,不复用连接上的任何状态
        client = httpx.Client(headers={"User-Agent": user_agent(contact)}, follow_redirects=False)
    try:
        for host in HOSTS_BY_LANG.get(lang, HOSTS_BY_LANG["en"]):
            found = _query_host(client, host, query)
            titled = _title_host(client, host, query)
            # 直接按条目名取到的排前面;同一条目去重
            seen, results = set(), []
            for r in titled + found:
                if r.title not in seen:
                    seen.add(r.title)
                    results.append(r)
            if results:
                return results
        return []
    finally:
        if own:
            client.close()
