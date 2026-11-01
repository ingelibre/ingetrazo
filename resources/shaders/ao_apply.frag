#version 330 core
// Multiplies the occlusion onto the scene (#954), drawn with the blend
// (GL_ZERO, GL_SRC_COLOR) over the opaque faces only — edges, dimensions,
// text and guides come after and stay as they were.
//
// The occlusion pass gives the true visibility (a 90-degree corner sees
// half its sky). Two things turn it into light, both from the paper the
// pass follows (Jimenez et al. 2016):
// - light bounces: a white corner is lit by its own walls and comes out a
//   soft grey, a dark one stays dark. The fit of the paper, fed with the
//   face's own colour (the scene the face passes drew, read from u_color);
// - the intensity scales the darkening linearly: 0 leaves the picture
//   untouched, 1 is the physical value, 2 doubles it. (It was a contrast
//   curve, ao^(2.5 * intensity), that sent every corner nearly black.)
//
// The occlusion is worked out at half size. Stretching it back with plain
// bilinear filtering mixed, along every silhouette, the value of the object
// with that of what lies behind it — dark halos round a column against a far
// background, a figure behind a post cut into blocks, saw teeth under every
// slat. Each of the four half-size texels around this pixel now counts only
// as much as its depth agrees with this pixel's (the depth the occlusion
// pass read at that texel's centre).
uniform sampler2D u_ao;
uniform sampler2D u_depth;      // full size
uniform mat4 u_inv_proj;
uniform vec2 u_ao_size;         // the occlusion texture's size
uniform float u_radius;
uniform float u_intensity;
uniform sampler2D u_color;      // the scene's resolved colour, full size

in vec2 v_uv;
out vec4 fragColor;

// Visibility after the light the surroundings bounce back, per channel,
// for a surface of colour a (the paper's cubic fit).
vec3 multi_bounce(float v, vec3 a) {
    vec3 ka = 2.0404 * a - 0.3324;
    vec3 kb = -4.7951 * a + 0.6417;
    vec3 kc = 2.7552 * a + 0.6903;
    return max(vec3(v), ((v * ka + kb) * v + kc) * v);
}

float view_z(vec2 uv) {
    float d = texture(u_depth, uv).r;
    vec4 p = u_inv_proj * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return p.z / p.w;
}

void main() {
    // The sky has nothing to darken. Its depth sits on the far plane, so a
    // tolerance relative to depth would let the slat in front through.
    if (texture(u_depth, v_uv).r >= 1.0) {
        fragColor = vec4(1.0);
        return;
    }
    float z = view_z(v_uv);
    vec2 f = v_uv * u_ao_size - 0.5;
    vec2 base = floor(f);
    vec2 t = f - base;
    float tol = max(u_radius * 0.1, abs(z) * 0.003);
    float sum = 0.0;
    float wsum = 0.0;
    float best = 1e30;
    float nearest = 1.0;
    for (int j = 0; j < 2; ++j) {
        for (int i = 0; i < 2; ++i) {
            vec2 uv = (base + vec2(float(i), float(j)) + 0.5) / u_ao_size;
            float dz = texture(u_depth, uv).r >= 1.0 ? 1e30
                                                    : abs(view_z(uv) - z);
            float a = texture(u_ao, uv).r;
            float bil = (i == 0 ? 1.0 - t.x : t.x) * (j == 0 ? 1.0 - t.y : t.y);
            float w = bil * max(0.0, 1.0 - dz / tol) + 1e-5 * bil;
            if (dz < tol) {
                sum += a * w;
                wsum += w;
            }
            if (dz < best) { best = dz; nearest = a; }
        }
    }
    // No texel on this surface (a sliver thinner than a half-size texel):
    // the closest in depth.
    float ao = wsum > 1e-6 ? sum / wsum : nearest;
    // The scene's colour is the face already lit, not its bare albedo, and
    // the walls round a corner pass on only part of their light: half of it
    // reads as the surface's own (fed whole, a white corner all but went).
    vec3 albedo = clamp(texture(u_color, v_uv).rgb, 0.0, 1.0) * 0.5;
    vec3 lit = multi_bounce(clamp(ao, 0.0, 1.0), albedo);
    vec3 k = 1.0 - (1.0 - lit) * clamp(u_intensity, 0.0, 2.0);
    // Never pure black: the slot under a bench seat keeps a third of its
    // light, so what is in there still reads.
    fragColor = vec4(max(k, vec3(0.3)), 1.0);
}
