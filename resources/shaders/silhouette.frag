#version 330 core
// One flat colour: the style's edge colour. Profiles are plain lines.
uniform vec4 u_color;
out vec4 fragColor;

void main() {
    fragColor = u_color;
}
