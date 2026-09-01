#version 330 core

uniform vec4 u_color;
uniform vec4 u_back_color;
uniform sampler2D u_tex;
uniform int u_use_texture;
uniform int u_use_vcolor;
// Uniform opacity of the current draw (1.0 = opaque pass). Translucent
// material runs (SketchUp trans with useTrans) draw last with this < 1.
uniform float u_opacity;
// 1 while drawing face-me billboards: a HARD alpha cut at 0.5 instead of
// the Bayer dither below. Their mipmapped edge alpha would otherwise
// render as stipple dots around the figure; the dither stays for scene
// cutouts (fences, leaves), which need it to survive minification.
uniform int u_hard_cutout;
// Per-run diffuse shade for textured faces (colour faces bake it into
// their vertex colours) — 1.0 everywhere else (billboards, previews).
uniform float u_shade;
// While a group is open for editing, the model AROUND it is washed toward
// the background (SketchUp's faded rest of model). A mix, not blending:
// the pass stays opaque and keeps writing depth, so the context still
// occludes itself. Drawing it translucent instead let every surface show
// through every other one and turned coplanar faces into colour speckle.
// 0 = untouched.
uniform float u_fade;
uniform vec3 u_fade_color;
// Sun shadows: the light's view-projection, its packed-depth map (unit 1),
// how dark a shadowed fragment goes, and the depth-compare bias. Enabled
// only around the geometry passes — sky, overlays and previews stay unlit.
uniform int u_shadow_enable;
uniform sampler2D u_shadow_map;
uniform mat4 u_light_vp;
uniform float u_shadow_dark;
uniform float u_shadow_bias;
// Unit vector toward the sun — with shadows on, faces are shaded BY THE SUN
// (SketchUp's "use sun for shading"): the per-fragment normal comes from
// screen derivatives of the world position (exact on flat faces, no vertex
// data needed), oriented toward the viewer so the VISIBLE side is judged.
uniform vec3 u_sun_dir;
// 1 while drawing the ground-shadow catcher: instead of a coloured surface
// it outputs ONLY the shadow, as translucent black — where the sun reaches
// it is fully transparent, so the plane has no visible shape or edges
// (SketchUp's on-ground shadows are these same floating dark stains).
uniform int u_shadow_overlay;

in vec2 v_uv;
in vec3 v_color;
in vec3 v_world;

out vec4 fragColor;

// Fraction of light reaching this fragment (0..1): 3x3 PCF over the
// packed-depth shadow map. Outside the map = fully lit.
float shadow_light() {
    vec4 lp = u_light_vp * vec4(v_world, 1.0);
    vec3 uvz = lp.xyz / lp.w * 0.5 + 0.5;
    if (uvz.x <= 0.0 || uvz.x >= 1.0 || uvz.y <= 0.0 || uvz.y >= 1.0
            || uvz.z >= 1.0) {
        return 1.0;
    }
    vec2 texel = 1.0 / vec2(textureSize(u_shadow_map, 0));
    // Receiver-plane depth correction (Isidoro): each PCF tap compares the
    // stored depth against the receiver PLANE evaluated AT the tap, not
    // against the centre fragment. The plane's depth gradient in MAP UV
    // space comes from the screen derivatives through the inverse Jacobian
    // — both components, so diagonal taps on a surface lying oblique to
    // the sun stay exact (a per-axis slope estimate under-covered them by
    // up to 2× and striped grazing faces with moiré acne). The clamp keeps
    // a degenerate 2×2 quad (silhouette pixels) from blowing the plane up.
    vec3 ddx = dFdx(uvz);
    vec3 ddy = dFdy(uvz);
    float det = ddx.x * ddy.y - ddx.y * ddy.x;
    vec2 grad = (abs(det) > 1e-12)
        ? vec2(ddy.y * ddx.z - ddx.y * ddy.z,
               ddx.x * ddy.z - ddy.x * ddx.z) / det
        : vec2(0.0);
    float glen = length(grad);
    if (glen > 8.0) {
        // Cap: a face seen edge-on by the sun has a near-infinite gradient;
        // uncapped it inflates the margin and paints a wide false-lit band
        // where such a face meets its roof. 8 covers every face that
        // actually SHOWS its lighting (the truly parallel ones are dark by
        // face shading anyway) while keeping the band under ~15 cm.
        grad *= 8.0 / glen;
        glen = 8.0;
    }
    // Margin: constant term + 1.5 texels of slope along the gradient
    // (covers the within-texel offset of both receiver and caster raster).
    float bias = u_shadow_bias + glen * texel.x * 1.5;
    float lit = 0.0;
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            vec2 off = vec2(dx, dy) * texel;
            vec3 e = texture(u_shadow_map, uvz.xy + off).rgb;
            float d = dot(e, vec3(1.0, 1.0 / 255.0, 1.0 / 65025.0));
            lit += (uvz.z + dot(grad, off) - bias <= d) ? 1.0 : 0.0;
        }
    }
    return lit / 9.0;
}

// 4x4 Bayer matrix, thresholds strictly inside (0, 1) so alpha 0 always
// discards and alpha 1 always draws.
const float BAYER[16] = float[16](
     0.5/16.0,  8.5/16.0,  2.5/16.0, 10.5/16.0,
    12.5/16.0,  4.5/16.0, 14.5/16.0,  6.5/16.0,
     3.5/16.0, 11.5/16.0,  1.5/16.0,  9.5/16.0,
    15.5/16.0,  7.5/16.0, 13.5/16.0,  5.5/16.0);

void main() {
    vec4 c;
    if (u_use_texture == 1) {
        vec4 texel = texture(u_tex, v_uv);
        // Cutout transparency (face-me billboards, leaves, chain-link):
        // discard keeps the depth buffer honest behind the holes. Below the
        // 0.5 cut the test is DITHERED, not hard — mipmap minification
        // averages a sparse cutout's alpha toward its coverage fraction
        // (a chain-link fence reads ~0.12 at distance) and a hard cut would
        // erase it; the Bayer pattern keeps that fraction of pixels, drawn
        // opaque, so distant fences stay visible as a faint weave.
        // Translucent runs (u_opacity < 1) blend instead of cutting.
        if (u_opacity > 0.999 && texel.a < 0.5) {
            if (u_hard_cutout == 1) discard;
            int bx = int(mod(gl_FragCoord.x, 4.0));
            int by = int(mod(gl_FragCoord.y, 4.0));
            if (texel.a < BAYER[by * 4 + bx]) discard;
            c = vec4(texel.rgb * u_shade, 1.0);
        } else {
            c = vec4(texel.rgb * u_shade, texel.a * u_opacity);
        }
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
        vec4 front = (u_use_vcolor == 1) ? vec4(v_color, u_opacity) : u_color;
        c = (gl_FrontFacing || u_use_vcolor == 1) ? front : u_back_color;
    }
    if (u_shadow_enable == 1) {
        if (u_shadow_overlay == 1) {
            // Ground catcher: the shadow and nothing else.
            fragColor = vec4(0.0, 0.0, 0.0,
                             (1.0 - u_shadow_dark)
                             * (1.0 - shadow_light()));
            return;
        }
        // Sun shading + cast shadows, composed the SketchUp way: the sun
        // side of the model is bright, the far side sits at the flat shade
        // tone, and the map only speaks where the face actually SEES the
        // sun — a face turned away never samples it, which also kills every
        // residual bias artifact along its roof line.
        vec3 nrm = normalize(cross(dFdx(v_world), dFdy(v_world)));
        float ndl = dot(nrm, u_sun_dir);
        float lit = (ndl > 0.0) ? shadow_light() : 0.0;
        c.rgb *= mix(u_shadow_dark, 1.0,
                     clamp(ndl * 1.5, 0.0, 1.0) * lit);
    }
    fragColor = vec4(mix(c.rgb, u_fade_color, u_fade), c.a);
}
