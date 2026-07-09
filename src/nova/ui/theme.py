"""Design tokens (docs/05 §2-4,8) and the QSS/font/icon loading built from them.

Single source for color/type/spacing/motion values — widget code must reference these,
never hardcode a hex value or duration (CODING_STANDARDS.md).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

logger = logging.getLogger(__name__)


def _assets_dir() -> Path:
    """Repo-relative in dev; next to the executable once packaged (PyInstaller, M6)."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and frozen_root:
        return Path(frozen_root) / "assets"
    return Path(__file__).resolve().parents[3] / "assets"


# ── color (docs/05 §2) ────────────────────────────────────────────────


class Color:
    """Fixed palette tokens. `accent_hex()` below handles the one user-adjustable color."""

    BG_BASE = "#0A0E1A"
    BG_SURFACE = "#111827"
    BG_RAISED = "#1A2332"
    STROKE_SUBTLE = "#233046"
    # Violet — thinking/reasoning states specifically; fixed regardless of the user's
    # chosen accent (FR-44 only makes accent.primary user-adjustable, docs/05 §2).
    ACCENT_SECONDARY = "#8B5CF6"
    STATE_SUCCESS = "#34D399"
    STATE_WARNING = "#FBBF24"
    STATE_ERROR = "#F87171"
    TEXT_PRIMARY = "#E5E7EB"
    TEXT_SECONDARY = "#94A3B8"
    TEXT_INVERSE = "#0A0E1A"
    BUBBLE_USER = "#1E3A5F"
    BUBBLE_NOVA = "#161F32"


_ACCENT_HEX: dict[str, str] = {
    "cyan": "#22D3EE",
    "violet": "#8B5CF6",
    "emerald": "#34D399",
    "amber": "#FBBF24",
}
DEFAULT_ACCENT = "cyan"


def accent_hex(accent: str) -> str:
    """Hex for one of the 4 FR-44 accent options; unknown values fall back to the default."""
    return _ACCENT_HEX.get(accent, _ACCENT_HEX[DEFAULT_ACCENT])


def with_alpha(hex_color: str, alpha: float) -> QColor:
    """A QColor with alpha applied — for glow effects (docs/05 §4: `accent @ 20%`, blur 24)."""
    color = QColor(hex_color)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


# ── typography (docs/05 §3) ──────────────────────────────────────────


class FontRole:
    """(family, px size, weight) triples. Pass to `font()` to get a ready QFont."""

    DISPLAY = ("Inter", 24, 700)
    BODY = ("Inter", 15, 400)
    LABEL = ("Inter", 13, 500)
    CAPTION = ("Inter", 12, 400)
    MONO = ("JetBrains Mono", 14, 400)


_BUNDLED_FONT_FILES = {
    "Inter": "Inter-Variable.ttf",
    "JetBrains Mono": "JetBrainsMono-Variable.ttf",
}
_SYSTEM_FALLBACK = {"Inter": "Segoe UI", "JetBrains Mono": "Consolas"}

_loaded_families: dict[str, str] = {}


def load_bundled_fonts() -> dict[str, str]:
    """Register bundled fonts with Qt. Returns {role family name: actual loaded family name}.

    Missing/unloadable files are logged at DEBUG and simply omitted — `font()` falls back to
    a close system font for that role rather than raising (TD-14 bundling is a nicety, not
    a hard requirement for the app to run).
    """
    if _loaded_families:
        return _loaded_families

    fonts_dir = _assets_dir() / "fonts"
    for role_family, filename in _BUNDLED_FONT_FILES.items():
        path = fonts_dir / filename
        if not path.is_file():
            logger.debug("Bundled font %s not found at %s; using a system font", filename, path)
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            logger.debug("Qt could not load bundled font %s", filename)
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            _loaded_families[role_family] = families[0]

    return _loaded_families


def font(role: tuple[str, int, int]) -> QFont:
    """Build a QFont for a `FontRole` triple, preferring the bundled family if it loaded."""
    family, size, weight = role
    loaded = load_bundled_fonts()
    actual_family = loaded.get(family) or _SYSTEM_FALLBACK.get(family, family)
    built = QFont(actual_family, size)
    built.setWeight(QFont.Weight(weight))
    return built


# ── spacing, radii, motion (docs/05 §4, §8) ──────────────────────────


class Spacing:
    XS = 4
    SM = 8
    MD = 16
    LG = 24
    XL = 32
    XXL = 48


class Radius:
    CHIP = 8
    CARD = 12
    INPUT_BAR = 16


class Motion:
    """(duration_ms, easing name) pairs — pass via `*Motion.BASE` to `nova.ui.animations`."""

    FAST = (150, "OutCubic")
    BASE = (250, "OutCubic")
    SLOW = (400, "InOutCubic")
    BREATHE = (3000, "InOutSine")


# ── icons (docs/05 §5) ────────────────────────────────────────────────


def load_icon(name: str, color: str, size: int = 20) -> QIcon:
    """Render a bundled Lucide icon (`assets/icons/<name>.svg`) tinted to `color`.

    Lucide source SVGs use `stroke="currentColor"`, which Qt's SVG renderer does not resolve
    on its own — so icons are rendered once to a transparent QPixmap, then tinted via
    SourceIn compositing (fills the already-painted alpha shape with the target color).
    Returns an empty QIcon if the asset is missing, rather than raising.
    """
    svg_path = _assets_dir() / "icons" / f"{name}.svg"
    if not svg_path.is_file():
        logger.debug("Icon asset not found: %s", svg_path)
        return QIcon()

    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        logger.debug("Icon asset is not a valid SVG: %s", svg_path)
        return QIcon()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return QIcon(pixmap)


# ── stylesheet (QSS) ──────────────────────────────────────────────────


def build_stylesheet(accent: str = DEFAULT_ACCENT) -> str:
    """Render the app-wide QSS for the given accent (one of the 4 FR-44 options)."""
    accent_color = accent_hex(accent)
    return f"""
        QMainWindow, QWidget {{
            background-color: {Color.BG_BASE};
            color: {Color.TEXT_PRIMARY};
            font-family: "Inter";
            font-size: {FontRole.BODY[1]}px;
        }}

        QWidget#surface, QFrame#surface {{
            background-color: {Color.BG_SURFACE};
            border: 1px solid {Color.STROKE_SUBTLE};
            border-radius: {Radius.CARD}px;
        }}

        QPushButton {{
            background-color: {Color.BG_SURFACE};
            color: {Color.TEXT_PRIMARY};
            border: 1px solid {Color.STROKE_SUBTLE};
            border-radius: {Radius.CHIP}px;
            padding: {Spacing.SM}px {Spacing.MD}px;
        }}
        QPushButton:hover {{
            background-color: {Color.BG_RAISED};
            border-color: {accent_color};
        }}
        QPushButton:pressed {{
            background-color: {Color.BG_RAISED};
        }}
        QPushButton:disabled {{
            color: {Color.TEXT_SECONDARY};
            border-color: {Color.STROKE_SUBTLE};
        }}
        QPushButton:focus {{
            border: 2px solid {accent_color};
        }}

        QLineEdit {{
            background-color: {Color.BG_SURFACE};
            color: {Color.TEXT_PRIMARY};
            border: 1px solid {Color.STROKE_SUBTLE};
            border-radius: {Radius.INPUT_BAR}px;
            padding: {Spacing.SM}px {Spacing.MD}px;
            selection-background-color: {accent_color};
            selection-color: {Color.TEXT_INVERSE};
        }}
        QLineEdit:focus {{
            border: 2px solid {accent_color};
        }}

        QLabel {{
            color: {Color.TEXT_PRIMARY};
            background: transparent;
        }}
        QLabel[role="secondary"] {{
            color: {Color.TEXT_SECONDARY};
        }}

        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {Color.STROKE_SUBTLE};
            border-radius: 5px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {Color.BG_RAISED};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        QSplitter::handle {{
            background-color: {Color.STROKE_SUBTLE};
        }}
    """
