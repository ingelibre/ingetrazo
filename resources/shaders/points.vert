#version 330 core
// Point clouds (georef/pointcloud.py): one vertex per scanned point, in
// world coordinates, with its display colour as normalised bytes.

layout(location = 0) in vec3 a_pos;
layout(location = 2) in vec4 a_color;

uniform mat4 u_mvp;
uniform float u_point_size;
// The section cut, the same contract as basic.vert: (n, d) with the KEPT
// side where dot(n, p) + d >= 0; u_clip_count says how many are set.
uniform vec4 u_clip_planes[7];
uniform int u_clip_count;
out float gl_ClipDistance[7];

out vec3 v_color;

void main() {
    vec4 world = vec4(a_pos, 1.0);
    for (int i = 0; i < 7; ++i)
        gl_ClipDistance[i] = (i < u_clip_count)
            ? dot(world, u_clip_planes[i])
            : 1.0;
    v_color = a_color.rgb;
    gl_Position = u_mvp * world;
    gl_PointSize = u_point_size;
}
