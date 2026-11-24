#version 330 core
// Shadow-map depth pass: same vertex contract as basic.vert (positions in
// world coordinates, optional per-instance matrix at locations 3-6, the
// active section cut respected so clipped-away geometry does not cast).
// UVs ride along for the billboard casters' alpha cutout.
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec2 a_uv;
layout(location = 3) in vec4 a_inst0;
layout(location = 4) in vec4 a_inst1;
layout(location = 5) in vec4 a_inst2;
layout(location = 6) in vec4 a_inst3;
layout(location = 7) in float a_shadow_flags;
flat out int v_shadow_flags;

uniform mat4 u_mvp;            // the SUN's view-projection
// The section cut as in basic.vert — up to SEVEN planes, the active one
// and the six faces of the section box; u_clip_count says how many are set (0 = nothing cuts). Sized here,
// as GLSL asks of a clip-distance array indexed in a loop.
uniform vec4 u_clip_planes[7];
uniform int u_clip_count;
out float gl_ClipDistance[7];

out vec2 v_uv;

void main() {
    v_uv = a_uv;
    v_shadow_flags = int(round(a_shadow_flags * 255.0));
    vec4 world = mat4(a_inst0, a_inst1, a_inst2, a_inst3) * vec4(a_pos, 1.0);
    for (int i = 0; i < 7; ++i)
        gl_ClipDistance[i] = (i < u_clip_count)
            ? dot(world, u_clip_planes[i])
            : 1.0;
    gl_Position = u_mvp * world;
}
