#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
layout(location = 0) in vec3 a_pos;
out vec2 v_ndc;
void main() {
    v_ndc = a_pos.xy;
    gl_Position = vec4(a_pos, 1.0);
}
