"""Shared animation helpers built on the motion tokens (docs/05 §8, theme.Motion).

CODING_STANDARDS.md: "no ad-hoc durations/easings" — widgets build animations through
these helpers so every duration/easing traces back to a named token.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QVariantAnimation

_EASING_CURVES: dict[str, QEasingCurve.Type] = {
    "Linear": QEasingCurve.Type.Linear,
    "OutCubic": QEasingCurve.Type.OutCubic,
    "InOutCubic": QEasingCurve.Type.InOutCubic,
    "InOutSine": QEasingCurve.Type.InOutSine,
}


def easing_curve(name: str) -> QEasingCurve:
    """Look up a named easing (falls back to Linear for an unrecognized name)."""
    return QEasingCurve(_EASING_CURVES.get(name, QEasingCurve.Type.Linear))


def make_property_animation(
    target: QObject,
    property_name: str,
    duration_ms: int,
    easing: str,
    *,
    start_value: object = None,
    end_value: object = None,
    loop: bool = False,
) -> QPropertyAnimation:
    """Build a QPropertyAnimation from a motion token, e.g. `*theme.Motion.BASE`."""
    animation = QPropertyAnimation(target, property_name.encode())
    animation.setDuration(duration_ms)
    animation.setEasingCurve(easing_curve(easing))
    if start_value is not None:
        animation.setStartValue(start_value)
    if end_value is not None:
        animation.setEndValue(end_value)
    if loop:
        animation.setLoopCount(-1)
    return animation


def make_variant_animation(
    duration_ms: int,
    easing: str,
    start_value: object,
    end_value: object,
    *,
    loop: bool = False,
) -> QVariantAnimation:
    """Build a phase-driving QVariantAnimation for custom-painted widgets (e.g. PulseRing)."""
    animation = QVariantAnimation()
    animation.setDuration(duration_ms)
    animation.setEasingCurve(easing_curve(easing))
    animation.setStartValue(start_value)
    animation.setEndValue(end_value)
    if loop:
        animation.setLoopCount(-1)
    return animation
