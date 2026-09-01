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
// Active section cut (SketchUp): world-space plane as (n, d) with the KEPT
// side where dot(n, p) + d >= 0. Enabled only around the model-geometry
// passes (sky, axes, terrain, previews stay uncut). All vertex buffers are
// WORLD coordinates (group chunks bake their transform), so one plane
// covers everything.
uniform vec4 u_clip_plane;
uniform int u_clip_enable;

out vec2 v_uv;
out vec3 v_color;
// World position for the shadow lookup (every buffer is world-space or
// carries its instance matrix, so this is exact for both).
out vec3 v_world;

void main() {
    v_uv = a_uv;
    v_color = a_color;
    // World position: instanced draws bake local coords and carry the
    // transform per instance; everything else has identity here (buffers
    // already in world coordinates), so the section plane keeps working
    // unchanged for both.
    vec4 world = mat4(a_inst0, a_inst1, a_inst2, a_inst3) * vec4(a_pos, 1.0);
    v_world = world.xyz;
    gl_ClipDistance[0] = (u_clip_enable == 1)
        ? dot(world, u_clip_plane)
        : 1.0;
    gl_Position = u_mvp * world;
}
