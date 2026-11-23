# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Draws the workflow flow chart with the demo's screenshots, as
workflow-flowchart.drawio (editable in draw.io, images embedded) and
workflow-flowchart.png, one folder up.

    python examples/workflow-demo/create-demo/make_flowchart.py

Needs matplotlib and Pillow (not IngeTrazo dependencies). The screenshots in
images/ come from workflow-demo.igz (see ../README.md).
"""
from __future__ import annotations

import base64
import io
import textwrap
from html import escape
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parents[1]    # examples/workflow-demo
IMG = HERE / "images"
W, H = 720, 420                    # block size
TOP = 182                          # height of the text part of a block
COLS = (40, 880)
ROWS = (70, 540, 1010, 1480)
BLUE = "#1a4d8f"

# key: (col, row, fill, dashed, title, description, example,
#       [(image, caption)])
BLOCKS = {
    "tree": (0, 0, "#dae8fc", False, "Model Tree (Outliner)",
             "The outliner groups all physical elements of the building in a "
             "fixed hierarchy: storey, trade, construction status, element. "
             "Each element exists exactly once, and its position in the tree "
             "says where it is, who builds it and whether it stays, goes or "
             "is new.",
             "GF › Tiles › Tiles_New › Tiles_new",
             [("ui_outliner.png", "Browser"), ("view_model.png", "Model")]),
    "layer": (1, 0, "#fff2cc", False, "Layers",
              "Layers are switches for visibility and colour. They hang on "
              "the containers of the tree, never on single elements, so any "
              "combination can be shown or hidden: one storey, one trade, "
              "only what is new.",
              "S_Existing grey · S_Demolition yellow · S_New red",
              [("ui_layers.png", "Layers")]),
    "bim": (0, 1, "#d5e8d4", False, "BIM Information",
            "BIM data says what each element is (wall, tiles, furniture) and "
            "how much of it there is. Quantities such as areas and volumes "
            "are measured from the geometry, so they stay correct when the "
            "model changes.",
            "Tiles_new → IfcCovering, 2.40 m² · Sink cabinet → IfcFurniture",
            [("ui_bim.png", "BIM ▸ takeoff")]),
    "view": (1, 1, "#e1d5e7", False, "Saved Views (Scenes)",
             "A saved view is a reusable picture of the model: camera, "
             "visible layers, display style and section. It answers one "
             "question, for example “what does the tiler have to do?” or "
             "“what is demolished?”.",
             "V_Tiles (old + new tiles) · V_Kitchen (new kitchen)",
             [("ui_scenes.png", "Scenes"), ("view_tiles.png", "V_Tiles")]),
    "sheet": (1, 2, "#f8cecc", False, "Sheets",
              "A sheet is a printable page that places one or more saved "
              "views at a fixed scale, with a title block and dimensions. "
              "Because the frames point to the views, sheets update by "
              "themselves.",
              "Sheet_Tiles = V_Tiles at 1:25 · Sheet_Kitchen = V_Kitchen at 1:25",
              [("sheet_tiles.png", "Sheet_Tiles")]),
    "set": (1, 3, "#ffe6cc", True, "Sheet Sets (planned)",
            "A sheet set bundles the sheets one trade or tender needs, in "
            "order and with its own cover page. Each trade gets exactly the "
            "drawings it needs, and nothing else. Until the feature exists: "
            "one sheet folder per trade.",
            "Set_Tiler = Sheet_Tiles · Set_Kitchen_fitter = Sheet_Kitchen",
            [("sheet_tiles.png", "Set_Tiler"),
             ("sheet_kitchen.png", "Set_Kitchen_fitter")]),
    "out": (0, 3, "#f5f5f5", False, "Output",
            "The output is what leaves the model: one PDF per trade, images "
            "for the bill of quantities and lists or IFC files. All of it is "
            "generated from the same model, so the documents never "
            "contradict each other.",
            "Kitchen_fitter.pdf · BoQ: tiles 2.40 m²",
            [("sheet_kitchen.png", "Kitchen_fitter.pdf"),
             ("view_kitchen.png", "BoQ image")]),
}
EDGES = [("tree", "layer", "container → layer"),
         ("tree", "bim", "element → attributes"),
         ("layer", "view", "layers on/off"),
         ("view", "sheet", "frame uses view"),
         ("sheet", "set", "select sheets"),
         ("set", "out", "export set"),
         ("bim", "out", "quantities")]


def box(key):
    col, row = BLOCKS[key][:2]
    return COLS[col], ROWS[row]


def image_slots(key):
    """(path, caption, x, y, w, h) for each picture, fitted in the block."""
    x0, y0 = box(key)
    pics = BLOCKS[key][7]
    area_w = W - 40
    slot_w = (area_w - 20 * (len(pics) - 1)) / len(pics)
    out = []
    for i, (name, cap) in enumerate(pics):
        im = Image.open(IMG / name)
        sw, sh = slot_w, H - TOP - 34
        s = min(sw / im.width, sh / im.height)
        w, h = im.width * s, im.height * s
        x = x0 + 20 + i * (slot_w + 20) + (slot_w - w) / 2
        y = y0 + TOP + (sh - h) / 2
        out.append((IMG / name, cap, x, y, w, h))
    return out


def points(a, b):
    (xa, ya), (xb, yb) = box(a), box(b)
    if ya == yb:
        return (((xa + W, ya + H / 2), (xb, yb + H / 2)) if xb > xa
                else ((xa, ya + H / 2), (xb + W, yb + H / 2)))
    return (xa + W / 2, ya + H), (xb + W / 2, yb)


def png(out: Path) -> None:
    fig, ax = plt.subplots(figsize=(16.6, 19.9))
    ax.set_xlim(0, 1640)
    ax.set_ylim(1960, 0)
    ax.axis("off")
    ax.text(40, 30, "IngeTrazo – workflow with the demo model "
            "(room corner: new tiles + sink cabinet)",
            weight="bold", fontsize=15, va="center")
    for key, (c, r, fill, dashed, title, body, ex, _) in BLOCKS.items():
        x, y = box(key)
        ax.add_patch(FancyBboxPatch((x, y), W, H,
                                    boxstyle="round,pad=0,rounding_size=14",
                                    fc=fill, ec="#666",
                                    ls="--" if dashed else "-", lw=1.2))
        ax.text(x + 12, y + 14, title, weight="bold", fontsize=12, va="top")
        lines = textwrap.wrap(body, 84)
        ax.text(x + 12, y + 42, "\n".join(lines), fontsize=9.5,
                va="top", linespacing=1.35)
        ax.text(x + 12, y + 50 + 25 * len(lines), "Example: " + ex,
                fontsize=9, va="top", style="italic", color=BLUE)
        for path, cap, ix, iy, iw, ih in image_slots(key):
            ax.imshow(plt.imread(path), extent=(ix, ix + iw, iy + ih, iy),
                      zorder=3, interpolation="lanczos")
            ax.add_patch(plt.Rectangle((ix, iy), iw, ih, fill=False,
                                       ec="#999", lw=0.6, zorder=4))
            ax.text(ix + iw / 2, y + H - 16, cap, fontsize=8, ha="center",
                    color="#444")
    for a, b, label in EDGES:
        s, e = points(a, b)
        ax.annotate("", e, s, arrowprops=dict(arrowstyle="-|>", lw=1.6))
        if s[1] == e[1]:
            ax.text((s[0] + e[0]) / 2, s[1] - 8, label, fontsize=8.5,
                    style="italic", ha="center")
        else:
            ax.text(s[0] + 8, (s[1] + e[1]) / 2, label, fontsize=8.5,
                    style="italic", va="center")
    fig.savefig(out, dpi=110, bbox_inches="tight")


def data_uri(path: Path, max_w: int = 460) -> str:
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)),
                       Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png," + base64.b64encode(buf.getvalue()).decode()


def drawio(out: Path) -> None:
    cells = ['<mxCell id="title" value="IngeTrazo – workflow with the demo '
             'model" style="text;html=1;fontStyle=1;fontSize=18;" vertex="1" '
             'parent="1"><mxGeometry x="40" y="10" width="900" height="36" '
             'as="geometry"/></mxCell>']
    for key, (c, r, fill, dashed, title, body, ex, _) in BLOCKS.items():
        x, y = box(key)
        label = (f"<b>{title}</b><br>{body}<br><i><font color='{BLUE}'>"
                 f"Example: {ex}</font></i>")
        style = (f"rounded=1;arcSize=6;whiteSpace=wrap;html=1;"
                 f"fillColor={fill};strokeColor=#666666;"
                 f"{'dashed=1;' if dashed else ''}align=left;"
                 f"verticalAlign=top;spacingLeft=10;spacingTop=6;"
                 f"spacingRight=10;fontSize=12;")
        cells.append(f'<mxCell id="{key}" value="{escape(label)}" '
                     f'style="{style}" vertex="1" parent="1"><mxGeometry '
                     f'x="{x}" y="{y}" width="{W}" height="{H}" '
                     f'as="geometry"/></mxCell>')
        for i, (path, cap, ix, iy, iw, ih) in enumerate(image_slots(key)):
            cells.append(
                f'<mxCell id="{key}_img{i}" value="" style="shape=image;'
                f'image={data_uri(path)};imageAspect=0;aspect=fixed;'
                f'imageBorder=#999999;" vertex="1" parent="1"><mxGeometry '
                f'x="{ix:.0f}" y="{iy:.0f}" width="{iw:.0f}" '
                f'height="{ih:.0f}" as="geometry"/></mxCell>')
            cells.append(
                f'<mxCell id="{key}_cap{i}" value="{escape(cap)}" '
                f'style="text;html=1;align=center;fontSize=10;'
                f'fontColor=#444444;" vertex="1" parent="1"><mxGeometry '
                f'x="{ix - 20:.0f}" y="{y + H - 30}" width="{iw + 40:.0f}" '
                f'height="22" as="geometry"/></mxCell>')
    for i, (a, b, label) in enumerate(EDGES):
        cells.append(f'<mxCell id="e{i}" value="{escape(label)}" '
                     'style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;'
                     'endArrow=block;fontSize=11;fontStyle=2;" edge="1" '
                     f'parent="1" source="{a}" target="{b}"><mxGeometry '
                     'relative="1" as="geometry"/></mxCell>')
    xml = ('<mxfile><diagram name="IngeTrazo workflow"><mxGraphModel '
           'grid="1" gridSize="10"><root><mxCell id="0"/>'
           '<mxCell id="1" parent="0"/>' + "".join(cells)
           + "</root></mxGraphModel></diagram></mxfile>")
    out.write_text(xml, encoding="utf-8")


if __name__ == "__main__":
    png(HERE / "workflow-flowchart.png")
    drawio(HERE / "workflow-flowchart.drawio")
    print("Written: workflow-flowchart.png, workflow-flowchart.drawio")
