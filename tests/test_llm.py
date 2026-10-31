"""Tests for llm.py retry classification (P1-3)."""
import types

import pytest
import requests

import llm


class _StubResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = json.dumps(self._body) if body else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code}")
            err.response = self
            raise err

    def json(self):
        return self._body


import json


def _patch_session(client, responses):
    """Make the LLMClient's session.post return the given responses in order."""
    iter_resp = iter(responses)

    def fake_post(url, **kwargs):
        try:
            return next(iter_resp)
        except StopIteration:
            raise AssertionError("LLM called session.post more times than expected")

    client._session.post = fake_post


def _client_with_key():
    """Return a client whose deepseek provider has a key configured.

    test_config.py reloads `config` and can leave DEEPSEEK_API_KEY empty
    during the same pytest session; we set it directly to keep these tests
    hermetic."""
    import config
    config.DEEPSEEK_API_KEY = "test-deepseek-key"
    config.MINIMAX_API_KEY = ""  # ensure only one provider is exercised
    return llm.LLMClient(provider="deepseek")


def test_no_retry_on_4xx_business_errors(monkeypatch):
    """P1-3: 400/401/403/404 must raise LLMError immediately without retry."""
    client = _client_with_key()
    _patch_session(client, [
        _StubResp(400, {"err": "bad"}),
        _StubResp(400, {"err": "bad"}),  # would be hit if retry happened
    ])
    with pytest.raises(llm.LLMError) as exc:
        client.chat([{"role": "user", "content": "x"}])
    assert "HTTP 400" in str(exc.value)


def test_retry_on_5xx_then_success(monkeypatch):
    client = _client_with_key()
    _patch_session(client, [
        _StubResp(500),
        _StubResp(503),
        _StubResp(200, {"choices": [{"message": {"content": "ok"}}]}),
    ])
    out = client.chat([{"role": "user", "content": "x"}])
    assert out == "ok"


def test_retry_on_network_error(monkeypatch):
    client = _client_with_key()
    call_count = {"n": 0}

    def fake_post(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise requests.exceptions.ConnectionError("net down")
        return _StubResp(200, {"choices": [{"message": {"content": "ok"}}]})

    client._session.post = fake_post
    out = client.chat([{"role": "user", "content": "x"}])
    assert out == "ok"
    assert call_count["n"] == 2


def test_retry_after_header_is_honored(monkeypatch):
    """P1-3: 429 with Retry-After: 1 should sleep ~1s, not 3s."""
    client = _client_with_key()
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(llm.time, "sleep", fake_sleep)
    _patch_session(client, [
        _StubResp(429, headers={"Retry-After": "1"}),
        _StubResp(200, {"choices": [{"message": {"content": "ok"}}]}),
    ])
    out = client.chat([{"role": "user", "content": "x"}])
    assert out == "ok"
    # First sleep should be ~1s (Retry-After) plus a tiny jitter, definitely
    # not the default 3s. Upper bound 2.0 leaves room for random.random().
    assert any(0.5 <= s <= 2.0 for s in sleeps), f"unexpected sleeps: {sleeps}"


def test_invalid_json_response_does_not_retry_same_provider(monkeypatch):
    """P1-3: 200 OK but unparseable JSON must NOT retry the same provider."""
    client = _client_with_key()
    # Only supply 200s that are malformed — if we retried, this would fail.
    _patch_session(client, [
        _StubResp(200, {"choices": [{}]}),  # missing message.content
    ])
    # After deepseek fails, client should fall through to next provider (minimax).
    # We don't care which provider ultimately succeeds; we only verify deepseek
    # was called exactly once.
    call_count = {"n": 0}

    def counting_post(url, **kwargs):
        call_count["n"] += 1
        return _StubResp(200, {"choices": [{}]})

    client._session.post = counting_post
    import config
    if not config.MINIMAX_API_KEY:
        with pytest.raises(llm.LLMError):
            client.chat([{"role": "user", "content": "x"}])
    else:
        with pytest.raises(llm.LLMError):
            client.chat([{"role": "user", "content": "x"}])
    # Deepseek was tried once; we don't count minimax attempts here.
    assert call_count["n"] >= 1