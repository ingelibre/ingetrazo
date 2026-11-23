#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// A 360° equirectangular panorama behind the model, looked up by the
// direction of sight (core/panorama_backdrop.py holds the same lookup in
// Python, direction_uv, and documents the conventions).
in vec2 v_ndc;
uniform mat4 u_inverse_mvp;
uniform sampler2D u_tex;
uniform float u_centre;        // azimuth of the picture's middle, radians
uniform vec3 u_fog_color;
uniform float u_fog_strength;
out vec4 fragColor;
const float PI = 3.14159265358979;
void main() {
    vec4 near_point = u_inverse_mvp * vec4(v_ndc, -1.0, 1.0);
    vec4 mid_point = u_inverse_mvp * vec4(v_ndc, 0.0, 1.0);
    vec3 dir = mid_point.xyz / mid_point.w - near_point.xyz / near_point.w;
    float len = length(dir);
    if (len < 1e-12) discard;
    dir /= len;
    float u = fract(0.5 - (atan(dir.y, dir.x) - u_centre) / (2.0 * PI));
    float v = 0.5 + asin(clamp(dir.z, -1.0, 1.0)) / PI;
    vec3 rgb = texture(u_tex, vec2(u, v)).rgb;
    fragColor = vec4(mix(rgb, u_fog_color, u_fog_strength), 1.0);
}
