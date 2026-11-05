# Styles and display settings

Open **Styles** from the Panels toolbar. The window stays open while you work in the model.
Use **Select** to browse Built-in styles or My styles, and **Edit** to adjust the current look.
Changes appear immediately; **Save style…** stores a reusable copy in My styles.

## Mixing styles

On **Mix**, browse **Built-in styles** or **My styles** and select a source.
Selecting a source only samples it. Click a category to copy that category's
settings into the current style, or drag the source thumbnail onto its category.
You can take edges from one style, faces from another and a background from a third.

The five categories match the Edit tab. Faces include X-ray, transparency and
ambient occlusion; Modeling includes cue colors, visibility and section fill.
Watermarks replaces the image collection and its display switch with the source's
embedded images, masks and layer order. Modeling applies only the scene visibility
overrides explicitly stored in the source; older styles without them keep current
document visibility.

Mixing preserves the current style's name and settings from other categories.
Source styles remain unchanged. The result appears immediately and **Save style…**
stores it as a reusable style. Further edits and saved views/documents retain the
combined settings without needing the original source styles.

## Modeling

On **Edit**, choose **Modeling settings**. The color swatches control selected
geometry, the selection outline of locked objects, guides, active/inactive section
frames and section-cut lines. A chosen selection color replaces the automatic
contrast color; untouched styles keep their existing selection behavior.
Without a section-cut color override, cut lines follow the style's edge color.

**Section cut width** ranges from 1 to 20 screen pixels (default 2.5). Width stays
constant in perspective and parallel views and scales with exported line pens.
The existing **Section Fill** switch and color remain below these controls.

The visibility checkboxes control hidden geometry, section planes, section cuts,
guides and model axes. They share their live state with the View/Camera menus.
Hiding guides also removes them from picking and inference; the guides themselves
are retained. Hiding hidden geometry removes hidden entities from the selection.
**Color by layer** displays layer colors in Textures/Shaded without repainting faces;
Hidden line, Monochrome and Wireframe retain their own appearance.

These settings travel with saved styles, views and IGZ documents. Older styles
without modeling visibility overrides retain the document's current visibility.
Photo-matching display controls require a separate photo-matching feature.

## Watermarks

On **Edit**, choose **Watermark settings** and **Add image…**. PNG, JPEG, BMP and
WebP images are embedded in the style, so moving or deleting the original image
does not remove the watermark from saved styles, views or IGZ documents.

**Display watermarks** controls the whole collection; **Visible** controls the
selected image. Name, opacity, placement and scale update the model immediately.
Choose **Behind model** for a background or **In front of model** for an overlay.
The **Model space** row separates foreground images above it from background
images below. Use the arrow buttons to move an image across this boundary or move
Model space past an image; its foreground/background setting updates automatically.
Within each side, the top image appears on top. **Delete** removes the selected
image. Model space represents the model and cannot be deleted or edited as an image.

**Create mask** uses the image's brightness as a mask: white is transparent,
black paints the style's background color and gray is partially transparent.
The image's existing alpha is preserved and **Opacity** still applies. The
original embedded image is retained, so unchecking the option restores it.

**Positioned** offers nine anchors and a width relative to the viewport, preserving
the image's proportions. **Stretched** fills the viewport; **Keep aspect ratio**
fills it without distortion, cropping any excess. **Tiled** repeats the image
at the chosen scale. Disabled placement controls retain their values.

Images stay fixed on screen during orbit and zoom, and scale with exported views.
Background images sit behind model geometry and the display ground; foreground
images cover the model but remain below the application's interactive drawing cues.
None of these image layers becomes model geometry or a snapping target.

## Background

On **Edit**, choose **Background settings**. Pick the background color and turn
**Sky** and **Ground** on or off independently. Their color swatches stay editable
while disabled, so a color can be prepared before displaying it.

The ground is an infinite display plane at Z = 0. **Ground transparency** ranges
from 0% (opaque) to 100% (invisible); intermediate values reveal geometry below it.
Faces above the plane keep their appearance, including transparent materials.
**Show ground from below** controls whether the plane is visible from underneath.
Turning Ground off retains its transparency and underside setting.

These settings travel with styles, saved views, the style library and IGZ documents.
Old styles retain their original combined sky/ground backdrop until a background
toggle or ground setting is edited. Maps, terrain and photogrammetric surveys keep
their own ground; the display plane does not add model geometry or snapping targets.

## Faces

On **Edit**, choose **Face settings**. The mode buttons select Textures, Shaded,
Hidden line, Monochrome or Wireframe. Tooltips identify each button. **X-ray** is a
separate toggle: it keeps the selected mode, makes its faces transparent and enables
snapping to entities through faces. Changing modes keeps the toggle's state.
**Alt+X** and the View menu's X-ray action control the same option. Turning it off
retains the selected mode, edge settings and any edits made while it was active.
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

Older saved styles using X-ray as their face mode load as Textures with X-ray enabled.
Their previous 60% face opacity is preserved unless a different opacity was saved.

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
