"""Tests for nova.memory.retrieval (docs/09 §5) — tokenize/extract_keywords + KeywordRetriever."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nova.core.models import MemoryItem
from nova.memory.retrieval import KeywordRetriever, extract_keywords, tokenize


def _item(content: str, keywords: tuple[str, ...], *, age_days: int = 0) -> MemoryItem:
    return MemoryItem(
        id="f_test",
        kind="fact",
        content=content,
        keywords=keywords,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
        source_request="req_test",
    )


def test_extract_keywords_lowercases_dedupes_and_drops_stopwords() -> None:
    assert extract_keywords("The Favorite color is blue and blue") == (
        "favorite",
        "color",
        "blue",
    )


def test_tokenize_returns_a_set() -> None:
    assert tokenize("Favorite color is blue") == {"favorite", "color", "blue"}


def test_tokenize_of_pure_stopwords_is_empty() -> None:
    assert tokenize("is the a") == frozenset()


class TestKeywordRetriever:
    def test_no_query_words_returns_nothing(self) -> None:
        retriever = KeywordRetriever()
        items = [_item("Favorite color is blue", ("favorite", "color", "blue"))]

        assert retriever.retrieve("the a", items, k=5) == []

    def test_scores_by_overlap_and_returns_matches_only(self) -> None:
        retriever = KeywordRetriever()
        color_fact = _item("Favorite color is blue", ("favorite", "color", "blue"))
        food_fact = _item("Likes pizza", ("likes", "pizza"))

        result = retriever.retrieve("what's my favorite color", [color_fact, food_fact], k=5)

        assert result == [color_fact]

    def test_higher_overlap_score_ranks_first(self) -> None:
        retriever = KeywordRetriever()
        weak = _item("Has a dog", ("dog",))
        strong = _item("Favorite dog breed is corgi", ("favorite", "dog", "breed", "corgi"))

        result = retriever.retrieve("favorite dog breed", [weak, strong], k=5)

        assert result == [strong, weak]

    def test_recency_breaks_ties(self) -> None:
        retriever = KeywordRetriever()
        older = _item("Likes cats", ("likes", "cats"), age_days=5)
        newer = _item("Likes cats too", ("likes", "cats"), age_days=0)

        result = retriever.retrieve("cats", [older, newer], k=5)

        assert result == [newer, older]

    def test_k_limits_the_result_count(self) -> None:
        retriever = KeywordRetriever()
        items = [_item(f"Likes thing {i}", ("likes", "thing")) for i in range(10)]

        result = retriever.retrieve("thing", items, k=3)

        assert len(result) == 3
