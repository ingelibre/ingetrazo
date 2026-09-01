#version 330 core
// Depth packed into RGB (24 bits) of a plain RGBA8 colour attachment — a
// QOpenGLFramebufferObject sampled as an ordinary texture, no raw depth-
// texture plumbing. The ortho projection makes gl_FragCoord.z linear.
// Unpack with dot(rgb, vec3(1, 1/255, 1/65025)); the buffer clears to
// white, which unpacks a hair ABOVE 1.0 — empty sky is always "lit".
// Billboard casters (the 2D people): their silhouette is the texture's
// alpha, so the caster discards like the render pass does.
uniform sampler2D u_tex;
uniform int u_use_texture;

in vec2 v_uv;
out vec4 fragColor;

void main() {
    if (u_use_texture == 1 && texture(u_tex, v_uv).a < 0.5) {
        discard;
    }
    float d = gl_FragCoord.z;
    // Slope-scaled bias, applied on the CASTER (glPolygonOffset cannot
    // reach a depth that is packed into colour): a face at a grazing angle
    // to the sun changes depth fast across one texel and stripes with
    // self-shadow acne under any constant bias. The derivative IS the
    // per-texel depth slope; clamped so extreme grazing cannot detach a
    // shadow visibly.
    float slope = max(abs(dFdx(d)), abs(dFdy(d)));
    d = min(d + min(slope * 2.0, 0.01) + 0.0004, 0.999999);
    vec3 e = fract(vec3(1.0, 255.0, 65025.0) * d);
    e.xy -= e.yz * (1.0 / 255.0);
    fragColor = vec4(e, 1.0);
}
