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

uniform mat4 u_mvp;            // the SUN's view-projection
uniform vec4 u_clip_plane;
uniform int u_clip_enable;

out vec2 v_uv;

void main() {
    v_uv = a_uv;
    vec4 world = mat4(a_inst0, a_inst1, a_inst2, a_inst3) * vec4(a_pos, 1.0);
    gl_ClipDistance[0] = (u_clip_enable == 1)
        ? dot(world, u_clip_plane)
        : 1.0;
    gl_Position = u_mvp * world;
}
