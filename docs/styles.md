# Styles and edge settings

Open **Styles** from the Panels toolbar. The window stays open while you work in the model.
Use **Select** to browse Built-in styles or My styles, and **Edit** to adjust the current look.
Changes appear immediately; **Save style…** stores a reusable copy in My styles.

## Faces

On **Edit**, choose **Face settings**. The mode buttons select Textures, Shaded,
Hidden line, Monochrome or Wireframe. Tooltips identify each button. **X-ray** is a
separate toggle: it keeps the selected mode, makes its faces transparent and enables
snapping to entities through faces. Changing modes keeps the toggle's state.
Front and back colors and ambient occlusion keep their existing behavior.

**Material transparency** displays material opacity and texture transparency. Turning it off
draws model materials as opaque without changing their saved paint. Hidden line and Monochrome
draw translucent material faces as solid surfaces too.

**Transparency quality** offers Faster (material batches) and Nicer (transparent triangles
ordered by depth across materials). Nicer trades additional draws for more accurate layering;
its triangle-center sort does not split intersecting triangles. This choice is preserved while
material transparency is off.

**X-ray opacity** sets face opacity from 20% to 80%, with 60% preserving the previous default.
The slider and numeric field stay synchronized and become available while X-ray is enabled. The setting
applies to loose geometry, textures, instances and painted backs. Styles, saved views and the
user style library retain these settings.

## Edges

On **Edit**, choose **Edge settings**, the first category button.

| Setting | Effect |
| --- | --- |
| Edges | Show the model's regular edges. Wireframe always shows edges. |
| Back edges | Show edges behind faces with a dashed stroke. |
| Profiles | Emphasize outlines and silhouettes; choose a width from 1 to 20 pixels and a square or round ending. |
| Depth cue | Make foreground edges thicker than distant edges; choose the foreground width. |
| Edge extensions | Positive values extend strokes; negative values shorten them, from -50 to 50 pixels. A fully shortened stroke disappears. |
| Endpoints | Emphasize each end with the default thickened stroke, or a round, square or triangular marker. Stroke length and marker size are stored separately, from 1 to 50 pixels. |
| Layer line | Show the line patterns assigned in Layers. Turning this off shows those lines as solid. Back edges retain their own hidden-line dash pattern. |

The four profile endings are square flush, round flush, square extended and round extended.
The extended square overhangs by `max(0, width / 2 - 2 px)`; the extended round overhangs by
`width / 2`. Endpoint markers stay aligned with the screen and are drawn once per shared vertex,
including where separate groups meet. An artificial endpoint created by section clipping does
not acquire a marker.

Widths and lengths use screen pixels and remain independent of model zoom. Enlarging an exported
image scales these effects with its line pens. Extensions and endpoint accents change only the
drawing: picking, dimensions and snapping keep using the actual geometric endpoints.

Numeric fields become available when their corresponding effect is enabled. Turning an effect
off preserves its numeric value for the next time it is enabled.

## Edge colors and independent paint

- **All same** uses the color swatch beside the selector.
- **By material** gives priority to each edge's own paint. An unpainted edge takes the average
  color of adjacent painted faces; textures contribute their average image color. A default
  face contributes its group's material when present, otherwise no color. An edge without a
  colored adjacent face falls back to its group's material, then the style's edge color.
  This is a display rule: it does not assign a material to the edge or change its faces.
- **By axis** uses red, green or blue for edges aligned with the active drawing axes. Diagonal
  edges use the style's edge color. Hidden back edges keep the fallback color.

To paint an edge, choose **By material**, pick a material in **Materials**, then click the edge
with **Paint**. Open a group or component before painting its edges individually. A painted edge
in the current edge selection paints that selected set. Clicking a face away from an edge
continues to paint faces as usual.

Use **Alt** with Paint to sample an edge's material. Choose the default material to remove its
independent paint and restore automatic coloring. An automatically colored edge samples its
calculated color. Painting supports Undo and Redo. Switching to All same or By axis preserves
the assigned materials so that switching back restores them.

Styles are stored in `.igz` documents, saved views and the user style library. Independent edge
materials travel with documents, copies, pasted geometry and split edges. They also appear in
the **In the model** material list and participate in material renaming and recoloring.
