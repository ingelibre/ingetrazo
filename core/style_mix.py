# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Copy one display-settings category without applying an entire style."""
from __future__ import annotations

from copy import deepcopy

from core.style import Style

# These groups follow the editor's five categories. The style's name is identity,
# not a setting to import from a source. Keep new Style fields in exactly one group.
STYLE_CATEGORIES = {
    "edges": ("edges", "profiles", "back_edges", "edge_color", "profile_width",
              "profile_cap", "depth_cue", "depth_cue_width", "extensions",
              "extension_length", "endpoints", "endpoint_length", "endpoint_type",
              "endpoint_size", "dashes", "edge_color_mode"),
    "faces": ("face_mode", "front_color", "back_color", "material_transparency",
              "transparency_quality", "xray", "xray_opacity", "ambient_occlusion",
              "ao_distance", "ao_intensity"),
    "background": ("background", "sky", "sky_color", "ground_color", "ground",
                   "ground_transparency", "ground_from_below"),
    "watermarks": ("watermarks", "watermarks_visible"),
    "modeling": ("section_fill", "section_fill_color", "color_by_layer", "modeling_colors",
                 "modeling_visibility", "show_guides", "section_cut_width"),
}


def mix_style_category(target: Style, source: Style, category: str) -> Style:
    """Return an independent mixed style, leaving target and source untouched."""
    if category not in STYLE_CATEGORIES:
        raise ValueError(f"Unknown style category: {category}")
    result, sampled = target.copy(), source.copy()
    for field in STYLE_CATEGORIES[category]:
        setattr(result, field, deepcopy(getattr(sampled, field)))
    return result
