#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// The drawing grid on the ground (#780): lines on the Z=0 plane every
// u_spacing, a stronger one every u_major divisions. A display aid only.
in vec2 v_ndc;
uniform mat4 u_inverse_mvp;
uniform mat4 u_mvp;
uniform vec3 u_color;
uniform float u_spacing;
uniform float u_major;
uniform float u_alpha;
out vec4 fragColor;

// Coverage of the lines of a grid of cell 1 in ``coord`` (anti-aliased,
// about one pixel wide), faded out as its cells shrink below a few pixels
// so the far ground does not turn into moire.
float lines(vec2 coord, float width) {
    vec2 fw = max(fwidth(coord), vec2(1e-6));
    vec2 g = abs(fract(coord - 0.5) - 0.5) / fw;
    float line = 1.0 - min(min(g.x, g.y) / width, 1.0);
    float cell_px = 1.0 / max(fw.x, fw.y);
    return line * smoothstep(4.0, 12.0, cell_px);
}

void main() {
    vec4 near_point = u_inverse_mvp * vec4(v_ndc, -1.0, 1.0);
    vec4 far_point = u_inverse_mvp * vec4(v_ndc, 1.0, 1.0);
    // Intersect the projective ray with Z = 0 before dividing by W.
    vec4 hit = near_point * far_point.z - far_point * near_point.z;
    bool miss = abs(hit.w) < 1e-8;
    hit /= miss ? 1.0 : hit.w;
    hit.z = 0.0;
    // The derivatives are taken before any discard, in uniform control
    // flow, as GLSL requires.
    vec2 coord = hit.xy / u_spacing;
    float minor = lines(coord, 1.0);
    float major = lines(coord / u_major, 1.5);
    if (miss) discard;
    vec4 clip = u_mvp * hit;
    if (clip.w <= 0.0) discard;
    float depth = clip.z / clip.w * 0.5 + 0.5;
    if (depth < 0.0 || depth > 1.0) discard;
    float a = max(minor * 0.45, major * 0.85) * u_alpha;
    if (a < 0.004) discard;
    // Faces lying on the ground (a floor at Z=0) cover the grid.
    gl_FragDepth = min(1.0, depth + 0.000004);
    fragColor = vec4(u_color, a);
}
