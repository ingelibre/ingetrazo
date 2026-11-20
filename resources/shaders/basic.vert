#version 330 core

layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec2 a_uv;
layout(location = 2) in vec3 a_color;
// Per-instance model matrix columns (divisor 1) for the instanced component
// pass. Non-instanced draws leave these attribute arrays DISABLED, and the
// viewport resets their generic values to the IDENTITY columns every frame
// (the GL default (0,0,0,1) would collapse all geometry).
layout(location = 3) in vec4 a_inst0;
layout(location = 4) in vec4 a_inst1;
layout(location = 5) in vec4 a_inst2;
layout(location = 6) in vec4 a_inst3;

uniform mat4 u_mvp;
// Section cut: world-space planes as (n, d) with the KEPT
// side where dot(n, p) + d >= 0. Enabled only around the model-geometry
// passes (sky, axes, terrain, previews stay uncut). All vertex buffers are
// WORLD coordinates (group chunks bake their transform), so the planes
// cover everything.
// Up to SEVEN of them: the active plane and the six faces of the section
// box; u_clip_count says how many are set (0 = nothing cuts). Sized here,
// as GLSL asks of a clip-distance array indexed in a loop.
uniform vec4 u_clip_planes[7];
uniform int u_clip_count;
// Slot 7: the display ground's half-space (styles, #1218), as (n, d) with
// the KEPT side >= 0. Zero leaves everything; GL_CLIP_DISTANCE7 is only
// enabled around the two halves of a frame that draws the ground. It was
// a discard in basic.frag: on the Radeon 780M that one statement cost
// ~7 ms of every zoom frame of a plaza of 3 400 groups that never shows
// the ground (20-11). A plane clips exactly in hardware, so what is kept
// is the same.
uniform vec4 u_style_ground_clip;
out float gl_ClipDistance[8];

out vec2 v_uv;
out vec3 v_color;
// World position for the shadow lookup (every buffer is world-space or
// carries its instance matrix, so this is exact for both).
out vec3 v_world;
// The position BEFORE the instance matrix: the prototype's own frame. The
// instanced pass re-shades from it (u_reshade, #482); everywhere else it
// equals v_world.
out vec3 v_local;
// The vertex's clip position, un-interpolated: along a line every fragment
// gets the PROVOKING vertex's, so the fragment shader can measure how far
// along the line it is — the dash of Back Edges (u_stipple 4, issue #234).
flat out vec4 v_line_clip;

void main() {
    v_uv = a_uv;
    v_color = a_color;
    // World position: instanced draws bake local coords and carry the
    // transform per instance; everything else has identity here (buffers
    // already in world coordinates), so the section plane keeps working
    // unchanged for both.
    vec4 world = mat4(a_inst0, a_inst1, a_inst2, a_inst3) * vec4(a_pos, 1.0);
    v_world = world.xyz;
    v_local = a_pos;
    for (int i = 0; i < 7; ++i)
        gl_ClipDistance[i] = (i < u_clip_count)
            ? dot(world, u_clip_planes[i])
            : 1.0;
    gl_ClipDistance[7] = dot(world, u_style_ground_clip);
    gl_Position = u_mvp * world;
    v_line_clip = gl_Position;
}
