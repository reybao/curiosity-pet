"""Wikipedia lookup: connects only to Wikipedia, sends only the search terms, and does not raise on failure."""

import httpx
import pytest

from curiosity_pet import wiki


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def page_json(title, extract):
    return {
        "query": {
            "pages": [
                {"title": title, "extract": extract, "fullurl": f"https://x.wikipedia.org/wiki/{title}", "index": 1}
            ]
        }
    }


def test_chinese_query_goes_to_zh_wikipedia_in_simplified_chinese():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=page_json("孙悟空 (七龙珠)", "孙悟空是《七龙珠》的主角。"))

    r = wiki.search("七龙珠 孙悟空", "zh", client=make_client(handler))
    assert r.title == "孙悟空 (七龙珠)"
    assert "主角" in r.text
    req = seen[0]
    assert req.url.host == "zh.wikipedia.org"
    assert req.url.params["gsrsearch"] == "七龙珠 孙悟空"
    assert req.url.params["variant"] == "zh-cn"


def test_english_tries_simple_wikipedia_first_then_english():
    hosts = []

    def handler(req):
        hosts.append(req.url.host)
        if req.url.host == "simple.wikipedia.org":
            return httpx.Response(200, json={"batchcomplete": True})  # not found
        return httpx.Response(200, json=page_json("Goku", "Goku is the main character of Dragon Ball."))

    r = wiki.search("Goku Dragon Ball", "en", client=make_client(handler))
    # Each site first does a full-text search, then fetches directly by title; English Wikipedia is queried only if Simple English has neither
    assert hosts == ["simple.wikipedia.org"] * 2 + ["en.wikipedia.org"] * 2
    assert r.title == "Goku"


def test_request_carries_no_cookies_and_only_the_query():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=page_json("恐龙", "恐龙是..."))

    wiki.search("恐龙 灭绝", "zh", client=make_client(handler))
    for req in seen:
        assert "cookie" not in {k.lower() for k in req.headers}
    # Besides the fixed API parameters, the only free text in the params is the search terms (full-text search) or words from them (fetch by title)
    free = [{k: v for k, v in req.url.params.items() if k not in wiki.FIXED_PARAM_KEYS} for req in seen]
    assert free == [{"gsrsearch": "恐龙 灭绝"}, {"titles": "恐龙|灭绝"}]


def test_only_wikipedia_hosts_are_allowed():
    with pytest.raises(ValueError):
        wiki.api_url("evil.example.com")
    assert wiki.api_url("zh.wikipedia.org").startswith("https://zh.wikipedia.org/")


def test_network_failure_returns_none():
    def handler(req):
        raise httpx.ConnectTimeout("timeout")

    assert wiki.search("恐龙", "zh", client=make_client(handler)) is None


def test_http_error_returns_none():
    assert wiki.search("恐龙", "zh", client=make_client(lambda r: httpx.Response(503))) is None


def test_long_extract_is_trimmed():
    def handler(req):
        return httpx.Response(200, json=page_json("恐龙", "长" * 5000))

    r = wiki.search("恐龙", "zh", client=make_client(handler))
    assert len(r.text) <= wiki.MAX_CHARS


def test_no_contact_means_no_network():
    # No request is sent when no contact is given
    assert wiki.search("恐龙", "zh", contact=None) is None


def test_user_agent_includes_contact():
    assert "pet@example.org" in wiki.user_agent("pet@example.org")


def test_disambiguation_or_empty_extract_is_skipped():
    def handler(req):
        return httpx.Response(200, json=page_json("孙悟空", ""))

    assert wiki.search("孙悟空", "zh", client=make_client(handler)) is None
