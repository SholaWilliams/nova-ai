"""Tests for the LLMProvider ABC and its supporting types (docs/10 §1)."""

from __future__ import annotations

import pytest

from nova.providers.base import GenerateOptions, LLMProvider


def test_llm_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_generate_options_defaults_match_docs_10_budget() -> None:
    opts = GenerateOptions()
    assert opts.max_tokens == 300
    assert opts.temperature == 0.6
    assert opts.timeout_s == 20.0


def test_generate_options_is_frozen() -> None:
    opts = GenerateOptions()
    with pytest.raises(AttributeError):
        opts.max_tokens = 100  # type: ignore[misc]
