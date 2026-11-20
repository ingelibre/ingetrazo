#version 330 core
layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_color;
layout(location=2) in vec3 a_normal0;
layout(location=3) in vec3 a_normal1;
layout(location=4) in vec3 a_info;
layout(location=5) in vec4 a_dash0;
layout(location=6) in vec4 a_dash1;
layout(location=7) in vec4 a_model0;
layout(location=8) in vec4 a_model1;
layout(location=9) in vec4 a_model2;
layout(location=10) in vec4 a_model3;
uniform mat4 u_mvp;
out EdgeVertex {
    vec3 world;
    vec3 normal0;
    vec3 normal1;
    vec3 color;
    vec3 info;
    vec4 dash0;
    vec4 dash1;
} edge;
void main() {
    mat4 model = mat4(a_model0, a_model1, a_model2, a_model3);
    vec4 world = model * vec4(a_pos, 1.0);
    mat3 linear = mat3(model);
    mat3 normal = abs(determinant(linear)) > 1e-12
        ? transpose(inverse(linear)) : mat3(1.0);
    edge.world = world.xyz;
    edge.normal0 = normal * a_normal0;
    edge.normal1 = normal * a_normal1;
    edge.color = a_color;
    edge.info = a_info;
    edge.dash0 = a_dash0;
    edge.dash1 = a_dash1;
    gl_Position = u_mvp * world;
}
