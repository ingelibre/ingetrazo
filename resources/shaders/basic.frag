#version 330 core

uniform vec4 u_color;
uniform vec4 u_back_color;
uniform sampler2D u_tex;
uniform int u_use_texture;

in vec2 v_uv;

out vec4 fragColor;

void main() {
    if (u_use_texture == 1) {
        fragColor = texture(u_tex, v_uv);
    } else {
        // SketchUp-style face culling colours: front = paper white, back =
        // blue-grey. Orientation is guaranteed outward by the engine, so a
        // visible back face means "you are looking at the inside" (or at a
        // genuinely inverted face).
        fragColor = gl_FrontFacing ? u_color : u_back_color;
    }
}
