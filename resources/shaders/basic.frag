#version 330 core

uniform vec4 u_color;
uniform vec4 u_back_color;
uniform sampler2D u_tex;
uniform int u_use_texture;
uniform int u_use_vcolor;
// Uniform opacity of the current draw (1.0 = opaque pass). Translucent
// material runs (.skp trans with useTrans) draw last with this < 1.
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
// the background (the classic faded rest of model). A mix, not blending:
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
// Soft sun shadows (#1281, Preferences): how fast the penumbra widens with
// the distance from what casts it (world width per world distance; 0 = the
// crisp map below), and the map's footprint in the world: x = metres across
// one map side, y = metres along the sun over the whole depth range.
uniform float u_shadow_soft;
uniform vec2 u_shadow_world;
// Unit vector toward the sun — with shadows on, faces are shaded BY THE SUN
// ("use sun for shading"): the per-fragment normal comes from
// screen derivatives of the world position (exact on flat faces, no vertex
// data needed), oriented toward the viewer so the VISIBLE side is judged.
uniform vec3 u_sun_dir;
// 1 while drawing the ground-shadow catcher: instead of a coloured surface
// it outputs ONLY the shadow, as translucent black — where the sun reaches
// it is fully transparent, so the plane has no visible shape or edges
// (the usual on-ground shadows are these same floating dark stains).
uniform int u_shadow_overlay;
// View ▸ Hidden Objects / Hidden Geometry: hidden things are
// drawn as a see-through screen-space GRID (1 = faces: a 1 px line every
// 4 px each way) or DOTTED (2 = edges). Fragments off the pattern are
// discarded, so what lies behind shows through the weave. 0 = off.
// 3 = SELECTED faces: an opaque 2x2 px dot every 6 px each way, so the
// face's own colour keeps showing between the dots and a selected face
// never reads as a tinted one (an orange wash over the blue-grey back
// looked like just another back face).
uniform int u_stipple;
// Back Edges (u_stipple 4): a dash measured ALONG the line from its
// provoking vertex, in window pixels — a screen pattern breaks on a
// diagonal (a line along x + y = const is all dash or all gap).
flat in vec4 v_line_clip;
uniform vec2 u_viewport_px;
uniform float u_dash_px;

in vec2 v_uv;
in vec3 v_color;
in vec3 v_world;
in vec3 v_local;
// Instanced component pass (#482): face colours and texture shades were
// baked from the PROTOTYPE's normals against the fixed world light, so a
// rotated copy kept the light of the unrotated one. With this on, the
// baked tone is scaled by the light of the face as placed over the light
// of the face as baked — the same 0.62..1.0 matte law as the bake
// (Viewport._shade_factor), unquantised so neighbouring pixels agree.
uniform int u_reshade;
uniform vec3 u_light_fixed;
// 1 while drawing the default backs of the shaded modes: the back colour
// takes the same matte light as the fronts' baked shade, so the inside of
// a sphere reads round instead of a flat disc (issue #873). Per pixel,
// from the face's plane — the back pass carries positions only.
uniform int u_back_shade;

out vec4 fragColor;

// The stored depth of the shadow map at ``uv`` (packed in RGB).
float shadow_depth(vec2 uv) {
    vec3 e = texture(u_shadow_map, uv).rgb;
    return dot(e, vec3(1.0, 1.0 / 255.0, 1.0 / 65025.0));
}

// 32 points of a Poisson disc of radius 1; the first 16 spread as well on
// their own, for the blocker search.
const vec2 POISSON[32] = vec2[32](
    vec2(-0.6123, 0.3315), vec2(0.4211, -0.7346), vec2(0.8622, 0.3911),
    vec2(-0.1843, -0.9318), vec2(0.0897, 0.6214), vec2(-0.8915, -0.3426),
    vec2(0.5503, 0.0712), vec2(-0.3364, -0.3992), vec2(-0.0412, 0.0567),
    vec2(0.2938, 0.9348), vec2(-0.4621, 0.8506), vec2(0.9547, -0.2459),
    vec2(-0.9618, 0.1574), vec2(0.6845, -0.6432), vec2(0.2371, -0.3365),
    vec2(-0.6834, -0.7175), vec2(0.1528, 0.2896), vec2(-0.2531, 0.3608),
    vec2(0.6627, 0.6876), vec2(-0.7765, 0.6151), vec2(0.3917, 0.4954),
    vec2(-0.5398, -0.0745), vec2(0.0174, -0.6293), vec2(0.7614, -0.0124),
    vec2(-0.1287, 0.8634), vec2(0.4637, -0.4215), vec2(-0.3946, -0.8237),
    vec2(0.9265, 0.1287), vec2(-0.8213, -0.0567), vec2(0.1843, -0.9471),
    vec2(-0.2145, -0.1563), vec2(0.5638, 0.2964));

// Percentage-closer soft shadows: the blockers around the fragment say how
// far it lies behind them, and the penumbra widens with that distance —
// crisp where a wall meets the floor, soft at the far end of its shadow.
// Widths are worked out in the world, so the detail map of a settled view
// (#958) and an export's bigger map soften the same.
float soft_shadow_light(vec3 uvz, vec2 grad, float bias, vec2 texel) {
    // One turn of the disc per pixel: the samples' pattern does not band.
    float a = 6.2831853 * fract(52.9829189 * fract(
        dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
    mat2 rot = mat2(cos(a), sin(a), -sin(a), cos(a));
    float per_uv = u_shadow_soft * u_shadow_world.y / u_shadow_world.x;
    // At most half a metre wide, in the world — not in texels, which an
    // export's bigger map or a settled view's detail map would shrink —
    // and never crisper than the PCF below.
    float least = 1.5 * texel.x;
    float most = max(0.5 / u_shadow_world.x, least);
    // Blocker search, as wide as the widest penumbra this point can get.
    float search = clamp(per_uv * uvz.z, least, most);
    float sum = 0.0;
    float n = 0.0;
    for (int i = 0; i < 16; i++) {
        vec2 off = rot * POISSON[i] * search;
        float d = shadow_depth(uvz.xy + off);
        if (d < uvz.z + dot(grad, off) - bias) {
            sum += d;
            n += 1.0;
        }
    }
    if (n == 0.0) {
        return 1.0;                       // nothing in front: in the sun
    }
    float pen = clamp(per_uv * (uvz.z - sum / n), least, most);
    float lit = 0.0;
    for (int i = 0; i < 32; i++) {
        vec2 off = rot * POISSON[i] * pen;
        lit += (uvz.z + dot(grad, off) - bias <= shadow_depth(uvz.xy + off))
            ? 1.0 : 0.0;
    }
    return lit / 32.0;
}

// Fraction of light reaching this fragment (0..1): 3x3 PCF over the
// packed-depth shadow map, each tap bilinearly weighted between the four
// texels around it — so the edge is a smooth ramp instead of the map's
// staircase (each texel is centimetres of ground, 30 cm on a 280 m plant).
// Outside the map = fully lit.
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
    if (u_shadow_soft > 0.0) {
        return soft_shadow_light(uvz, grad, bias, texel);
    }
    // The 4x4 texels under the kernel, each compared once against the
    // receiver plane at its own centre...
    vec2 size = vec2(textureSize(u_shadow_map, 0));
    vec2 st = uvz.xy * size - 0.5;
    vec2 cell = floor(st);
    vec2 f = st - cell;
    float t[16];
    for (int j = 0; j < 4; j++) {
        for (int i = 0; i < 4; i++) {
            vec2 uv = (cell + vec2(i - 1, j - 1) + 0.5) * texel;
            vec2 off = uv - uvz.xy;
            float d = shadow_depth(uv);
            t[j * 4 + i] = (uvz.z + dot(grad, off) - bias <= d) ? 1.0 : 0.0;
        }
    }
    // ...then the nine taps, each the bilinear blend of its 2x2.
    float lit = 0.0;
    for (int j = 0; j < 3; j++) {
        for (int i = 0; i < 3; i++) {
            float a = mix(t[j * 4 + i], t[j * 4 + i + 1], f.x);
            float b = mix(t[(j + 1) * 4 + i], t[(j + 1) * 4 + i + 1], f.x);
            lit += mix(a, b, f.y);
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

float matte(vec3 n) {
    return 0.62 + 0.38 * abs(dot(n, u_light_fixed));
}

void main() {
    // Taken before any discard, while the whole pixel quad is alive.
    vec3 n_local = cross(dFdx(v_local), dFdy(v_local));
    vec3 n_world = cross(dFdx(v_world), dFdy(v_world));
    if (u_stipple == 1) {
        if (mod(gl_FragCoord.x, 4.0) >= 1.0 && mod(gl_FragCoord.y, 4.0) >= 1.0)
            discard;
    } else if (u_stipple == 2) {
        if (mod(gl_FragCoord.x + gl_FragCoord.y, 6.0) >= 3.0) discard;
    } else if (u_stipple == 3) {
        if (mod(gl_FragCoord.x, 6.0) >= 2.0 || mod(gl_FragCoord.y, 6.0) >= 2.0)
            discard;
    } else if (u_stipple == 4) {
        vec2 o = (v_line_clip.xy / v_line_clip.w * 0.5 + 0.5) * u_viewport_px;
        if (mod(length(gl_FragCoord.xy - o), 2.0 * u_dash_px) >= u_dash_px)
            discard;
    }
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
        // Classic face culling colours: front = paper white, back =
        // blue-grey. Orientation is guaranteed outward by the engine, so a
        // visible back face means "you are looking at the inside" (or at a
        // genuinely inverted face).
        // u_use_vcolor: the batched face pass carries its per-face shaded
        // colour as a vertex attribute — ONE draw call for the whole model
        // instead of one per colour run. That pass draws imported REFERENCE
        // groups, whose faces show their own colour on both sides (the .skp format
        // paints each side; thin ironwork would otherwise flash the back
        // tint). The back tint stays on the user's own drawing (u_color
        // path), where it is honest "you are looking at the inside" feedback.
        vec4 front = (u_use_vcolor == 1) ? vec4(v_color, u_opacity) : u_color;
        c = (gl_FrontFacing || u_use_vcolor == 1) ? front : u_back_color;
        if (u_back_shade == 1 && !gl_FrontFacing && u_use_vcolor == 0) {
            float lb = length(n_world);
            if (lb > 1e-20) c.rgb *= matte(n_world / lb);
        }
    }
    if (u_reshade == 1 && (u_use_texture == 1 || u_use_vcolor == 1)) {
        float ll = length(n_local);
        float lw = length(n_world);
        if (ll > 1e-20 && lw > 1e-20) {
            c.rgb = min(c.rgb * (matte(n_world / lw) / matte(n_local / ll)),
                        vec3(1.0));
        }
    }
    if (u_shadow_enable == 1) {
        if (u_shadow_overlay == 1) {
            // Ground catcher: the shadow and nothing else.
            fragColor = vec4(0.0, 0.0, 0.0,
                             (1.0 - u_shadow_dark)
                             * (1.0 - shadow_light()));
            return;
        }
        // Sun shading + cast shadows, composed the classic way: the sun
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
