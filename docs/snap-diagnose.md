# Snap diagnose: how the axis loses, read from the code and measured

> Status: **record**. This is a *companion* to `docs/snap-robustness-plan.md`,
> written against the same issue (#368) and the same reported case. The plan
> owns the **policy** - the rule the fix implements and the phases that ship it.
> This document owns the **read of the code** and the **evidence** that the
> plan's *Diagnosis* left as an open question, so that the plan can stay about
> behaviour and not accumulate code spelunking.
>
> Nothing here is implemented. It does not supersede the plan; where the two
> differ, the plan's rule still decides, and this document is the reason to
> revise it, not the revision itself.
>
> Anchors are by function or attribute name; line numbers are hints that drift.
> Trust the names, re-grep the numbers. Structural counterpart:
> `docs/snap-pipeline-plan.md`.

## What this adds

The plan's *Diagnosis* closed with one thing "still unread", and it decided
whether its F2 was a phase of its own or a miniature of F1:

> on `iso` steps 25-28, *why* the axis answer lost ... If instead the point
> branch was reached and outranked the axis, then fact 3 is conditional and the
> ordering is the bug.

This document reads that branch and answers it: **the point branch was reached
and outranked the axis. Fact 3 is conditional.** It also pins the two failure
modes against the two axis detectors and the work plane, and it refines the
`obl-d` reading the plan names in *Open decisions*.

## The three code facts this rests on

**C1 - there are two axis detectors, and the second is a fallback.**
`_detect_axis_alignment` (`core/snap.py:185`) compares the candidate's **world**
delta to the axes and returns a name when it is inside `magnetic_axis_deg`.
That is rule 9a (`core/snap.py:1740`-`1747`), and it returns a `SnapResult`
immediately. The **screen** detector `_detect_axis_on_screen`
(`core/snap.py:220`, floored by `_MIN_AXIS_SCREEN_PX = 12.0`, `:213`) is rule
9b (`:1754`-`1775`) and is reached only when 9a found nothing:

> Deliberately placed after it and only consulted when it found nothing: an
> axis the work plane already offers keeps coming from the world detector, so
> this can only turn a "no inference" into one and never change an answer that
> existed.  (`core/snap.py:1748`-`1752`)

`MoveTool` opts into both: `magnetic_axis_deg = 15.0` (`tools/move.py:205`) and
`screen_axis_px = 9.0` (`tools/move.py:215`). So a world axis answer is never
second-guessed by the pixels that would contradict it.

**C2 - the work plane is chosen by the camera and the hovered face, never by the
drag.** `Viewport._current_work_plane` (`views/viewport.py`) hands the candidate
pipeline a plane it picks from, in order: the tool's `drag_plane`, a captured
`work_plane`, the plane through the active start point
`_start_point_plane` (`:7598`), the near-horizon vertical
`_near_horizon_vertical` (`:7623`), and - ahead of the start-point plane when
the axis check there fails - the face **under the cursor** `_hover_face_plane`
(`:7564`-`7585`). None of these reads the direction the hand is moving. For
`Move` there is an extra tilt: `MoveTool.prefers_vertical_drag = True`
(`tools/move.py:201`), so `_start_point_plane` hands back a plane that
**contains Z** and whose normal is the camera's horizontal heading - the design
intent being "dragging up raises the geometry". The candidate the axis detector
sees is the cursor ray cast onto that plane, so the plane decides which world
deltas are even representable.

**C3 - the magnetic axis sits below the discrete tier, so fact 3 is
conditional.** The plan's fact 3 cites `core/snap.py:1324`, `return
SnapResult(locked, "axis", ...)`. That line is the **Shift-held lock**
(`:1307`, comment `# 3. Shift held + auto axis inference`), one of the *explicit*
locks - it returns before the ranking, and fact 3 is true of it. It is **not**
the magnetic axis. The magnetic axis is 9a (`:1747`), which runs *after* the
discrete tier has already had its turn: the endpoint ranking (`_consider` /
`_resolve`, `:1337` / `:1352`, the `"endpoint"` `_consider`s at `:1426`-`:1427`,
returned at `:1434`) and the edge/guide intersection (`_intersection_snap`,
returned at `:1561`) both sit above 9a.

Consequence: a discrete point inside its pixel radius **can** preempt the
engaged magnetic axis. That is exactly `iso` steps 25-28.

## Measurements

Four cameras, the plan's reported gesture (box, top-right edge selected, nearest
endpoint grabbed, drag along X), replayed through `Viewport._refresh_snap`.
Numbers below are from a throwaway harness that reuses
`scripts/probe_snap_gesture.py::_aim`, then reads `_work_plane_normal()` and
`_last_work_plane` - see *How to reproduce*.

### The work plane and what each axis costs on screen

| camera | grabbed | work-plane normal (at grab) | X px | Y px | Z px |
|---|---|---|---|---|---|
| `top` (control) | (3, 2, 1.5) | ( 0.00, 0.00, 1.00) | 76.7 | 76.7 | 13.5 |
| `iso` | (3, 0, 1.5) | (-1.00, 0.00, 0.00) | 74.3 | 62.7 | 76.9 |
| `obl-a` | (3, 0, 1.5) | (-1.00, 0.00, 0.00) | 47.9 | 71.5 | 86.1 |
| `obl-d` | (0, 0, 1.5) | (+0.94, -0.34, 0.00) | 75.4 | 78.3 | 26.3 |

Two things fall out. First, the plane normal is **not** the same across cameras
and is **not** derived from the drag: `obl-d`'s normal is almost pure **X**
(the plane is `x ≈ const`), so that plane contains Y and Z and **excludes X
entirely**, even though X is the most visible thing on screen there (75 px).
Second, the plane is **re-picked at every cursor hit**, so a single sample at
the grab is not the whole gesture - `iso` starts on the `x = 3` face
(normal `-X`) and drifts (see below). This is why the fix cannot be a constant
"the plane is right" assumption.

### `iso`: the axis engages, then a far point steals it

Axis `x` holds from step 3 to step 24 (`off_x` exactly 0), then:

| step | work-plane normal | kind | point | off X line |
|---|---|---|---|---|
| 1 | (-1.00, 0.00, 0.00) | `on_face` | (3.00, 0.06, 1.46) | 0.07 |
| 2 | (-1.00, 0.00, 0.00) | `axis:z` | (3.00, 0.00, 1.46) | 0.04 |
| 3-24 | (-0.99..-0.82, 0, +0.11..+0.57) | **`axis:x`** | (3.16 .. 4.03, 0, 1.50) | **0.00** |
| 25 | (-0.71, +0.71, 0.00) | `intersection` | **(3.00, 2.00, 0.00)** | **2.50** |
| 26 | (-0.71, +0.71, 0.00) | `endpoint` | (3.00, 2.00, 0.00) | 2.50 |
| 27-28 | (-0.71, +0.71, 0.00) | `intersection` | (3.00, 2.00, 0.00) | 2.50 |
| 29-30 | (-0.71, +0.71, 0.00) | `axis:x` | (4.51 .. 4.56, 0, 1.50) | 0.00 |

The corner `(3, 2, 0)` is a **stationary** box vertex, 2.5 m off the X line but
inside the cursor's pixel radius. It fires at step 25 and holds four steps; the
axis resumes at `(4.51, 0, 1.5)` - exactly the plan's F2 figure. The jump of the
worked point from step 24 to 25 is `|(4.03,0,1.5) - (3,2,0)| = 2.70 m`, the
plan's reported 2.8 m. This is C3 in one table: the point branch returned before
the magnetic axis branch was reached, so the axis was not consulted at 25-28.

### `obl-d`: the drag cannot express X at all

| step | work-plane normal | kind | point | off X line |
|---|---|---|---|---|
| 1-30 | (+0.94, -0.34, 0.00) | **`axis:z`** | (0, 0, 1.61) -> (0, 0, 4.64) | 0.11 -> 3.14 |

The normal does not move: every step of the gesture is cast onto the same
`x ≈ const` plane, the world candidate's X and Y components are pinned at 0, and
the delta is **pure Z** - so 9a reads Z, and 9b (which would have seen X at 75 px
against Z at 26 px) is never reached. All 30 steps answer `axis:z`, `off_x`
grows to 3.14 m, and because the plane is nearly perpendicular to the drag the
piece travels smoothly in a direction ~47 deg from the hand (the plan's F3, "not
F2's").

## The two root causes

- **RC1 - the work plane can exclude the axis the hand is moving along (C2),
  and no fallback notices (C1).** `obl-d`: plane `x ≈ const`, candidate pure Z,
  rule 9a answers Z, rule 9b - the only detector that looks at pixels - is a
  fallback and is skipped. Symptom F3/S4: the wrong axis, outright.
- **RC2 - the discrete tier outranks the engaged magnetic axis (C3).**
  `iso` 25-28: a stationary corner 2.5 m off the line, inside the pixel radius,
  returns before 9a and holds the drag, then yields a 2.70 m jump. Symptom
  F2/S2-S3.

They are independent: RC1 is about *what axis can be offered at all*, RC2 about
*what beats what once it is*. The plan already splits them (Phase 2 = RC2;
Phase 1's engagement and the `obl-d` rule = RC1); the read above is what makes
the split principled rather than a guess.

## What this does to the plan

- **It answers the plan's open question.** `iso` 25-28 lost because the **point
  branch was reached and outranked the axis**, not because the axis entry
  condition stopped firing. So fact 3 is **conditional** - true for the explicit
  locks (`core/snap.py:1324`), false for the magnetic axis (`:1747`). F2 is its
  own failure with its own fix (silence the weak tier around the *axis*, in
  world space - the plan's Phase 2), not a miniature of F1.
- **It refines the `obl-d` reading in *Open decisions*.** The plan says two
  axes "sit nearly equidistant from the drag once it is mapped through the work
  plane". Measured, the world candidate is **exactly Z** (`x = y = 0` at every
  step): it is not a near-tie between X and Z, it is X being **unrepresentable**
  on the chosen plane. The `obl-d` answer therefore is *not* the "tie rule for
  near-tied world directions" the plan proposes for it. It is C2: when the work
  plane removes the drag's screen direction, the world detector's answer is an
  artifact, and 9b should be allowed to override it. Keep the tie rule for a
  genuinely near-tied candidate; `obl-d` is not one (X and Z are 47 deg apart on
  screen, 75 px against 26 px).
- **It explains why the fan "flips" `obl-d` at a few degrees.** A near-
  perpendicular plane has a near-singular screen-to-plane map: a couple of
  degrees of aim move the world candidate from "pure Z" to "pure X". That is the
  same C2 fact, seen from the aim axis.

## How to reproduce

The per-step plane is not in the plan's `gesture-base.jsonl`; it is read live.
Reusing the probe's `_aim`, after each `Viewport._refresh_snap()`:

```python
vp._world_from_pixel(px, py)          # sets _last_work_plane
print(vp._work_plane_normal(), vp.last_snap.kind, vp.last_snap.point)
```

The tables above come from a throwaway harness that does exactly this and prints
one row per step. The right home for it is a `--planes` flag on
`scripts/probe_snap_gesture.py` (a Phase 0/1 deliverable), so the planes are
part of the reproducible baseline rather than a side script.

## Still unread

- **Which `_current_work_plane` branch produced `obl-d`'s plane.** The
  `prefers_vertical_drag` start-point plane and the hovered `x = 0` face give
  the same normal here, so the measurement cannot tell them apart. One print at
  each branch (`_start_point_plane` / `_near_horizon_vertical` /
  `_hover_face_plane`) settles it; it matters only for *where* the C2 fix
  lands, not for *whether* C2 is real.
- **`iso` step 2 (`axis:z`).** A one-step wobble at engagement (`off_x` 0.04);
  likely the same start-of-drag seam the plan calls F1. Not chased here.

## Out of scope

- The policy and the phases - the plan owns those.
- Any fix. This document changes no rule; it only removes the excuse for a
  guess.
