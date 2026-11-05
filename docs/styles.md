# Styles window

Open **Styles** from the **Panels** toolbar. The window stays open while you work
in the model. Resize or move it as needed; closing and reopening it during the
same session retains the selected tab, editing category and collection.

The header shows a sample of the current style and its name. The sample is a
small illustration of the style, rather than a rendering of the current model.
**Modified** means the current settings differ from the saved preset.

On **Select**, open **Built-in styles** or **My styles**, then choose a thumbnail
to apply that style to the model. The home button returns to the collections.
**Save style…** saves the current settings under a name in **My styles**;
**Delete** removes a user style from the library, keeping the model's current look.

On **Edit**, the five category buttons organize the existing controls:

- **Edges:** edge visibility and color, profiles, and dashed back edges.
- **Faces:** face mode, front/back colors, and ambient occlusion with distance
  and intensity.
- **Background:** background color, the existing sky switch, and sky/ground colors.
- **Watermarks:** reserved for a later contribution.
- **Modeling:** section fill and its color.

Edits update the viewport immediately. They change display settings, rather than
geometry, and follow the existing style editor's behavior outside model undo.
Presets, user styles, saved views and IGZ persistence retain their existing format.
The View menu and the open editor stay synchronized.

**Mix** is reserved for a later contribution. It displays an explanation and
disabled category targets; it does not mix settings in this first implementation.
