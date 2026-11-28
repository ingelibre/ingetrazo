# Dynamic components

Import a SketchUp dynamic component, edit its exposed parameters, and run
supported click actions in IngeTrazo. The component's attributes and formulas
are saved in IGZ documents. This is an initial compatibility implementation;
it does not implement every SketchUp dynamic-component function.

## Using a component

Install the dependencies in `requirements.txt`, then open or import the SKP
file normally. The **Dynamic components** toolbar provides three tools:

- **Interact** runs the closest nested part's OnClick action when clicked in
  the viewport. Escape cancels an animation. A complete interaction is one
  undoable edit. Saving or starting another command finishes an active
  animation before reading the document.
- **Component options** shows the parameters exposed to users. Edit the
  text fields or lists and choose **Apply**. **Revert** restores the options
  from when the component was selected. Options are also in Properties.
- **Component attributes** opens the authoring sheet for the selected
  component and its nested parts.

The Options banner includes a geometry preview, Name, ItemCode, Summary and
Description when available. Rich text is limited to component information;
parameter labels remain plain text. The preview does not move the modeling
camera or load a remote image.

Both windows follow component selection. Their window controls support
maximize, minimize and restore. Toolbar icons follow the application theme;
selection and axis labels follow the model's active style.

## Editing attributes and formulas

The authoring sheet shows every part in its own rounded, collapsible block.
Use the left tree to navigate, or select a nested part in the viewport. The
tree can be collapsed with its edge handle. Custom attributes appear after
Component info and before the standard Position, Size and other categories.

Choose **Add attribute** in a block to add an attribute to that part. Clicking
a category title adds the whole category, such as X, Y and Z for Position,
without replacing existing values. Adding the first attribute initializes
an ordinary component automatically. Each attribute row has an options icon
for its display label, visibility/editing rule, display units and list choices.

Edit a Value cell directly, or use the synchronized input bar. Start a
formula with `=`, then click another attribute value to insert its reference
at the cursor. For example, enter `=` in part B's Z cell and click part A's
LenZ value to obtain `=A!LenZ`: B's position follows A's height. Navigating
the tree while composing keeps the draft on its original target.

References may address the same part, `parent`, or a uniquely named part
elsewhere in the component. Numbered names such as `Component #1!LenZ` are
accepted. Ambiguous names are not guessed by the insertion tool.

Press Enter or **Apply** to validate and redraw, or Escape/**Cancel** to
discard the draft. Invalid input stays available for correction. The function
picker and **Insert** button insert a signature or operator at the current
cursor/selection. Category headings separate Maths, IngeTrazo, Trigonometry,
Texture, Text, Logic, onClick and Operators. Unsupported entries remain
visible but disabled. Action calls are available only for OnClick attributes.

## Units

**Display in** defaults to **Original**, preserving each imported attribute's
display unit. The selector and cm/inch shortcuts change only the sheet's
display; each block can also use its own display unit. They do not rewrite
formulas, stored lengths or `_lengthunits`. Switching back to Original
restores the imported presentation without creating a document edit.

Length values show their unit suffix in Options, the authoring sheet and
its editors. A value typed without a suffix uses the displayed unit; an
explicit suffix such as `mm`, `cm`, `m`, `in` or `ft` overrides it. Formula
source remains separate from display-unit suffixes.

## Compatibility boundary

- The SKP import path preserves definition dictionaries, instance overrides,
  nesting, hidden parts, materials and shared geometry for dynamic components.
  It requires the OpenSKP definition/model dictionary reader, pinned in
  `requirements.txt`.
- IGZ preserves the imported program, including attributes not understood by
  the evaluator. Unsupported formulas keep their existing values and report
  evaluation problems; preserving metadata does not imply executing it.
- Supported top-level OnClick calls are `SET`, `REDRAW`, `ANIMATE`,
  `ANIMATEFAST`, `ANIMATESLOW` and `ANIMATECUSTOM`. Multiple calls can be
  separated by semicolons. Parsing and evaluation are bounded; no Python
  `eval` or imported code is executed. Unsupported actions reject the whole
  click, and animation durations are limited to 60 seconds.
- Conditional action scripts, `ALERT`, `GOTOSCENE`, additional spreadsheet
  and geometry-query functions, and exact `ANIMATECUSTOM` easing parity need
  further work. The catalogue is not a promise of full function coverage.
- Dynamic SKP export is outside this implementation. No SKP export menu item
  is introduced. Save to IGZ to preserve the program. The existing geometry
  writer remains available internally for separate future work; it does not
  provide dynamic round-trip compatibility.

Any future dynamic SKP writer must preserve the project's free-software
licensing and validate definition and instance dictionaries in both directions.
This implementation uses no proprietary SketchUp SDK or runtime.

## Validation and provenance

Run the focused regression tests with:

```bash
python -m pytest -q tests/test_dynamic_components.py tests/test_dynamic_interaction.py tests/test_dynamic_authoring_ui.py
```

The tests cover imported dictionaries and independent instances, formula
evaluation, inline references, category additions, display units, selection
tracking, block layout, function insertion, nested picking, animation
transactions, cancellation, Undo/Redo and saving during animation. SKP import,
history, model-style and outliner regressions provide additional coverage.
Run the repository-wide fast suite using the batching runner documented in
`CONTRIBUTING.md`.

This implementation includes the foundation from
[IngeTrazo PR #1617](https://github.com/ingelibre/ingetrazo/pull/1617), by
Gabriel Rodríguez Arregin, retaining its history and attribution. That work
adapts [d1rty-pixel's Dynamic Components](https://github.com/d1rty-pixel/ingetrazo-dynamic-components)
and [moominot's dc_tools](https://github.com/moominot/ingetrazo-skp-dc-import).
The placement metadata uses the latter's `skp_dc_import` layout in
`group.ext["skp_dc_import"]`. Existing copyright and licensing notices remain
in the source. The SKP dictionary reader comes from
[OpenSKP #530](https://github.com/iamahsanmehmood/openskp/pull/530).

Private reference models and development launchers are not included.
