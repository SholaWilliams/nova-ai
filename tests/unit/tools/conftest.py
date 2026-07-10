"""Shared fixtures for tool unit tests."""

from __future__ import annotations

import pytest

from nova.core.config import Settings
from nova.tools.base import ToolContext


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(settings=Settings())
