#version 330 core
// Profile (silhouette) edges of an instanced component, decided ON THE GPU.
//
// Each soft edge of the prototype is two vertices carrying the same two
// face planes (unit normal + offset, in the prototype's own coordinates)
// and a "single" flag (a boundary edge with one face: always a profile).
// The edge is a profile when the eye sees one face from the front and the
// other from the back — the eye taken into the prototype's coordinates
// through the inverse of the placement matrix, exactly the test the
// NumPy pass (_instanced_silhouettes) made per placement every few frames.
// Here it runs per vertex, per frame, for every placement in one instanced
// draw: no CPU work, no interval, no hitch. A non-profile edge is sent
// behind the near plane, where the clipper drops the whole segment (both
// vertices decide alike, so no half-lines).
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec3 a_n0;
layout(location = 2) in vec3 a_n1;
layout(location = 7) in vec3 a_dd;      // (d0, d1, single)
// Per-instance placement matrix columns (divisor 1): the same buffer and
// locations the instanced face pass uses.
layout(location = 3) in vec4 a_inst0;
layout(location = 4) in vec4 a_inst1;
layout(location = 5) in vec4 a_inst2;
layout(location = 6) in vec4 a_inst3;
// ...and its inverse (divisor 1 too), worked out once per placement on the
// CPU: a mat4 inverse() per vertex was the pass's GPU cost.
layout(location = 8) in vec4 a_inv0;
layout(location = 9) in vec4 a_inv1;
layout(location = 10) in vec4 a_inv2;
layout(location = 11) in vec4 a_inv3;

uniform mat4 u_mvp;            // view-projection (world -> clip)
uniform vec3 u_eye;            // camera eye, world
uniform vec4 u_clip_plane;     // section cut, as basic.vert
uniform int u_clip_enable;

void main() {
    mat4 m = mat4(a_inst0, a_inst1, a_inst2, a_inst3);
    vec3 eye_l = (mat4(a_inv0, a_inv1, a_inv2, a_inv3) * vec4(u_eye, 1.0)).xyz;
    float s0 = a_dd.x - dot(a_n0, eye_l);
    float s1 = a_dd.y - dot(a_n1, eye_l);
    bool profile = a_dd.z > 0.5 || ((s0 < 0.0) != (s1 < 0.0));
    if (!profile) {
        gl_Position = vec4(0.0, 0.0, -2.0, 1.0);   // behind the near plane
        gl_ClipDistance[0] = -1.0;
        return;
    }
    vec4 world = m * vec4(a_pos, 1.0);
    gl_ClipDistance[0] = (u_clip_enable == 1) ? dot(world, u_clip_plane) : 1.0;
    gl_Position = u_mvp * world;
}
