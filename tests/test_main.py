"""Tests for main.py helpers (fallback term extraction on LLM failure)."""
from main import _fallback_concepts


def test_fallback_concepts_lowercases_dedupes_caps():
    assert _fallback_concepts("Using Graph Neural Networks using graph") == \
        ["graph", "neural", "networks"]


def test_fallback_concepts_empty_for_no_english():
    assert _fallback_concepts("") == []
    assert _fallback_concepts("用图神经网络做药物发现") == []
