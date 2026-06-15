#version 330 core

uniform vec4 u_color;
uniform sampler2D u_tex;
uniform int u_use_texture;

in vec2 v_uv;

out vec4 fragColor;

void main() {
    if (u_use_texture == 1) {
        fragColor = texture(u_tex, v_uv);
    } else {
        fragColor = u_color;
    }
}
