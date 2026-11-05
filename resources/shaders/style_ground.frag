#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// An infinite display plane: no model entity, section cut or lighting.
in vec2 v_ndc;
uniform mat4 u_inverse_mvp;
uniform mat4 u_mvp;
uniform vec4 u_color;
out vec4 fragColor;
void main() {
    vec4 near_point = u_inverse_mvp * vec4(v_ndc, -1.0, 1.0);
    vec4 far_point = u_inverse_mvp * vec4(v_ndc, 1.0, 1.0);
    // Intersect the projective ray with Z = 0 before dividing by W.
    vec4 hit = near_point * far_point.z - far_point * near_point.z;
    if (abs(hit.w) < 1e-8) discard;
    hit /= hit.w;
    hit.z = 0.0;
    vec4 clip = u_mvp * hit;
    if (clip.w <= 0.0) discard;
    float depth = clip.z / clip.w * 0.5 + 0.5;
    if (depth < 0.0 || depth > 1.0) discard;
    // Coplanar model faces and their edges take priority over the backdrop.
    gl_FragDepth = min(1.0, depth + 0.000002);
    fragColor = u_color;
}
