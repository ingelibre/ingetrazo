# Perspective depth range

The renderer fits near/far clipping planes to conservative placement boxes that
intersect the camera's side planes. Boxes are reused across camera motion and
invalidated with content, visibility, edit context and placement changes. Each
frame projects their extrema along the actual view direction (including two-point
perspective). A five-percent margin keeps finite bounds inside the range.

The original range remains for orthographic views, unknown bounds, boxes crossing
the camera, edit contexts, active group previews, guides, terrain and shadows.
A fit never moves the near plane closer than the original camera would. The
original close-up floor is therefore preserved. These fallbacks are deliberate
limits: a camera inside a large conservative box can still show depth fighting.
Drawing axes use depth clamp so fitting does not truncate their infinite lines.

On a 24-bit depth buffer with near=0.1 m and far=10,000 m, the local depth step is
z²(f−n)/(fn(2²⁴−1)): 0.060 mm at 10 m, 1.49 mm at 50 m, 23.84 mm at 200 m.
Moving the far plane alone has little effect; moving the near plane matters.

Cocoa synthetic plates (1, 2 and 5 mm at 10, 50 and 200 m), rotated by 0.01°,
had 118,033 front/rear classification changes in their stable interiors before
fitting and none after. Geometry-only non-fighting scenes retain exact RGB32
pixels. Two antialiased drawing-axis pixels can change with the fitted depth
projection; full-frame parity outside formerly fighting geometry is not yet met.

A diagnostic 32-bit-float reversed-Z attachment on OpenGL 4.1, with projection Z
negated and GEQUAL, still fought at 200 m. Without ZERO_TO_ONE clip control the
viewport remap loses precision; this is not the usual reversed-Z guarantee.
It is not enabled in the product. Logarithmic vertex depth was not adopted:
nonlinear interpolation changes depth on large triangles and line/face contacts.

Depth remains conventional [0,1], LEQUAL, clear=1. Existing unprojection and
annotation/inference readback use the fitted projection without a depth encoding
change. Reversed depth would also require auditing sky tests, comparison direction,
polygon offsets, readback rejection, depth-cache copies and shadow depth separately.
