#version 330 core

uniform vec4 u_color;
uniform vec4 u_back_color;
uniform sampler2D u_tex;
uniform int u_use_texture;
uniform int u_use_vcolor;

in vec2 v_uv;
in vec3 v_color;

out vec4 fragColor;

void main() {
    if (u_use_texture == 1) {
        vec4 texel = texture(u_tex, v_uv);
        // Cutout transparency (face-me billboards, future leaf textures):
        // discard keeps the depth buffer honest behind the holes.
        if (texel.a < 0.5) discard;
        fragColor = texel;
    } else {
        // SketchUp-style face culling colours: front = paper white, back =
        // blue-grey. Orientation is guaranteed outward by the engine, so a
        // visible back face means "you are looking at the inside" (or at a
        // genuinely inverted face).
        // u_use_vcolor: the batched face pass carries its per-face shaded
        // colour as a vertex attribute — ONE draw call for the whole model
        // instead of one per colour run. That pass draws imported REFERENCE
        // groups, whose faces show their own colour on both sides (SketchUp
        // paints each side; thin ironwork would otherwise flash the back
        // tint). The back tint stays on the user's own drawing (u_color
        // path), where it is honest "you are looking at the inside" feedback.
        vec4 front = (u_use_vcolor == 1) ? vec4(v_color, 1.0) : u_color;
        fragColor = (gl_FrontFacing || u_use_vcolor == 1) ? front
                                                          : u_back_color;
    }
}
