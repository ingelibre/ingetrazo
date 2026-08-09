# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood and IngeTrazo contributors.
"""Unit tests for the Python Console plugin extension."""
import pytest
from plugins.python_console import PythonConsoleTool


def test_python_console_tool_metadata():
    tool = PythonConsoleTool()
    assert tool.name == "Python Console"
    assert tool.shortcut == "Ctrl+Shift+P"
    assert tool.uses_snap is False
