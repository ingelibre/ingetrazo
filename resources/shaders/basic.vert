#version 330 core

layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec2 a_uv;
layout(location = 2) in vec3 a_color;

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

void main() {
    v_uv = a_uv;
    v_color = a_color;
    gl_ClipDistance[0] = (u_clip_enable == 1)
        ? dot(vec4(a_pos, 1.0), u_clip_plane)
        : 1.0;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
