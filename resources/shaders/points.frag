#version 330 core
// Point clouds: flat colour per point; from 3 px up the square sprite is
// trimmed to a disc so a dense cloud reads as a surface, not a grid.

in vec3 v_color;
uniform int u_round;
out vec4 frag_color;

void main() {
    if (u_round != 0) {
        vec2 c = gl_PointCoord * 2.0 - 1.0;
        if (dot(c, c) > 1.0)
            discard;
    }
    frag_color = vec4(v_color, 1.0);
}
