#version 330 core
// One triangle that covers the screen, made from gl_VertexID alone (the
// ambient occlusion passes bind an empty VAO): no vertex buffer to keep.
out vec2 v_uv;

void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
