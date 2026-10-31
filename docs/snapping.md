# Snapping contracts and regression coverage

`core/snap.py` chooses a target in world coordinates using screen-space
distances. `core/inference.py` supplies the viewport's projection, visibility,
work-plane and acquired-reference state. The engine returns a `SnapResult`;
its kind, context and lock color are part of the result, alongside its point.

## Point targets under a direction lock

Arrow keys, a captured Shift direction and a parallel/perpendicular reference
share the same point selection policy as free snapping:

1. The chain's first point closes the drawing when it lies on the lock line
   and within the point radius. This live drawing point is deliberately exempt
   from scene occlusion checks.
2. Visible named points, the world origin and endpoints on the lock line are
   considered with their original kind, color and group/component context.
3. A crossing of the line with another edge precedes an ordinary midpoint.
4. Visible midpoints on the lock line remain exact point targets, including
   when their edge is collinear with the lock.
5. The existing projected-reference and constrained edge/face rules apply
   when no direct point target wins.

This avoids accepting a hidden endpoint or selecting whichever edge happened
to be listed first. It also prevents the origin or a collinear midpoint from
falling through to the cursor's approximate axis projection. For example,
drawing along X past the world origin with the cursor at `(0.03, 0.02, 0)`
must offer `(0, 0, 0)`, rather than `(0.03, 0, 0)`.

The caller retains the explicit lock's color in `SnapResult.lock_color` when
a point target wins. Centers, component origins and arc midpoints retain
their own kind and context instead of being relabeled as endpoints.

## Visibility and near-ties

Point candidates are ordered by screen distance and checked for visibility
nearest first. When the first is hidden, subsequent checks use the supplied
batched callback in progressively larger batches. Duplicate points share a
visibility result within that selection.

Candidates less than half a pixel farther than the nearest **visible** point
form a near-tie. The current drawing context wins over a group/component in
that window; remaining ties keep the original candidate order, including
named-point precedence. The window is relative to the nearest visible point,
so crossing an absolute half-pixel boundary or adding a hidden nearer point
does not change this preference. Outside that window, distance wins.

## Face constraints and deliberate changes of plane

Derived linear inferences must respect the face plane supplied by the caller:

- An edge extension parallel to a face but outside its plane offers no target
  on that face. An extension that pierces it offers its plane intersection.
- A crossing derived from two acquired points is accepted only if it lies on
  the face plane, just as a one-point inference is constrained to that plane.
- When Shift has not captured a direction and falls back to an inferred axis,
  it applies `axis_in_plane` before engaging the axis.

An explicitly requested arrow/reference lock or captured Shift direction
continues to take precedence. A real geometric point can deliberately change
a planar tool's drawing plane: `POINT_SNAP_KINDS` defines these targets. Do not
apply the derived-inference plane filter indiscriminately to endpoints,
midpoints, on-edge targets or real intersections.

## Long edges and points near the camera

The infinite-line/finite-segment intersection solver normalizes both
directions and uses double-precision scalar arithmetic. This avoids
cancellation on long or nearly parallel segments while preserving the
segment bounds and the caller's absolute skew tolerance. A skew pair must
not become an intersection merely because it is long.

For on-edge snapping, both projected endpoints normally determine the screen
distance. If exactly one endpoint is behind the camera, the supplied cursor
projection onto the original edge recovers the visible target. The projected
point must remain within the edge, be projectable and lie within the screen
radius. This does not create a new endpoint at the camera plane or change
the midpoint of the original model edge. With no usable projection callback,
or with both endpoints behind the camera, this fallback offers nothing.

The recovery also lets an edge under the cursor take precedence over an
automatic perpendicular inference. General edge-pair intersection filtering
and viewport picking are separate paths; this change does not replace their
camera clipping policies.

## Avoiding discarded intersection work

When a magnetic axis is already engaged, the general edge-pair intersection
result cannot win. Skip that search entirely. Keep the later on-edge search:
it can locate the actual junction of the engaged axis with an edge, which is
still needed to draw exact connections.

## Tests

`tests/test_snap_constraints.py` covers the reported failures and controls for
the intentional behavior described above. It includes all three explicit
lock variants, metadata, batched visibility, hidden nearest points,
half-pixel boundaries, face constraints, a real camera projection and long,
parallel, skew, out-of-bounds and degenerate segment cases. It does not need
a working OpenGL context.

Run the focused regression file and the existing snap tests:

```powershell
python -m pytest -q tests/test_snap_constraints.py
$snapTests = @(rg -l 'from core.snap import|import core.snap' tests -g '*.py')
python -m pytest -q @snapTests
```

Run the fast suite in the same file batches used by CI:

```sh
python scripts/pytest_batches.py -m "not slow" tests
```

The existing suites also protect chain closure, guide precision, magnetic
axis connections, thin rectangles, transformed drawing axes, group snapping
and agreement between batched and scalar visibility checks.
