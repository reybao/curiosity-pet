"""Search providers: only the neutral query leaves the machine, safe search is on, failures return nothing."""

import httpx

from curiosity_pet import search
from curiosity_pet.search import BraveProvider, GoogleProvider, from_settings, label


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_brave_request_shape_and_results():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Goku - Dragon Ball Wiki", "description": "Goku is a Saiyan raised on Earth.", "url": "https://dragonball.fandom.com/wiki/Goku"},
            {"title": "no url", "description": "x"},
        ]}})

    out = BraveProvider("KEY", client=mock(handler)).search("Goku Dragon Ball", "en")
    req = seen[0]
    assert req.url.host == "api.search.brave.com"
    assert req.url.params["q"] == "Goku Dragon Ball" and req.url.params["safesearch"] == "strict"
    assert req.url.params["search_lang"] == "en" and req.headers["X-Subscription-Token"] == "KEY"
    assert "cookie" not in {k.lower() for k in req.headers}
    assert [r.title for r in out] == ["Goku - Dragon Ball Wiki"] and out[0].host == "dragonball.fandom.com"


def test_google_request_shape():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"items": [
            {"title": "孙悟空 (七龙珠)", "snippet": "孙悟空是《七龙珠》的主角。", "link": "https://zh.wikipedia.org/wiki/x", "displayLink": "zh.wikipedia.org"}
        ]})

    out = GoogleProvider("KEY", "CX", client=mock(handler)).search("七龙珠 孙悟空", "zh")
    p = seen[0].url.params
    assert seen[0].url.host == "www.googleapis.com"
    assert p["q"] == "七龙珠 孙悟空" and p["safe"] == "active" and p["lr"] == "lang_zh-CN" and p["cx"] == "CX"
    assert out[0].title == "孙悟空 (七龙珠)"


def test_failures_and_missing_keys_return_nothing():
    assert BraveProvider("", client=mock(lambda r: httpx.Response(200, json={}))).search("x", "en") == []
    assert BraveProvider("K", client=mock(lambda r: httpx.Response(429))).search("x", "en") == []
    assert GoogleProvider("K", "", client=mock(lambda r: httpx.Response(200, json={}))).search("x", "en") == []

    def boom(req):
        raise httpx.ConnectTimeout("t")

    assert GoogleProvider("K", "C", client=mock(boom)).search("x", "en") == []


def test_provider_order_from_settings():
    assert [p.name for p in from_settings({}, contact="c")] == ["wikipedia"]
    assert [p.name for p in from_settings({"search": {"provider": "brave", "api_key": "k"}}, contact="c")] == ["brave", "wikipedia"]
    assert [p.name for p in from_settings({"search": {"provider": "google", "api_key": "k", "cx": "x"}}, contact="c")] == ["google", "wikipedia"]
    # a provider without its key is skipped
    assert [p.name for p in from_settings({"search": {"provider": "brave"}}, contact="c")] == ["wikipedia"]


def test_labels():
    assert label("zh.wikipedia.org", "zh") == "维基百科" and label("simple.wikipedia.org", "en") == "Wikipedia"
    assert label("www.dragonball.fandom.com", "en") == "dragonball.fandom.com"
    assert search.LABELS["brave"]["zh"]
