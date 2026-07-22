"""Tests for atomic_write_text (docs/03 §15, docs/09 §2) — extracted from config.py's
existing atomic-write pattern in M5; see test_config.py for the settings/.env-specific
regression coverage this still holds."""

from __future__ import annotations

from pathlib import Path

from nova.core.atomic_io import atomic_write_text


def test_writes_the_given_text(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"

    atomic_write_text(path, "hello")

    assert path.read_text(encoding="utf-8") == "hello"


def test_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "out.txt"

    atomic_write_text(path, "hello")

    assert path.read_text(encoding="utf-8") == "hello"


def test_overwrites_existing_content(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"
    path.write_text("old", encoding="utf-8")

    atomic_write_text(path, "new")

    assert path.read_text(encoding="utf-8") == "new"


def test_no_leftover_temp_files_after_a_successful_write(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"

    atomic_write_text(path, "hello")

    assert list(tmp_path.iterdir()) == [path]


def test_custom_tmp_prefix_is_honored(tmp_path: Path) -> None:
    path = tmp_path / ".env"

    atomic_write_text(path, "KEY=value\n", tmp_prefix=".env.")

    assert path.read_text(encoding="utf-8") == "KEY=value\n"
