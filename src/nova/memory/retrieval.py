"""Keyword tokenization + retrieval (docs/09 §5) — the v1 retrieval index. Zero dependencies,
transparent (a child can be shown *why* a memory matched — EO-5), adequate at <= 200 facts.
The seam for a future vector/hybrid retriever without changing `MemoryService`'s interface
(docs/09 §6): swap `KeywordRetriever` for a `HybridRetriever` behind the same `retrieve()`.
"""

from __future__ import annotations

import re

from nova.core.models import MemoryItem

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "my",
        "your",
        "his",
        "her",
        "its",
        "our",
        "their",
        "me",
        "him",
        "them",
        "us",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "about",
        "as",
        "by",
        "that",
        "this",
        "these",
        "those",
        "do",
        "does",
        "did",
        "not",
        "so",
        "if",
        "than",
    }
)


def extract_keywords(text: str) -> tuple[str, ...]:
    """Ordered, deduped, stopword-free tokens — the `keywords` stored on a `MemoryItem` at
    write time (docs/09 §3)."""
    seen: list[str] = []
    for word in _WORD_RE.findall(text.lower()):
        if word not in _STOPWORDS and word not in seen:
            seen.append(word)
    return tuple(seen)


def tokenize(text: str) -> frozenset[str]:
    """Same tokenization, as a set — for scoring a query against stored `keywords`."""
    return frozenset(extract_keywords(text))


class KeywordRetriever:
    """`score = |query_words ∩ fact.keywords|`, recency tiebreak, top-k with score >= 1
    (docs/09 §5)."""

    def retrieve(self, query: str, items: list[MemoryItem], k: int) -> list[MemoryItem]:
        query_words = tokenize(query)
        if not query_words:
            return []

        scored = ((len(query_words & set(item.keywords)), item) for item in items)
        matches = [(score, item) for score, item in scored if score >= 1]
        matches.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        return [item for _score, item in matches[:k]]
