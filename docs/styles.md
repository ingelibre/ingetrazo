# Styles and edge settings

Open **Styles** from the Panels toolbar. The window stays open while you work in the model.
Use **Select** to browse Built-in styles or My styles, and **Edit** to adjust the current look.
Changes appear immediately; **Save style…** stores a reusable copy in My styles.

## Edges

On **Edit**, choose **Edge settings**, the first category button.

| Setting | Effect |
| --- | --- |
| Edges | Show the model's regular edges. Wireframe always shows edges. |
| Back edges | Show edges behind faces with a dashed stroke. |
| Profiles | Emphasize outlines and silhouettes; choose a width from 1 to 20 pixels. |
| Depth cue | Make foreground edges thicker than distant edges; choose the foreground width. |
| Extensions | Extend strokes beyond their geometric ends by 1 to 50 pixels. |
| Endpoints | Thicken the last 1 to 50 pixels at each end of an edge. |
| Dashes | Show the line patterns assigned in Layers. Turning this off shows those lines as solid. Back edges retain their own hidden-line dash pattern. |

Widths and lengths use screen pixels and remain independent of model zoom. Enlarging an exported
image scales these effects with its line pens. Extensions and endpoint accents change only the
drawing: picking, dimensions and snapping keep using the actual geometric endpoints.

Numeric fields become available when their corresponding effect is enabled. Turning an effect
off preserves its numeric value for the next time it is enabled.

## Edge colors and independent paint

- **All same** uses the color swatch beside the selector.
- **By material** uses each edge's own paint. Unpainted edges inherit their group's material;
  otherwise they use the style's edge color. Face paint does not repaint its surrounding edges.
- **By axis** uses red, green or blue for edges aligned with the active drawing axes. Diagonal
  edges use the style's edge color. Hidden back edges keep the fallback color.

To paint an edge, choose **By material**, pick a material in **Materials**, then click the edge
with **Paint**. Open a group or component before painting its edges individually. A painted edge
in the current edge selection paints that selected set. Clicking a face away from an edge
continues to paint faces as usual.

Use **Alt** with Paint to sample an edge's material. Choose the default material to remove its
independent paint. Painting supports Undo and Redo. Switching to All same or By axis preserves
the assigned materials so that switching back restores them.

Styles are stored in `.igz` documents, saved views and the user style library. Independent edge
materials travel with documents, copies, pasted geometry and split edges. They also appear in
the **In the model** material list and participate in material renaming and recoloring.
