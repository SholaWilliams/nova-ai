"""Unit tests for nova.ui.theme — tokens, stylesheet generation, fonts, and icons."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QIcon

import nova.ui.theme as theme
from nova.ui.theme import (
    Color,
    FontRole,
    Motion,
    Radius,
    Spacing,
    accent_hex,
    build_stylesheet,
    font,
    load_bundled_fonts,
    load_icon,
    with_alpha,
)

ALL_ICON_NAMES = [
    "mic",
    "sparkles",
    "zap",
    "bookmark",
    "volume-2",
    "alert-triangle",
    "shield-question",
    "settings",
    "history",
    "brain",
    "wifi",
    "wifi-off",
    "cpu",
    "house",
]


@pytest.fixture(autouse=True)
def _reset_font_cache() -> Iterator[None]:
    """`_loaded_families` is a process-wide cache — isolate tests that monkeypatch assets."""
    theme._loaded_families.clear()
    yield
    theme._loaded_families.clear()


# ── tokens spot-check (docs/05 §2-4,8) ───────────────────────────────


def test_color_tokens_match_spec() -> None:
    assert Color.BG_BASE == "#0A0E1A"
    assert Color.ACCENT_SECONDARY == "#8B5CF6"
    assert Color.STATE_ERROR == "#F87171"
    assert Color.TEXT_PRIMARY == "#E5E7EB"


def test_accent_hex_covers_all_four_fr44_options() -> None:
    assert accent_hex("cyan") == "#22D3EE"
    assert accent_hex("violet") == "#8B5CF6"
    assert accent_hex("emerald") == "#34D399"
    assert accent_hex("amber") == "#FBBF24"


def test_accent_hex_falls_back_to_default_for_unknown_value() -> None:
    assert accent_hex("not-a-real-accent") == accent_hex("cyan")


def test_font_role_sizes_match_spec() -> None:
    assert FontRole.DISPLAY == ("Inter", 24, 700)
    assert FontRole.BODY == ("Inter", 15, 400)
    assert FontRole.LABEL == ("Inter", 13, 500)
    assert FontRole.CAPTION == ("Inter", 12, 400)
    assert FontRole.MONO == ("JetBrains Mono", 14, 400)


def test_spacing_tokens_match_4px_grid() -> None:
    assert (Spacing.XS, Spacing.SM, Spacing.MD, Spacing.LG, Spacing.XL, Spacing.XXL) == (
        4,
        8,
        16,
        24,
        32,
        48,
    )


def test_radius_tokens_match_spec() -> None:
    assert Radius.CHIP == 8
    assert Radius.CARD == 12
    assert Radius.INPUT_BAR == 16


def test_motion_tokens_match_spec() -> None:
    assert Motion.FAST == (150, "OutCubic")
    assert Motion.BASE == (250, "OutCubic")
    assert Motion.SLOW == (400, "InOutCubic")
    assert Motion.BREATHE == (3000, "InOutSine")


def test_with_alpha_sets_alpha_channel_and_keeps_rgb() -> None:
    color = with_alpha("#22D3EE", 0.2)
    assert color.red() == 0x22
    assert color.green() == 0xD3
    assert color.blue() == 0xEE
    assert color.alphaF() == pytest.approx(0.2, abs=0.01)


def test_with_alpha_clamps_out_of_range_values() -> None:
    assert with_alpha("#FFFFFF", 5.0).alphaF() == pytest.approx(1.0)
    assert with_alpha("#FFFFFF", -5.0).alphaF() == pytest.approx(0.0)


# ── stylesheet ────────────────────────────────────────────────────────


@pytest.mark.parametrize("accent", ["cyan", "violet", "emerald", "amber"])
def test_build_stylesheet_embeds_the_requested_accent(accent: str) -> None:
    qss = build_stylesheet(accent)
    assert accent_hex(accent) in qss


def test_build_stylesheet_has_no_hardcoded_accent_when_unspecified() -> None:
    assert build_stylesheet() == build_stylesheet(theme.DEFAULT_ACCENT)


# ── fonts ─────────────────────────────────────────────────────────────


def test_load_bundled_fonts_finds_the_real_repo_assets() -> None:
    loaded = load_bundled_fonts()
    assert "Inter" in loaded
    assert "JetBrains Mono" in loaded


def test_font_uses_bundled_family_when_available() -> None:
    built = font(FontRole.DISPLAY)
    loaded = load_bundled_fonts()
    assert built.family() == loaded["Inter"]
    assert built.pointSize() == 24


def test_load_bundled_fonts_falls_back_gracefully_when_assets_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(theme, "_assets_dir", lambda: tmp_path)

    loaded = load_bundled_fonts()

    assert loaded == {}
    built = font(FontRole.BODY)  # must not raise even with nothing bundled
    assert built.family() == "Segoe UI"


# ── icons ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ALL_ICON_NAMES)
def test_bundled_icon_loads(name: str) -> None:
    icon = load_icon(name, "#FFFFFF")
    assert not icon.isNull()
    assert not icon.pixmap(20, 20).isNull()


def test_missing_icon_returns_empty_icon_not_an_error() -> None:
    icon = load_icon("not-a-real-icon", "#FFFFFF")
    assert isinstance(icon, QIcon)
    assert icon.isNull()


def test_icon_is_tinted_to_the_requested_color() -> None:
    icon = load_icon("mic", "#FF0000", size=64)
    image = icon.pixmap(64, 64).toImage()

    visible_pixels = [
        image.pixelColor(x, y)
        for x in range(64)
        for y in range(64)
        if image.pixelColor(x, y).alpha() > 0
    ]
    assert visible_pixels, "icon should have painted at least one visible pixel"
    assert all(c.red() == 255 and c.green() == 0 and c.blue() == 0 for c in visible_pixels)
