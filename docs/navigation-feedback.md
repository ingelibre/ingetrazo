# Camera feedback for large models

Preferences → General → **Hide edges while moving the camera (large models)**
is off by default (`display/navigation_feedback=0` in QSettings). Enabling it
keeps faces, textures, materials, selection cues, section cuts and shadows, but
skips model edges, back edges and silhouette profiles while the camera moves.
Wireframe retains its lines because it has no faces to show. Image exports
always render the complete style, even during a gesture.

An orbit/pan drag release immediately requests a complete frame. Wheel bursts and other
camera changes restore the complete frame after 150 ms without a new camera
pose. Profiles are recomputed for the final view before that frame is shown.
Disabling the option during motion also requests the complete frame. Picking
and model data are unchanged.

This is an optional visual tradeoff, not a change to the default renderer.
The R8-B benchmark report contains on/off gesture and GPU-pass measurements.
An upstream proposal should decide the user-facing wording and idle interval
before considering any wider default. Further texture/shadow degradation is
outside this implementation.

A positive Motion edge threshold retains the edges of placements at least that
many framebuffer pixels across (bounding sphere, conservatively estimated).
Zero, the default, hides all edges during motion. Profiles remain suppressed.
Unknown bounds and loose edges are retained in threshold mode. Wireframe and
exports remain complete. The setting does not change face culling.

Moving frames bypass the static-frame cache. Stopping recomputes profiles only
when the stored profile input signature differs from the final camera/scene.
