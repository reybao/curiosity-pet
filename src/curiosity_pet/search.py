"""Search providers for the lookup: the local library (offline, tried first), Brave or Google web search, and Wikipedia.

All providers receive only the neutral topic words that passed the privacy gate (lookup.py); they never
see the child's words. Results are normalized to WikiResult (title, text, url, host) so the rest of the
lookup (relevance check, prompt reference, source label) does not care where they came from.
Provider choice and keys live in the parent's settings.json ("search": {"provider": ..., "api_key": ..., "cx": ...});
"library": false there turns the local library off.
"""

from urllib.parse import urlparse

import httpx

from curiosity_pet import config, wiki
from curiosity_pet.wiki import WikiResult

TIMEOUT_S = 4.0
LABELS = {"wikipedia": {"zh": "维基百科", "en": "Wikipedia"}, "brave": {"zh": "Brave 搜索", "en": "Brave Search"},
          "google": {"zh": "Google 搜索", "en": "Google Search"}, "library": {"zh": "小图书馆", "en": "my library"}}


def _snippets(items, host_key, title_key, text_key, url_key) -> list[WikiResult]:
    out = []
    for it in items or []:
        title, text, url = it.get(title_key, ""), it.get(text_key, ""), it.get(url_key, "")
        if not (title and text and url):
            continue
        out.append(WikiResult(title=str(title), text=wiki.trim(str(text), 600), url=str(url), host=urlparse(str(url)).netloc))
    return out


class LibraryProvider:
    """The local library (library.py). Nothing leaves the machine, so it also works when online lookup is off.
    Its results are already ranked and vetted, so the lookup uses the first one as is."""

    name = "library"
    local = True
    ranked = True
    accepts_intent = True

    def __init__(self, library=None):
        from curiosity_pet.library import Library

        self.library = library or Library()

    def search(self, query: str, lang: str, intent: str | None = None) -> list[WikiResult]:
        return self.library.search(query, lang, intent=intent)

    def search_answer(self, answer: str, query: str, lang: str) -> WikiResult | None:
        return self.library.answer_entry(answer, query, lang)


class WikipediaProvider:
    name = "wikipedia"

    def __init__(self, contact: str):
        self.contact = contact

    def search(self, query: str, lang: str) -> list[WikiResult]:
        return wiki.search_all(query, lang, contact=self.contact)


class BraveProvider:
    """Brave Search API (free plan: 2000 queries a month). Safe search strict."""

    name = "brave"
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client

    def search(self, query: str, lang: str) -> list[WikiResult]:
        if not self.api_key:
            return []
        params = {"q": query, "count": "5", "safesearch": "strict",
                  "search_lang": "zh-hans" if lang == "zh" else "en", "text_decorations": "0"}
        headers = {"Accept": "application/json", "X-Subscription-Token": self.api_key}
        try:
            client = self.client or httpx.Client(follow_redirects=False)
            r = client.get(self.URL, params=params, headers=headers, timeout=TIMEOUT_S)
            if r.status_code != 200:
                return []
            items = r.json().get("web", {}).get("results", [])
        except (httpx.HTTPError, ValueError):
            return []
        return _snippets(items, "host", "title", "description", "url")


class GoogleProvider:
    """Google Programmable Search (Custom Search JSON API, free: 100 queries a day). SafeSearch active."""

    name = "google"
    URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, cx: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.cx = cx
        self.client = client

    def search(self, query: str, lang: str) -> list[WikiResult]:
        if not (self.api_key and self.cx):
            return []
        params = {"key": self.api_key, "cx": self.cx, "q": query, "num": "5", "safe": "active",
                  "lr": "lang_zh-CN" if lang == "zh" else "lang_en"}
        try:
            client = self.client or httpx.Client(follow_redirects=False)
            r = client.get(self.URL, params=params, timeout=TIMEOUT_S)
            if r.status_code != 200:
                return []
            items = r.json().get("items", [])
        except (httpx.HTTPError, ValueError):
            return []
        return _snippets(items, "displayLink", "title", "snippet", "link")


def from_settings(settings: dict | None = None, contact: str | None = None, library_path=None):
    """Providers in the order to try: the local library (if built), the configured web search (if any), Wikipedia."""
    from curiosity_pet.library import DB_PATH, Library

    settings = config.load_settings() if settings is None else settings
    contact = config.WIKI_CONTACT if contact is None else contact
    cfg = settings.get("search") if isinstance(settings.get("search"), dict) else {}
    providers = []
    lib = Library(DB_PATH if library_path is None else library_path)
    if settings.get("library", True) and lib.available():
        providers.append(LibraryProvider(lib))
    name = cfg.get("provider", "wikipedia")
    if name == "brave" and cfg.get("api_key"):
        providers.append(BraveProvider(cfg["api_key"]))
    elif name == "google" and cfg.get("api_key") and cfg.get("cx"):
        providers.append(GoogleProvider(cfg["api_key"], cfg["cx"]))
    providers.append(WikipediaProvider(contact))
    return providers


def label(host: str, lang: str) -> str:
    if host == "library":
        return LABELS["library"][lang]
    if host.endswith("wikipedia.org"):
        return LABELS["wikipedia"][lang]
    return host.removeprefix("www.")
