"""Wikipedia lookup (the only source for web lookups).

Connects to Wikipedia only; the only free text in a request is the search term cleared by the privacy gate; no cookies are stored or sent;
network failure, timeout, or no result all return None and do not stop the pet from answering.
Chinese uses zh.wikipedia, converted to Simplified; English tries Simple English Wikipedia first (better for children), then English Wikipedia.
"""

from dataclasses import dataclass

import httpx

ALLOWED_HOSTS = {"zh.wikipedia.org", "en.wikipedia.org", "simple.wikipedia.org"}
HOSTS_BY_LANG = {"zh": ["zh.wikipedia.org"], "en": ["simple.wikipedia.org", "en.wikipedia.org"]}
# Wikimedia's User-Agent policy (https://w.wiki/4wJS) requires bots to include contact info, otherwise requests are blocked (measured: 403).
# The parent fills in the contact info in the config (a dedicated email is recommended); without it there is no web access. We do not work around their bot detection by altering request headers.
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
# Fetch directly by entry name (once per word in the search term), to make up for the shortcomings of full-text search
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
        raise ValueError(f"Only Wikipedia is allowed: {host}")
    return f"https://{host}/w/api.php"


def trim(text: str, limit: int = MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Truncate at a sentence end where possible
    for mark in ("。", ". ", "!", "?", "\n"):
        pos = cut.rfind(mark)
        if pos > limit // 2:
            return cut[: pos + 1].strip()
    return cut


def _query_host(client: httpx.Client, host: str, query: str) -> list[WikiResult]:
    params = dict(FIXED_PARAMS, gsrsearch=query)
    return _fetch(client, host, params)


def _title_host(client: httpx.Client, host: str, query: str) -> list[WikiResult]:
    """Treat each word in the search term as an entry name and fetch it directly, e.g. "天空 蓝色" fetches the entries 天空 and 蓝色."""
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
    """Return the top-ranked valid entry."""
    results = search_all(query, lang, client=client, contact=contact)
    return results[0] if results else None


def search_all(
    query: str, lang: str, client: httpx.Client | None = None, contact: str | None = None
) -> list[WikiResult]:
    """Return the first few valid entries (in Wikipedia search rank order) for the caller to pick the most relevant."""
    own = client is None
    if own:
        if not contact:
            return []  # no contact info means no web access, see USER_AGENT_TEMPLATE
        # Create a new client each time: keep no cookies and reuse no state from earlier connections
        client = httpx.Client(headers={"User-Agent": user_agent(contact)}, follow_redirects=False)
    try:
        for host in HOSTS_BY_LANG.get(lang, HOSTS_BY_LANG["en"]):
            found = _query_host(client, host, query)
            titled = _title_host(client, host, query)
            # Entries fetched directly by name come first; duplicates of the same entry are dropped
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
