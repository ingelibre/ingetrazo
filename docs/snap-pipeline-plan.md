# Snap pipeline: separating inference from rendering

> Status: **DONE.** All six steps landed:
> **1** (freeze the contract), **2** (one `compute_snap` kwargs list),
> **3** (extract the engine), **4** (move the two post-processors behind
> `engine.snap()`), **5** (retire the duplicate body) and **6** (this doc).
> The seam is closed: `InferenceEngine` owns every rule of the snap search,
> and `Viewport` delegates.
>
> Behaviour is unchanged by design: this is a structural refactor. The batched
> sweep that verified it is recorded under **Verification**, with its one
> pre-existing (non-snapping) failure. The full suite was not run in one go -
> CI runs the fast suite (`python -m pytest -m "not slow"`, per
> CONTRIBUTING.md).
>
> Part of #368. Every claim below is anchored to a **function or attribute
> name**; line numbers are hints and will drift - trust the names, re-grep the
> numbers.

## Objective

Split the snapping stack into two layers with one clean seam:

1. **Inference engine** - pure "what point does the cursor snap to?" logic plus
   the accumulated reference state (hovered edge, acquired points, encouraged
   points, centre reference, axis lock...).
2. **Presentation** - QPainter drawing of whatever inference produced
   (`_draw_snap_indicator`, the circle-centre dot, labels).

The goal is *not* to rewrite snapping. The goal is to remove the duplication and
the mixing, so that (a) there is **one** code path that runs inference, and
(b) rendering never has to know how a snap was computed - only how to draw a
`SnapResult`.

**Step 3 delivered (1).** Rendering was already clean and stays clean.

## Where the code stands now (after step 4)

### The two files

- `core/inference.py` (**new**, 285 lines): `class InferenceEngine`, the
  collaborator. No QPainter, no GL, no drawing. Its module and class
  docstrings say what it owns and why. Module-level imports are `QtCore` /
  `QtGui` and `core.snap`; the two post-processors add `core.axes` and
  `logging` **lazily**, inside the method (step 4), so the no-drawing claim
  still holds.
- `views/viewport.py`: event routing, drawing, and a **bridge** of delegating
  properties. The reference state is no longer declared in `__init__`, and
  `compute_snap` is no longer imported.

### `InferenceEngine` - the state it owns

Moved verbatim (meaning *and* comments) out of `Viewport.__init__`:

| Attribute | Meaning |
| --- | --- |
| `axis_lock` | arrow-key lock: `None` / `"x"` / `"y"` / `"z"` |
| `last_snap` | the last `SnapResult`, kept for the marker and the readouts |
| `reference_edge`, `reference_mode` | the Down-arrow parallel / perpendicular reference, and the mode it was taken in |
| `_shift_lock` | sticky Shift inference lock: `(direction, color)` |
| `_hover_edge` | edge under the cursor (highlight + capture candidate) |
| `_hover_center` | centre of the last circle / arc the cursor visited |
| `_center_ref` | `(centre, radius, key, version, source, mesh, group)` |
| `_acquired_edge`, `_acquired_face_normal` | soft references held while a segment is being drawn |
| `_acquired_point` | the "from point" corner |
| `_encouraged` | the last two points the cursor *paused* on |
| `_dwell_point`, `_dwell_timer` | the pause that turns a point into an encouraged one |

### `InferenceEngine` - the methods it owns

| Method | What it is |
| --- | --- |
| `__init__(viewport)` | the state above + `QTimer(viewport)` at `viewport.ENCOURAGE_MS`, whose `timeout` is `_encourage_dwelt` |
| `acquire(px, py)` | the picking block lifted out of `_process_hover`: hover edge, hover centre, and the mid-draw soft references |
| `snap(px, py, modifiers)` | raycast + `compute_snap(...)` (the single kwargs list) + the two post-processors; returns `Optional[SnapResult]` |
| `_axis_source_cue(snap, px, py)` | the "on axis" cue of the tools that read the model axes as a source, applied after the search |
| `_extension_snap(snap, px, py)` | the extension providers' hook, applied last, behind the frozen `_NAMED_SNAPS` set |
| `_dwell_on(point)` | (re)start / stop the pause over a point |
| `_encourage_dwelt()` | the timer's slot |
| `encourage_point(point)` | make a point the newest encouraged one (two kept), set it as the acquired point, repaint |

Deviations from the original sketch, recorded so nobody "fixes" them back:

- `acquire(px, py)` takes **no** `modifiers` - nothing in the block used them.
- The public name is `encourage_point` (as it was on the viewport), not
  `encourage`.
- `snap()` returns exactly what `_snap_at` returned, `None` included, so
  `_build_ctx`'s early return and `_refresh_snap`'s early return keep working
  unchanged.

### The bridge on `Viewport`

- `self.inference = InferenceEngine(self)` is built in `__init__`, right after
  `self.history = History(self.scene)` - *before* `active_tool` and before the
  threshold attributes. That is safe: the engine reads all of those at call
  time, never at construction (it only reads the class attribute
  `ENCOURAGE_MS`).
- **Delegating properties**, getter *and* setter, so the old attribute names
  keep working everywhere: `axis_lock`, `last_snap`, `reference_edge`,
  `reference_mode`, `_shift_lock`, `_hover_edge`, `_hover_center`,
  `_center_ref`, `_acquired_edge`, `_acquired_face_normal`, `_acquired_point`,
  `_encouraged`, `_dwell_point`, `_dwell_timer`.
- **Thin wrappers**: `_dwell_on`, `_encourage_dwelt`, `encourage_point`, and
  - after step 4 - `_axis_source_cue`, `_extension_snap`.
- **Entry points**: `_process_hover` calls `self.inference.acquire(...)`;
  `_snap_at` is one line, `return self.inference.snap(...)`; and `_build_ctx`
  and `_refresh_snap` both go through `_snap_at` - which is what closed steps 2
  and 5 (there is exactly one `compute_snap` kwargs list, in the engine).

### One code path, as intended

`compute_snap(` has exactly **one** production call site now:
`core/inference.py::InferenceEngine.snap`. `views/viewport.py` mentions it only
in prose. Re-verify with:

    grep -rn 'compute_snap(' --include='*.py'

(every other hit is under `tests/`).

### The delegation is load-bearing: who still pokes the state

The viewport's own routines were left untouched; they keep reading and writing
`self.axis_lock`, `self.last_snap`, ... and land in the engine through the
properties. The hits worth knowing (names, not lines):

- **clears**: `set_active_tool`, `set_document`, `set_nav_mode`,
  `release_constraints`, `_release_axis_lock_after_operation`;
- **keys**: `keyPressEvent` (toggles `axis_lock`), `_cycle_reference_mode`
  (reads `_hover_edge`, writes `reference_edge` / `reference_mode`),
  `_capture_shift_lock` (reads `last_snap`, writes `_shift_lock`);
- **hover**: `_process_hover` writes `last_snap = ctx.snap` and reads
  `_hover_center` to feed `_dwell_on`;
- **drawing** (read-only): `_draw_overlay` (`last_snap`,
  `_valid_center_ref`, `axis_lock`, `reference_mode`), `_draw_rubber_band`
  (`last_snap`), `_draw_axis_lock_label`, `_draw_reference_label`.
- **One ordering constraint, not an accident:** `engine.acquire` assigns
  `self._hover_edge` *before* calling `vp._update_center_ref(px, py)`, because
  that method reads `self._hover_edge` (through the property) to decide which
  of the new batch of circles to fit. Reorder `acquire` and the centre fit
  silently goes blind.

### What is still on the `Viewport` (picking + presentation)

- `pick_axis(px, py)` - a *general* pick (it needs `_clip_segment_front`,
  `_world_to_pixel`, `pick_threshold_px`, `core.axes`) that the Tape reads
  too, so it stays a viewport service; **the engine calls it** - the shape of
  `_snap_scene` / `pick_face_any` (the decision step 4 had to take).
- `_ext_snap_providers` - the provider list, filled by
  `ExtensionApp.add_snap_provider`; the engine reads it off the viewport
  rather than owning it, so `extension_api` keeps registering on the
  viewport (the same shape as `pick_axis`).
- `_axis_source_cue` / `_extension_snap` - **thin one-line delegates now**;
  the rules live in `InferenceEngine`, beside the rest. They stay on the
  viewport's surface because the extension tests and the probe call them
  from there.
- `_update_center_ref` / `_valid_center_ref` / `_center_hint_px` - the centre
  *fit* stays on the viewport (it walks the chunk); the engine only stores
  (`_hover_center`, `_center_ref`) and reads. Note `_valid_center_ref` is a
  reader with a side effect: it refreshes `_center_ref` when new circles
  appeared.
- **Presentation**, untouched and still ignorant of inference:
  `_draw_snap_indicator` (marker per `snap.kind` + label), the centre-dot block,
  `_draw_inference_marker`, `_draw_guides`, `_draw_reference_label`,
  `_draw_axis_lock_label`, `_draw_inference_label`, `_draw_linear_mode_label`.
  They read only `last_snap` / `_center_ref`.

**The closed seam** - the tail of `InferenceEngine.snap`, and now the only
place the cue and the extension hooks run:

```python
snap = self._axis_source_cue(snap, px_x, px_y)
snap = self._extension_snap(snap, px_x, px_y)
return snap
```

`Viewport._axis_source_cue` / `._extension_snap` survive as one-line
delegates (`return self.inference.<same>(...)`), so the extension tests and
the probe keep calling them through the viewport.

Mind the homonym: `core.snap._extension_snap` (called at step 5 of
`compute_snap`) is the *geometric* extension inference - an edge's dashed
continuation and its green connection points. `InferenceEngine._extension_snap`
is the *extension-API* provider hook. Different things, same name, one file
each.

### Contract surface (what the engine talks to)

Enumerated so step 4 - or a future "host protocol", which is the *clean* version
of the engine owning the viewport - can be scoped without re-grepping:

- `acquire`: `viewport.active_tool`, `pick_edge`, `pick_edge_any`,
  `_update_center_ref`, `pick_vertex`, `pick_face_placement`,
  `core.snap.face_plane_world`.
- `snap`: `viewport._world_from_pixel`, `active_tool`, `_snap_scene`,
  `_world_to_pixel`, `snap_threshold_px`, `_project_to_lock_line`,
  `inference_angle_deg`, `_is_occluded`, `pick_face_any`,
  `edge_snap_threshold_px`, `linear_inference_mode`, `_work_plane_normal`,
  and - for the post-processors - `pick_axis` and `_ext_snap_providers`.
- the active tool: `uses_snap`, `start_point`, `chain_first_point`,
  `magnetic_axis_deg`, `screen_axis_px`, `radial_arm`, `axis_source`,
  `hover_group_edges`.
- Qt: `QTimer(viewport)` and `viewport.update()` (in `encourage_point`).
- and the reverse direction: `acquire`, `snap`, the 14 properties, the 5
  wrappers (`_dwell_on`, `_encourage_dwelt`, `encourage_point`,
  `_axis_source_cue`, `_extension_snap`).

## Target architecture (as originally sketched - now mostly true)

```
class InferenceEngine:
    def __init__(self, viewport): ...            # needs scene/camera/pick access only
    # the reference state table above MOVES HERE
    def acquire(self, px, py): ...               # the picking block in _process_hover
    def encourage_point(self, point): ...        # _dwell_on / encourage_point
    def snap(self, px, py, modifiers) -> SnapResult:
        # = the single, unified body of today's _build_ctx + _refresh_snap:
        #   world_raw = raycast
        #   compute_snap(...)
        #   self._axis_source_cue(...)
        #   self._extension_snap(...)
```

`Viewport` keeps only event routing -> `tool.on_*`, and drawing. `_build_ctx`
shrinks to a thin bridge; `_refresh_snap` becomes a `snap` call - deleting the
duplicate argument list. **All of that is true today**, the two
post-processors included.

The shrinking bridge, as shipped (it goes through `_snap_at`, which is the
one-liner onto the engine):

```python
def _build_ctx(self, ev) -> Optional[ToolContext]:
    self._sync_axes()
    p = ev.position().toPoint()
    snap = self._snap_at(p.x(), p.y(), ev.modifiers())
    if snap is None:
        return None
    return ToolContext(
        viewport=self, world=snap.point, screen=ev.position(),
        modifiers=ev.modifiers(), snap=snap)
```

## The shape before the extraction (investigation pass - kept for the *why*)

### Two near-identical copies of the inference call

- `_build_ctx(self, ev)` - the live one; called from `_process_hover`,
  `mousePressEvent`, `mouseReleaseEvent`, `mouseDoubleClickEvent` and
  `_dispatch_tool_click`.
- `_refresh_snap(self)` - re-runs the *same* `compute_snap(...)` with the last
  known cursor position; called from `keyPressEvent` / `keyReleaseEvent` when a
  modifier / lock / reference changes (arrows, Shift, Alt, Esc), and from
  `set_active_tool`, `release_constraints` and `_release_linear_mode`.

Each carried its own ~50-line copy of the whole `compute_snap(...)` keyword
list. **That duplication was *the* structural bug**, and it is gone: both now
call `_snap_at` -> `InferenceEngine.snap`.

### The inference core (unchanged, still `core/snap.py`)

    core.snap.compute_snap(candidate_world, candidate_pixel, scene,
        world_to_pixel, threshold_px, edge_threshold_px, project_onto_line,
        chain_first_point, start_point, axis_lock, shift_held, reference_edge,
        reference_mode, inference_angle_deg, is_occluded, face_under_cursor,
        magnetic_axis_deg, screen_axis_px, acquired_edge, acquired_point,
        acquired_face_normal, acquired_points, shift_lock_dir, shift_lock_color,
        linear_mode, work_plane_normal, radial_arm) -> SnapResult

Pure, already decoupled, and unit-tested directly by a dozen `tests/test_snap_*`
and `tests/test_axis_*` files. **Do not touch its signature casually** - those
tests call it by keyword.

### The output seam (reused as-is)

- `SnapResult` (`core/snap.py`) - the contract between engine and drawing.
  Fields: `kind, point, color, axis, guide, guides, guide_color, context,
  label`. Rendering switches only on `kind`.
- `ToolContext` (`tools/base.py`) - the contract with tools: `world`, `snap`,
  `screen`, `modifiers`, `viewport`.

### The state table, before the move (for reference)

| State | Was written in | Was read by |
| --- | --- | --- |
| `axis_lock`, `reference_edge`, `reference_mode` | `keyPressEvent` | `compute_snap` |
| `_shift_lock` | `_capture_shift_lock` | `compute_snap` |
| `_hover_edge`, `_hover_center`, `_acquired_*` | `_process_hover` | `compute_snap` |
| `_encouraged`, `_dwell_point`, `_dwell_timer` | `_dwell_on`, `_encourage_dwelt`, `encourage_point` | `compute_snap` |
| `_center_ref` | `_update_center_ref`, `_valid_center_ref` | `_snap_scene`, `_draw_overlay` |
| `last_snap` | `_build_ctx` / `_refresh_snap` | `_draw_overlay`, `on_hover` |

After step 3 every row lives in `InferenceEngine`; the writers and readers still
on the `Viewport` reach them through the delegating properties.

## Migration steps (each independently verifiable)

1. **Freeze the contract. [DONE]** Confirm nothing outside the viewport
   constructs the `compute_snap(...)` kwargs. **Result (verified):** the only
   production call-sites were `views/viewport.py::_refresh_snap` and
   `::_build_ctx` (2 sites); every other call-site is in `tests/`;
   `core/snap.py` is the sole definition; no call-site under `plugins/ tools/
   georef/ formats/ analysis/ scripts/`; no dynamic dispatch
   (`getattr(..., "compute_snap")`, no alias, no string reference). => the
   kwargs contract was safe to refactor behind one path.
2. **De-duplicate first (no behaviour change). [DONE]** Make `_refresh_snap`
   and `_build_ctx` share one helper. **Closed by step 3**: both call
   `_snap_at`, and `_snap_at` is the engine. (`_refresh_snap` uses
   `QGuiApplication.keyboardModifiers()`; `_build_ctx` uses `ev.modifiers()` -
   that difference is preserved.)
3. **Extract the engine. [DONE]** The reference state and the unified
   `acquire` / `snap` / `encourage_point` live in `core/inference.py`; the
   `Viewport` keeps the thin delegating properties so tools, extensions, the
   probe and the tests that poke these attributes kept working during the
   move. Verified on the snap / centre / extension / pick-index tests.
4. **Move the post-processors behind `engine.snap()`. [DONE]** The two rules
   (and `_NAMED_SNAPS` with the second) moved into `core/inference.py`, beside
   `snap`, which now calls `self._axis_source_cue(...)` /
   `self._extension_snap(...)` as its last two statements. Both decisions the
   step flagged were taken and are recorded under **Risks**: `pick_axis` stays
   a viewport service the engine calls, and the provider signature stays
   `fn(viewport, snap, px, py)` - the engine hands each provider the
   **viewport**, so **no plugin change** was needed.
   `Viewport._axis_source_cue` / `._extension_snap` survive as one-line
   delegates, because the extension tests call them from there.
5. **Retire the duplicate body. [DONE]** Fell out of step 3: `_build_ctx` and
   `_refresh_snap` no longer carry a kwargs list. Presentation untouched.
6. **Update the doc. [DONE]** This file is it: the status block says done, the
   seam excerpt shows the closed seam, step 4's decisions are under **Risks**,
   and the sweep that verified it is under **Verification**.

## Verification

- After step 3 (all green): 109 passed, 1 skipped on the snap / centre /
  extension / pick-index files, and a 38-test subset re-run after the last
  edit.
- After step 4: the two edited test files on their own (12 and 17 passed),
  then the sweep that stands in for the full suite - every `tests/*.py` that
  mentions `_snap_at`, `inference.`, `pick_axis`, `_extension_snap`,
  `_axis_source_cue`, `_process_hover`, `compute_snap`, `_ext_snap_providers`
  or `active_tool` (63 files), run in three batches:

      # 1. the snap core - 120 passed. Explicit files, not tests/test_snap_*.py:
      #    that glob also picks up test_snap_extension.py, which ran on its own
      #    (with the extension tests) and is not part of the 120.
      python -m pytest -q tests/test_snap_from_point_first_click.py \
        tests/test_snap_under_lock_both_sides.py \
        tests/test_snap_level_with_point_across_walls.py \
        tests/test_snap_protractor_arm.py tests/test_snap_origin_under_lock.py \
        tests/test_snap_intersection.py \
        tests/test_snap_excludes_moving_geometry.py tests/test_center_inference.py \
        tests/test_acquired_edge_sticky.py tests/test_alt_inference_toggle.py \
        tests/test_origin_beats_linear_inferences.py \
        tests/test_rafael_rev4_inferences.py \
        tests/test_from_point_during_an_operation.py tests/test_viewport_snap.py
      # 2. axes and guides - 106 passed, 1 pre-existing failure (below)
      python -m pytest -q tests/test_axis_*.py tests/test_close_under_axis_lock.py \
        tests/test_tape_axis_source_and_guide_segment.py tests/test_guide_visibility.py \
        tests/test_lock_takes_guide_height.py tests/test_shift_lock_has_snaps.py \
        tests/test_local_axes_drawing.py tests/test_group_face_inference.py \
        tests/test_perp_on_slope.py tests/test_shared_point_prefers_the_drawing_context.py \
        tests/test_ctrl_guide_toggle.py
      # 3. extensions, plugins and the tools that snap - 213 passed
      python -m pytest -q tests/test_extension_api_v2.py tests/test_plugin_loader.py \
        tests/test_pick_index.py tests/test_pushpull_snaps_to_guides.py \
        tests/test_pushpull_click_on_the_cap.py tests/test_scale_grips_snap.py \
        tests/test_fillet_tool.py tests/test_planar_tools_follow_the_view.py \
        tests/test_workplane_horizon.py tests/test_walkthrough.py \
        tests/test_bench_0_4_9_followups.py tests/test_first_person.py \
        tests/test_paste.py tests/test_repeat_last_command.py \
        tests/test_cursor_after_operation.py tests/test_esc_cascade.py \
        tests/test_pushpull_instances.py tests/test_pushpull_ux.py

  **Nothing red in the snap path.** The one failure,
  `tests/test_ctrl_guide_toggle.py::test_the_status_bar_keeps_the_ctrl_clause_up`,
  is pre-existing and environmental: it compares `QFontMetrics.horizontalAdvance`
  of the Tape hint against `statusBar().width() * MESSAGE_SHARE`, and the font in
  this shell renders the hint 1440 px wide into an 815 px bar. No snapping code
  is on that path (it is a status-text width assertion), and sweep batch 2 above
  re-ran all of it after the snap work landed.
- Two new tests pin the rules step 4 moved, so the extraction cannot be undone
  silently:
  `tests/test_tape_axis_source_and_guide_segment.py::test_the_axis_cue_rule_lives_in_the_engine`
  (the rule is the engine's, the viewport's name for it is a delegate, and
  `pick_axis` is still the viewport service the engine calls) and
  `tests/test_extension_api.py::test_a_provider_is_handed_the_viewport_not_the_engine`
  (the provider signature).
- Full suite: not run in one go. The sweep above covers every `tests/*.py`
  that touches the snap path; CI runs `python -m pytest -m "not slow"` (the
  fast suite, per CONTRIBUTING.md).
- Behaviour probe: `scripts/probe_snap_matrix.py` (it drives
  `Viewport._refresh_snap`, so it exercises the new path).
- Stub viewports in tests bind individual methods (`_world_to_pixel`,
  `_valid_center_ref`, `_center_hint_px`, `_snap_scene`, ...). The engine calls
  them on the viewport, so the stubs keep working; if the engine ever
  method-ises any of them, update the stubs. `tests/test_center_inference.py`
  has the list of names it patches.

## Risks / open questions

- **Resolved:** "engine owns the viewport, or a host protocol?" - it owns the
  viewport (`self.viewport`), as the simplest first cut. The contract surface
  above is what a protocol would have to cover if it is ever wanted.
- **Resolved:** the dwell timer stays a Qt object parented to the viewport and
  simply calls `engine.encourage_point()`. `ENCOURAGE_MS` is still a viewport
  class attribute.
- **Resolved (step 4):** `pick_axis` did **not** move. It is a general pick (it
  uses `_clip_segment_front`, `_world_to_pixel`, `pick_threshold_px`) that the
  Tape reads too, so it stays on the viewport and the engine calls it - the
  same shape as `_snap_scene` / `pick_face_any`. Same for
  `_ext_snap_providers`: the engine reads the list off the viewport, so
  `add_snap_provider` keeps its home.
- **Resolved (step 4):** the provider signature stayed
  `fn(viewport, snap, px, py)`, deliberately: the engine hands each provider
  the **viewport**, not itself, so a plugin never learns the extraction
  happened. Pinned by
  `tests/test_extension_api.py::test_a_provider_is_handed_the_viewport_not_the_engine`.
- **Open:** the delegating properties are the transition crutch. Nothing forces
  retiring them, but if they are, the writers to fix first are the clears in
  `set_active_tool` / `set_document` / `set_nav_mode` and the key handlers -
  those would talk to `self.inference.<attr>` directly.
- Line numbers quoted in older revisions of this file are stale; re-grep by
  name.
