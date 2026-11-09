# Snap robustness: which inference wins, and how long it stays

> Status: **OPEN** - nothing in this document is implemented yet. It is the plan
> for the *behaviour* work, and it is deliberately a separate document from
> `docs/snap-pipeline-plan.md`, which records the *structural* refactor now in
> review. That refactor is this plan's prerequisite: every rule of the snap
> search lives in `core/inference.py::InferenceEngine` behind one call site, so
> the policy changes below have a single place to live and a single place to
> test.
>
> Written against issue #368, from a reported case (below), not from theory.
> Phase 0 is measured; its tables and verdict are in *Diagnosis*.
>
> Line numbers are hints and will drift; every claim is anchored to a function
> or attribute name. Trust the names, re-grep the numbers.

## The reported case

A plane is drawn and push/pulled into a parallelepiped whose edges are square
to the axes. The user selects the top-right edge and grabs the endpoint nearest
the camera, to drag that edge leftwards along X.

**Expected**: X engages immediately, and no other
inference appears for as long as the drag stays on X. Another inference shows
up only if the user deliberately goes looking for it.

**Observed**: inference points light up "all over the place" as the cursor
moves, and the axis competes with them instead of silencing them.

Four symptoms. The first three come from the report; the fourth Phase 0 found
while measuring them, and it is the worst of the four.

- **S1 - engagement.** The axis does not take hold at the start of the drag.
  Measured: 1 to 4 steps of `on_face` or of the wrong axis before X takes.
- **S2 - authority.** A cue that is not the axis takes the drag while the axis
  is engaged. Measured on `iso`: the box's own back-bottom corner, 2.5 m off
  the drag line but ~10 px from the cursor, held the drag for 4 steps.
- **S3 - stability.** The firing cue changes as the cursor moves, so the cue
  aimed at is not the cue that fires - and when the displacement ends, the
  working point jumps to wherever the axis has got to meanwhile. Measured: a
  2.8 m jump of the worked point.
- **S4 - wrong axis.** The drag runs along X and the engine answers Z on every
  step of it. Measured on one camera: 30 of 30 steps.

## What the code does today

Four facts read from the code, not inferred from behaviour:

1. **Candidates are ranked by screen distance, in pixel buckets.**
   `compute_snap` (`core/snap.py:1173`) hands each candidate to the nested
   `_consider` (`core/snap.py:1337`), which measures its distance from the
   cursor in pixels and drops anything beyond `threshold_px`. The nested
   `_resolve` (`core/snap.py:1352`) sorts by `floor(d / _TIE_PX)` and takes the
   first candidate that is not occluded. `_TIE_PX` is thus already a
   retention-like idea: inside one bucket, sub-pixel distance stops mattering
   and the order in the list decides.
2. **Within a bucket, append order decides, plus one contextual rule.**
   `_resolve` sorts so that a candidate with no `context` comes first - "a
   derived point never beats the point it derives from" (the 0.4.4 rule, from
   issue #36: a loose vertex beats a component's copy at the same spot). The
   rest is why `compute_snap` considers the named points (`center`,
   `component_origin`, `arc_midpoint`, `core/snap.py:1392`-`1411`) before the
   plain endpoints.
3. **An engaged axis already outranks every discrete point.** The axis/lock
   branch returns a `SnapResult` before the discrete-point ranking is ever
   reached (`core/snap.py:1324`, `return SnapResult(locked, "axis", ...)`, and
   the crossing case above it). So S2 is not, in itself, a missing priority:
   when that branch fires, nothing else is considered at all.
4. **`SnapResult` carries no priority field** (`core/snap.py:60`): `kind`,
   `color`, `axis`, `guide`, `guide_color`, `guides`, `context`, `label`.
   Priority is implicit in the order of consideration and in the bucket sort,
   not stored as a number.

A dwell mechanism already exists in the engine: `InferenceEngine._dwell_on`
(`core/inference.py:260`), `_encourage_dwelt` (`:273`) and `encourage_point`
(`:277`). Its exit conditions (`Viewport.reset()`, geometry deleted) were part
of the refactor's contract, and it is the natural candidate for "the point the
user deliberately returned to".

## Diagnosis (Phase 0, measured)

Phase 0 replaced the hypothesis below with measurements. Both are kept, because
the hypothesis was testable and its verdict is part of the record.

**The hypothesis was**: the axis has authority (fact 3), so the defect must be
engagement - if the axis branch's entry condition does not fire during a drag
along X, `compute_snap` falls through to the distance ranking, and the distance
ranking is what produces the cloud.

**Verdict: half right, and the wrong half is the useful one.**

- The fall-through is real, and S2/S3 ride on it: a *point* took the drag away
  from an engaged axis. But the axis does engage and does hold - 24 of 30 steps
  on `iso`, 26 on `obl-a`, and 30/30 with zero cues off the line on the control
  camera. S1 is not "the axis never fires", it is "the axis fires late".
- The distance ranking is a suspect for a different reason than the hypothesis
  gave. The thief on `iso` is **not** the geometry being dragged. The moving
  edges are excluded correctly - 5 of the 12 dropped, both moving vertices
  absent from the candidate set, and no selection box exists for an edge
  selection, all counted by the probe's `_census`. The thief is a **stationary
  vertex 2.5 m off the drag line**, inside the pixel radius because the radius
  is measured in pixels only, with no regard for how far the candidate sits
  from the axis the user is working on.

One line per camera, dragging the reported gesture (the probe's JSONL
baseline):

| camera | `axis:x` | other axis | cues off the X line | X-Z on screen |
|---|---|---|---|---|
| `top` (control) | 30/30 | 0 | 0 | 33.7 deg |
| `iso` | 24/30 | 1 | 6 | 115.6 deg |
| `obl-a` | 26/30 | 2 | 4 | 107.1 deg |
| `obl-d` | 0/30 | 30 | 30 | 47.2 deg |

The two right-hand columns move together: every camera that produced a cue off
the drag line produced a broken drag, and the one camera that produced none was
flawless. That is the finding Phase 0 exists for, and it is why the fix is
about *the ordering of a cue against the axis*, not about engagement alone.

The fan (`--fan`), which re-aims the same drag by a few degrees, adds two
things:

- **The axis does absorb hand error, where it engages at all.** On `top`, X held
  30/30 at every angle up to 8 deg off, with no dropout. The mechanism is not
  fragile in principle.
- **`obl-d` is a knife edge, and it is not a screen-space tie.** X and Z are
  47 deg apart on screen there, yet Z won all 30 steps; turning the drag 6 deg
  flips the winner completely (at -8 deg: X 30/30; at -4 deg: six dropouts; at
  -2 deg and beyond: Z all 30). The comparison that fails is in *world* terms -
  the cursor's screen direction, mapped through the work plane, lands almost
  half-way between X and Z, and the tie is being broken by the aim rather than
  by a rule.

So the failure modes to fix, in the order they hurt:

- **F1 - engagement (S1).** 1 to 4 steps before X takes; `on_face` on the first
  movement.
- **F2 - a distant point displaces an engaged axis (S2/S3).** On `iso`, steps
  25-28: the corner at (3, 2, 0), 2.5 m off the line, takes the drag; the axis
  returns at (4.51, 0, 1.5), 0.48 m ahead of where it left - a 2.8 m jump of
  the worked point.
- **F3 - the wrong axis wins outright (S4).** `obl-d`, above. Its symptom is
  not F2's: the piece does not jump (largest jump 0.13 m), it travels smoothly
  in a direction ~47 deg away from the hand.

One thing is still unread in the code, and it decides whether Phase 1 and
Phase 2 are really two phases: on `iso` steps 25-28, *why* the axis answer
lost. Fact 3 says the axis branch returns before the ranking is reached, which
implies the axis entry condition stopped firing at exactly those steps - F2
would then be F1 in miniature, the axis dropping out while a point sits inside
its pixel radius. If instead the point branch was reached and outranked the
axis, then fact 3 is conditional and the ordering is the bug. Read
`compute_snap`'s head (`core/snap.py:1173`-`1324`), `_lock_line_snaps`
(`:1098`), `_detect_axis_alignment` (`:185`) and `_detect_axis_on_screen`
(`:220`) next, before writing any rule.

## The rule the fix has to implement

Stated once, because everything below follows from it:

> An engaged strong inference (an axis, a held lock, an acquired reference)
> silences the weak ones while the cursor stays inside its reach. The reach of
> a direction is a narrow cone around it and is generous; the reach of a point
> is a tight disk and is small. Getting a point while an axis is engaged means
> leaving the cone and landing on the point - that is the "deliberately going
> looking for it" of the report.

Two properties make this safe rather than lossy, and both are worth keeping in
view when tuning:

- Inside the cone, a point that *disagrees* with the axis is not what the user
  asked for, so silencing it costs nothing.
- Inside the cone, a point that *agrees* with the axis lies on the axis line,
  where the axis snap and the point snap produce the same result, so there is
  no conflict to resolve and no cue to flicker.

## Plan

Each phase is independently verifiable and can ship on its own.

### Phase 0 - measure before changing  [DONE]

Two instruments, and the grid plan keeps doing its own job:

- `scripts/probe_snap_matrix.py` - the regression net. Unchanged.
- `scripts/probe_snap_gesture.py` - new, and the one that answers this plan. It
  rebuilds the reported gesture (box, top-right edge selected, nearest endpoint
  grabbed, drag along X) across four cameras and replays it through
  `Viewport._refresh_snap`, so the moving-edge exclusion, the work plane and
  the lock projection are all in play. `-o file.jsonl` writes the per-step
  record - the baseline, byte-for-byte reproducible, `--selftest` checks that.
  `--fan` re-aims the same drag in 2-degree steps to measure how much hand
  error the axis absorbs, and prints per camera the on-screen angle between the
  world axes plus a `_census` of exactly what the engine is fed.

Deliverable (the tables in *Diagnosis* above): kinds per step and kinds per
aim, before any code change. It also killed one hypothesis worth recording -
the geometry being dragged does **not** leak into the candidate set - and
replaced it with the one that matters: a *stationary* vertex displacing the
axis.

Baseline: `gesture-base.jsonl`, 120 steps, reproducible.

### Phase 1 - engagement

Make the axis engage from the direction of the drag itself, as soon as the drag
commits to a direction, rather than requiring the cursor to satisfy whatever
the current entry condition asks for.

Deliverable: in the probe's replay, the axis fires on the first movement and
stays fired.

Risk to watch: an axis that engages too eagerly breaks drawing *off* the axis
(the user cannot place a point one pixel to the side). The entry condition
needs a clear answer to "when is the user committed to a direction".

### Phase 2 - authority while engaged

Holding the axis engaged is what makes the early return at `core/snap.py:1324`
do the silencing. If the axis keeps dropping out mid-drag, the fall-through to
the distance ranking keeps happening and S2 survives Phase 1.

This is F2's fix, and Phase 0 measured its shape: the cue that displaces the
axis on `iso` is a *stationary* vertex 2.5 m off the line, so the reach that
has to silence it is measured around the **axis** (in world space), not around
the cursor (in pixels). A cue that is far from the line cannot outrank the
line, however close it is to the mouse.

Deliverable: no non-axis kind in the probe's stream while the gesture stays
inside the cone, and a defined, deliberate way out of the cone.

### Phase 3 - retention when nothing strong is engaged

With no axis in play, the discrete points are still ranked by raw distance,
bucket by bucket, so S3 remains. Apply retention to the weak tier: keep the
last discrete snap until the cursor moves decisively away from it, or until the
dwell mechanism says the user is looking elsewhere. `_TIE_PX` (`core/snap.py`)
is the place where this half-measure already lives.

Deliverable: in the probe's replay of a slow, ambiguous approach to a vertex,
one kind holds instead of alternating.

This is the phase that needs a *time* or *distance* number, and the number is
to be tuned from the probe, not chosen by taste.

### Phase 4 - edges as a continuum

Only now: `on_edge`, `extension`, `perpendicular`, `parallel` and the axis
locks mutually exclude each other over the same pixels, and an edge has no
point to hold. This needs its own retention policy (the line stays, not the
point) *and* an arbitration rule for which linear inference wins. It is
deliberately last: a discrete-point policy that works is a much better
foundation for it than a guess made now.

## Delivery note (ordering, not scope)

This plan refers to a feature (hysteresis) that may change the
`InferenceEngine.snap()` contract only in behaviour, not in signature. Keep it
that way: no new fields on `SnapResult`, no new plugin surface. If a phase
appears to need a signature change, that is a signal the phase is doing too
much at once.

## Open decisions

- **The numbers**: cone angle, point radius, retention distance and time. All
  from Phase 0's baseline, all easy to revise.
- **Is dwell the deliberate search?** The mechanism already exists; either it
  becomes the answer to "the user went looking for a point", or it stays
  independent of snap selection. Decide before Phase 3.
- **Whether S2 is even in scope.** *Answered by Phase 0: yes.* The reported
  case is not purely S1 - a point displaced an engaged axis and the axis had to
  be recovered (F2). Phase 2 is that fix, not a safety net.
- **The tie rule for near-tied world directions.** `obl-d` shows two axes can
  sit nearly equidistant from the drag once it is mapped through the work
  plane, with the winner decided by a few degrees of aim. This needs a
  deterministic rule - prefer the axis whose *world* direction the drag is
  closest to? prefer the axis the grabbed geometry runs along? - rather than a
  better threshold. Decide before Phase 2.
- **What "the axis dropped out" looks like from outside.** F2 needs the axis
  branch's entry condition read directly; today the probe only sees `kind`.
  Decide whether testing the fix needs an inspection point (a counter, a debug
  field) or whether the existing kinds are enough.

## Verification

- **The probes**: `scripts/probe_snap_matrix.py` (the grid, unchanged) and
  `scripts/probe_snap_gesture.py` (the reported gesture, added in Phase 0). The
  gesture probe is the one that has to move: `-o before.jsonl` / `-o after.jsonl`
  and diff, plus `--fan` for the aim sensitivity. `--selftest` must keep
  passing - a baseline that no longer reproduces is not a baseline.
- **Tests**: one test per phase, pinning behaviour at the `InferenceEngine.snap`
  level rather than through the GUI, following the two tests the refactor added
  (`tests/test_extension_api.py`, `tests/test_tape_axis_source_and_guide_segment.py`).
- **The suite**: `python -m pytest -m "not slow"`, the same set CI runs.
- **The gesture itself**, by hand, because this is a behaviour change and the
  reports come from a hand.

## Out of scope

- New inference kinds, or feature expectation beyond what this case needs.
- Touch and stylus input.
- The number of cues drawn at once as a *drawing* decision. If "several
  indicators at the same time" survives Phase 2, the residue is about how many
  cues are painted and which one wins the ScreenTip - a presentation question,
  in `views/viewport.py`, not in the engine.
