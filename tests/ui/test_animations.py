"""Unit tests for nova.ui.animations — shared easing/animation-builder helpers."""

import pytest
from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QWidget

from nova.ui.animations import easing_curve, make_property_animation, make_variant_animation
from nova.ui.theme import Motion


def test_easing_curve_maps_known_names() -> None:
    assert easing_curve("OutCubic").type() == QEasingCurve.Type.OutCubic
    assert easing_curve("InOutCubic").type() == QEasingCurve.Type.InOutCubic
    assert easing_curve("InOutSine").type() == QEasingCurve.Type.InOutSine
    assert easing_curve("Linear").type() == QEasingCurve.Type.Linear


def test_easing_curve_falls_back_to_linear_for_unknown_name() -> None:
    assert easing_curve("NotARealCurve").type() == QEasingCurve.Type.Linear


def test_make_variant_animation_uses_the_given_motion_token(qtbot: object) -> None:
    animation = make_variant_animation(*Motion.BREATHE, start_value=0.96, end_value=1.0, loop=True)

    assert animation.duration() == 3000
    assert animation.easingCurve().type() == QEasingCurve.Type.InOutSine
    assert animation.startValue() == 0.96
    assert animation.endValue() == 1.0
    assert animation.loopCount() == -1


def test_make_variant_animation_without_loop_defaults_to_running_once() -> None:
    animation = make_variant_animation(*Motion.BASE, start_value=0, end_value=1)
    assert animation.loopCount() == 1


def test_variant_animation_actually_interpolates(qtbot: object) -> None:
    animation = make_variant_animation(50, "Linear", 0.0, 1.0)
    values: list[float] = []
    animation.valueChanged.connect(lambda v: values.append(v))

    animation.start()
    qtbot.waitUntil(lambda: animation.state() == QVariantAnimation.State.Stopped, timeout=1000)

    assert values
    assert values[-1] == pytest.approx(1.0)


def test_make_property_animation_configures_target_property(qtbot: object) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)

    animation = make_property_animation(
        widget, "windowOpacity", *Motion.FAST, start_value=0.0, end_value=1.0
    )

    assert animation.targetObject() is widget
    assert animation.propertyName() == b"windowOpacity"
    assert animation.duration() == 150
    assert animation.easingCurve().type() == QEasingCurve.Type.OutCubic
