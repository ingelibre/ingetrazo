# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Unit tests for the runtime plugin loader system."""
import inspect
from pathlib import Path

import pytest

from tools.base import Tool
import plugins.model_info as model_info_mod


def test_plugin_discovery_existing_plugins():
    """Verify that the model_info plugin is discoverable as a Tool subclass."""
    tools_found = []
    for _name, obj in inspect.getmembers(model_info_mod, inspect.isclass):
        if issubclass(obj, Tool) and obj is not Tool:
            tools_found.append(obj())

    assert len(tools_found) == 1
    assert tools_found[0].name == "Model Info"


def test_plugins_directory_exists():
    """Verify that the plugins directory exists and contains plugin files."""
    plugins_dir = Path(__file__).resolve().parent.parent / "plugins"
    assert plugins_dir.is_dir()
    assert (plugins_dir / "__init__.py").exists()
    assert (plugins_dir / "model_info.py").exists()
