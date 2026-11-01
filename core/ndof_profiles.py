# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable SpaceMouse navigation profiles (never directly writes QSettings)."""
import json
import math
from core.ndof import AXES, ACTIONS, NdofSettings

FORMAT = "ingetrazo.ndof.profile"
VERSION = 1


def profile_to_dict(settings):
    return {
        "format": FORMAT, "version": VERSION,
        "mapping": {axis: settings.axis_mapping[axis] for axis in AXES},
        "inversion": {axis: settings.axis_inversion[axis] for axis in AXES},
        "sensitivity": {axis: settings.axis_sensitivity[axis] for axis in AXES},
        "global_speed": settings.sensitivity,
        "deadzone": settings.deadzone,
    }


def _number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return value


def profile_from_dict(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != VERSION:
        raise ValueError("Unsupported SpaceMouse profile format or version")
    for key in ("mapping", "inversion", "sensitivity"):
        if not isinstance(data.get(key), dict) or set(data[key]) != set(AXES):
            raise ValueError(f"{key} must contain exactly the six physical axes")
    result = NdofSettings(mapping_preset="custom")
    for axis in AXES:
        action = data["mapping"][axis]
        if not isinstance(action, str) or action not in ACTIONS:
            raise ValueError(f"Invalid action for {axis}")
        result.axis_mapping[axis] = action
        inverted = data["inversion"][axis]
        if not isinstance(inverted, bool):
            raise ValueError(f"Invalid inversion for {axis}")
        result.axis_inversion[axis] = inverted
        result.axis_sensitivity[axis] = _number(
            data["sensitivity"][axis], 0.25, 4.0, f"{axis} sensitivity")
    result.sensitivity = _number(data.get("global_speed"), 0.25, 4.0, "Global speed")
    result.deadzone = _number(data.get("deadzone"), 0.0, 0.95, "Deadzone")
    return result


def save_profile(path, settings):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile_to_dict(settings), f, indent=2)
        f.write("\n")


def load_profile(path):
    with open(path, "r", encoding="utf-8") as f:
        return profile_from_dict(json.load(f))
