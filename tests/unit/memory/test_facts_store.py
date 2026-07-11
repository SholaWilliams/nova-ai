"""Tests for FactsStore (docs/09 §2, §3) — tmp_path-based, real file I/O."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova.core.errors import MemoryError as NovaMemoryError
from nova.memory.facts_store import _SOFT_CAP, FactsStore


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "facts.json"


def test_missing_file_starts_empty(path: Path) -> None:
    store = FactsStore(path)
    assert store.list_facts() == []


def test_add_fact_persists_across_instances(path: Path) -> None:
    FactsStore(path).add_fact("Has a dog named Rex", "fact", "req_1")

    reloaded = FactsStore(path)
    facts = reloaded.list_facts()
    assert len(facts) == 1
    assert facts[0].content == "Has a dog named Rex"
    assert facts[0].kind == "fact"
    assert facts[0].source_request == "req_1"
    assert facts[0].keywords == ("has", "dog", "named", "rex")
    assert facts[0].id.startswith("f_")


def test_add_fact_round_trips_the_exact_json_shape(path: Path) -> None:
    FactsStore(path).add_fact("Favorite color is blue", "preference", "req_2")

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    entry = raw["facts"][0]
    assert set(entry) == {"id", "kind", "content", "keywords", "created_at", "source_request"}
    assert entry["kind"] == "preference"


def test_delete_fact_removes_only_the_given_id(path: Path) -> None:
    store = FactsStore(path)
    first = store.add_fact("Has a dog", "fact", "req_1")
    store.add_fact("Has a cat", "fact", "req_2")

    store.delete_fact(first.id)

    remaining = FactsStore(path).list_facts()
    assert len(remaining) == 1
    assert remaining[0].content == "Has a cat"


def test_clear_facts_empties_the_store(path: Path) -> None:
    store = FactsStore(path)
    store.add_fact("Has a dog", "fact", "req_1")

    store.clear_facts()

    assert FactsStore(path).list_facts() == []


def test_soft_cap_raises_memory_error(path: Path) -> None:
    store = FactsStore(path)
    for i in range(_SOFT_CAP):
        store.add_fact(f"Fact number {i}", "fact", "req_x")

    with pytest.raises(NovaMemoryError):
        store.add_fact("One too many", "fact", "req_x")


def test_corrupt_file_is_quarantined_and_starts_empty(path: Path, tmp_path: Path) -> None:
    path.write_text("not valid json{{{", encoding="utf-8")

    store = FactsStore(path)

    assert store.list_facts() == []
    quarantined = list(tmp_path.glob("facts.json.corrupt-*"))
    assert len(quarantined) == 1


def test_non_object_json_is_quarantined(path: Path) -> None:
    path.write_text("[1, 2, 3]", encoding="utf-8")

    store = FactsStore(path)

    assert store.list_facts() == []
