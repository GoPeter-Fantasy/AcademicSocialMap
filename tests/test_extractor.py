"""Tests for extractor schema validation (P1-1, P1-2)."""
import logging

import pytest

import extractor
from llm import LLMError


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.last_messages = None

    def chat_json(self, messages, temperature=0.2, max_tokens=4000):
        self.last_messages = messages
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_extract_idea_uses_system_user_separation():
    """P1-1: prompt must be split into a system message and a user message
    containing only the idea text — no template injection from the idea."""
    fake = _FakeLLM({"methods": [], "concepts": [], "queries": []})
    extractor.extract_idea("hello world", llm=fake)
    msgs = fake.last_messages
    assert msgs[0]["role"] == "system", "system message must come first"
    assert "research" in msgs[0]["content"].lower()
    assert msgs[1]["role"] == "user"
    assert "hello world" in msgs[1]["content"]
    assert "{idea}" not in msgs[0]["content"]


def test_extract_idea_truncates_overlong_input():
    """P1-1: defensive length cap even if upstream validation is bypassed."""
    fake = _FakeLLM({"methods": [], "concepts": [], "queries": []})
    huge = "x" * 10_000
    extractor.extract_idea(huge, llm=fake)
    user_text = fake.last_messages[1]["content"]
    assert "x" * 4000 in user_text
    assert "x" * 4001 not in user_text


def test_extract_idea_falls_back_on_llm_error():
    fake = _FakeLLM(LLMError("upstream down"))
    out = extractor.extract_idea("hello", llm=fake)
    assert out == {"methods": [], "concepts": [], "queries": ["hello"]}


def test_extract_idea_falls_back_on_invalid_schema():
    """P1-2: confidence out of [0,1] or missing required keys must not crash —
    we degrade gracefully to an empty schema."""
    fake = _FakeLLM({"methods": [{"name": "x", "confidence": 2.5}], "concepts": "not a list"})
    out = extractor.extract_idea("hello", llm=fake)
    assert out == {"methods": [], "concepts": [], "queries": ["hello"]}


def test_extract_methods_swallows_invalid_results():
    """P1-2: malformed items are dropped; valid items in the same response survive."""
    fake = _FakeLLM({
        "results": [
            {"id": "P1", "methods": [{"name": "GNN", "confidence": 0.9}]},
            {"id": "P2", "methods": "garbage"},  # invalid
            {"id": "", "methods": []},  # missing id
            {"id": "P3"},  # missing methods
        ]
    })
    out = extractor.extract_methods_from_abstracts(
        [{"id": "P1", "title": "t", "abstract": "a", "cited_by_count": 1}],
        llm=fake,
    )
    assert "P1" in out
    assert out["P1"][0]["name"] == "GNN"
    assert "P2" not in out
    assert "" not in out