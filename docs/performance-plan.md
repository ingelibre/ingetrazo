# Performance plan — SketchUp-parity fluidity

*Written 2026-08-25, after the piscina.igz marathon. Owner benchmark
(Marco): "SketchUp feels ~2× smoother overall" on the same laptop
(Radeon 780M, Wayland). Goal: close that gap on real project scenes
(200–400k faces) — not on synthetic million-face torture tests.*

## The scoreboard (baseline, measured 2026-08-25)

| Metric | Today | Target |
|---|---|---|
| Paint, clean piscina (283k faces) | 4–22 ms | ≤ 16 ms sustained (60 fps) |
| Paint, 5 hedges (1.2M faces) | 37–40 ms | ≤ 20 ms (instancing + culling) |
| Hover latency (pick+snap, big model) | 25–40 ms | ≤ 10 ms |
| Wheel-zoom gesture start (re-pick) | 25 ms | ≤ 5 ms |
| Cold start to first full paint | ~11 s | ≤ 2 s perceived (progressive) |
| Tile upload hitch during zoom | ~100 ms | none ≥ 33 ms |
| Idle CPU | 0 % ✓ | 0 % (keep watching the 149 % ghost) |

`INGETRAZO_PERF=1` is the measuring stick; every phase lands with its
numbers in the commit message, like the marathon did.

## Why SketchUp feels 2× (honest diagnosis)

1. **Input→photon latency, not raw fps.** Our paints already hit 60 fps
   on clean scenes. What SketchUp does better is the path from gesture
   to frame: their event handling, picking and snapping are native; ours
   cross Python on every mouse move (25–40 ms of hover work before the
   paint even starts). Latency, not throughput, is most of the "2×".
2. **They draw less.** No frustum culling here yet: every chunk is
   submitted every frame even when the camera is inside the house.
3. **Fixed per-frame overhead**: the FBO+blit (forced by the Wayland
   depth bug) plus the QPainter overlay pass cost a few ms that native
   apps don't pay.
4. **Instance geometry is world-baked**: 5 instances of a 230k-face
   hedge = 5× vertex data uploaded and drawn. SketchUp draws one
   definition N times.

## Principles

- **Measure first.** No optimization lands without a before/after from
  the perf log. Phase 0 exists so we stop guessing.
- **Draw less before drawing faster.** Culling and instancing beat any
  library swap.
- **Native code only where the profiler demands it,** as leaf kernels
  behind a stable NumPy-shaped interface — never a rewrite.
- **The Python core is the moat, not the bottleneck to remove.** The
  velocity of this project (solo dev + AI pair) exists BECAUSE the app
  is Python. We keep it.

## Phases

### P0 — Frame telemetry (the microscope) — DONE 2026-08-25 (`4a9de47`)
GL timer queries + per-pass timings (faces / edges / silhouettes /
overlay / blit) and an input-to-paint latency stamp, behind a perf HUD
toggle. The perf log gains `frame gl=..ms ovl=..ms py=..ms lat=..ms`.
*Gate: we can name the top 3 costs of any janky frame in one look.*

### P1 — Frustum culling per chunk (draw less) — DONE 2026-08-25 (`4a9de47`)
Every chunk/instance already has (or can cheaply cache) a bbox; cull
against the view frustum before submitting, vectorized over all bboxes
at once (one NumPy pass, ~µs for hundreds of chunks). Also cull the
pick index the same way for hover rays.
*Gate: camera inside the casita → paint cost drops to the visible
subset; orbiting a corner of a big scene never submits the far side.*

### P2 — GPU instancing for components (the hedge killer) — slice 1 LANDED 2026-08-25 (instanced draw all modes + sections; validated live with 5 copies. Remaining: drop baked per-instance pick arrays via ray transform)
Replace world-baked instance chunks with ONE proto VBO + per-instance
matrices via `glDrawArraysInstanced` + `glVertexAttribDivisor`
(GL 3.3 core ✓). Wins: N hedges cost 1× vertex memory and 1 draw; the
instance chunk build (7.3 s cold for 230k) happens once per PROTO;
Move/Rotate of instances updates a 64-byte matrix, not arrays.
*Gate: 5 hedges paint ≈ 1 hedge + ε; cold start no longer rebuilds
per-instance.*

### P3 — Input latency (the feel) — core LANDED 2026-08-25 (ray-pick chunk prefilter: model 41→1.8 ms, sky 34→0.03 ms; budgeted-hover gate shrinks with it. Deferred: FBO depth-readback for the wheel (superseded — pick is ≤2 ms now), overlay dirty-flag)
- Budgeted hover: hard 10 ms budget — pick against the P1-culled index,
  defer the expensive snap refinements to the trailing-edge timer.
- Wheel focus: depth-readback under the cursor (1 px from the existing
  FBO) instead of the 25 ms CPU ray-pick on gesture start.
- Overlay pass on a dirty flag (skip QPainter entirely on pure camera
  frames with no labels in view).
*Gate: hover ≤ 10 ms on piscina; zoom gesture start indistinguishable
from mid-burst.*

### P4 — Async the stalls — LANDED 2026-08-25 (disk chunk cache: hedge 8.5→0.47 s, scene chunks ~7-8→~1.5 s warm; tile uploads paced 6→2/frame. Remaining: the .igz parse itself (~8 s) is now the cold-open floor)
- Tile/texture uploads staged through PBOs or split across frames
  (≤ 2 ms of upload per frame) — kills the 100 ms zoom hitch.
- Progressive cold start: paint what is chunked, build remaining group
  chunks in a background pass between frames (NumPy releases the GIL
  for the heavy slices) — the app is interactive in ~2 s, the hedge
  pops in when ready.
*Gate: no frame ≥ 33 ms during tile churn; time-to-interactive ≤ 2 s.*

### P5 — Native leaf kernels (only where P0 still complains)
Ranked candidates, each a drop-in behind an existing function:
1. **Triangulation**: swap `core/triangulate.py`'s Python earcut port
   for the official C++ `mapbox_earcut` wheel (pip, all platforms, no
   toolchain) — keep ours as fallback and for the hole-splitting
   preprocessing. Cheapest native win available.
2. **Ray/pick BVH**: a small Rust (PyO3/maturin) or pybind11 module for
   triangle BVH build + query. Only if P1+P3 leave picking on top.
3. **Weld/topology bulk ops**: same criterion.
Watch-list, not plan: free-threaded Python 3.14 (chunk builds across
cores once PySide6 supports it cleanly), Qt RHI.

## What we deliberately do NOT do

- **No C++/Rust rewrite of the app or the engine.** Death by rewrite is
  how solo projects end; the leaf-kernel path gets 80 % of the benefit.
- **No renderer/library swap** (VTK, Qt Quick 3D, ModernGL, wgpu,
  game engines): our draw-call count is already low — the overhead they
  would remove is not where the time goes, and each drags its own
  interaction model that fights the SketchUp feel.
- **No LOD/impostor system yet**: culling + instancing must land first;
  billboard impostors for distant vegetation are a later, separate
  conversation (SketchUp doesn't have them either — it would be a
  leapfrog, not parity).

## First P0 findings (2026-08-25, live piscina session)

Slow frames (25–29 ms) are dominated by the **edges pass** (19–22 ms:
271k-face wireframe lines + silhouettes) — a P3-adjacent target.
Gesture latency measured at 30–70 ms. Culling live: 12–25k tris
dropped while orbiting; paints 5–12 ms.

## Order and sizing

P0 is half a session. P1 and P3 are a session each and pay the most
"feel" per line. P2 is the big one (touches chunks, picks, move/rotate
paths) — a full session with the regression suite as the net. P4 rides
wherever the telemetry points. P5 only on evidence.
