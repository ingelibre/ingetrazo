#version 330 core
// Screen-space ambient occlusion (#954): how much of the hemisphere above
// each visible point is taken by the model's own nearby surfaces, read from
// the depth the face passes just wrote. A corner where a wall meets its slab
// sees half its sky hidden and comes out darker; an open face stays 1.0.
//
// Works in view space, rebuilt from depth with the inverse projection, so
// perspective and parallel views share one path and the radius is in model
// units (the view matrix is rigid).
uniform sampler2D u_depth;      // the scene's resolved depth, full size
uniform mat4 u_proj;
uniform mat4 u_inv_proj;
uniform vec2 u_texel;           // 1 / depth texture size
uniform float u_radius;         // model units
uniform float u_bias;           // model units, against self-occlusion
uniform int u_samples;

in vec2 v_uv;
out vec4 fragColor;

vec3 view_pos(vec2 uv, float d) {
    vec4 p = u_inv_proj * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return p.xyz / p.w;
}

vec3 view_at(vec2 uv) {
    return view_pos(uv, texture(u_depth, uv).r);
}

// A 4x4 ordered set of rotations, one per pixel of each 4x4 tile. The blur
// averages exactly 4x4 texels, so every window holds all sixteen and the
// pattern cancels to a flat tone; white noise left "clouds" on large faces.
float tile_rotation(vec2 frag) {
    ivec2 c = ivec2(frag) & 3;
    int bayer[16] = int[16](0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5);
    return (float(bayer[c.y * 4 + c.x]) + 0.5) / 16.0;
}

void main() {
    // The half-size pass lands its fragment centres on the CORNERS of the
    // full-size depth texels, where NEAREST sampling is ambiguous. Half a
    // texel in lands on a real centre, so p and its neighbours come from
    // one consistent grid (a corner sample made the reconstructed normal
    // wobble and the face self-occlude in vertical bands, #989).
    vec2 uv0 = v_uv + u_texel * 0.5;
    float d = texture(u_depth, uv0).r;
    if (d >= 1.0) {             // sky / background: nothing to occlude
        fragColor = vec4(1.0);
        return;
    }
    vec3 p = view_pos(uv0, d);
    // The depth buffer's own step at this distance (24 bits, so centimetres
    // at a couple of hundred metres in perspective): below it a flat face
    // reads as a staircase, and the stairs as corners — far walls seen
    // square on came out black. The bias never drops under four steps.
    float step = abs(view_pos(uv0, min(d + 4.0 / 16777216.0, 1.0)).z - p.z);
    float bias = max(u_bias, step);
    // Normal from the neighbour on the side with the smaller depth step, so
    // a silhouette does not bend the normal of the face in front.
    vec3 r = view_at(uv0 + vec2(u_texel.x, 0.0)) - p;
    vec3 l = p - view_at(uv0 - vec2(u_texel.x, 0.0));
    vec3 t = view_at(uv0 + vec2(0.0, u_texel.y)) - p;
    vec3 b = p - view_at(uv0 - vec2(0.0, u_texel.y));
    vec3 dx = abs(r.z) < abs(l.z) ? r : l;
    vec3 dy = abs(t.z) < abs(b.z) ? t : b;
    vec3 n = normalize(cross(dx, dy));
    // Towards the eye: along the ray in perspective, straight back in a
    // parallel view (u_proj[2][3] is -1 in perspective, 0 in parallel).
    vec3 to_eye = u_proj[2][3] < -0.5 ? normalize(-p) : vec3(0.0, 0.0, 1.0);
    if (dot(n, to_eye) < 0.0) n = -n;     // face the camera

    // Horizon-based occlusion (after "Practical Realtime Strategies for
    // Accurate Indirect Occlusion", Jimenez et al. 2016). Each direction on
    // the screen cuts a slice through the point; walking it both ways finds
    // the highest surface within the radius on each side — the horizons —
    // and the slice's visibility is the cosine-weighted arc between them, in
    // closed form. Random points in a hemisphere only estimate that arc and
    // their grain read as "clouds" under an overhang; a 90-degree corner now
    // comes out at its true half, not at whatever the sample count gave.
    //
    // The 4x4 tile of rotations is kept: the blur averages exactly one tile,
    // so its sixteen angles (times the directions) cancel to a flat tone.
    float jitter = tile_rotation(gl_FragCoord.xy);
    int dirs = 2;
    int steps = max(u_samples / (2 * dirs), 2);
    // The radius on the screen, in uv per side; w is the clip-space w.
    float w = u_proj[2][3] < -0.5 ? -p.z : 1.0;
    vec2 r_uv = u_radius * 0.5 * vec2(u_proj[0][0], u_proj[1][1]) / w;
    if (r_uv.x < u_texel.x) {          // under a texel: nothing to find
        fragColor = vec4(1.0);
        return;
    }
    // Lifted off its own plane by the bias, so the face's depth noise is
    // never a horizon (the same guard the hemisphere test had).
    vec3 pb = p + n * bias * 2.0;
    float vis = 0.0;
    float open_sky = 0.0;
    for (int di = 0; di < dirs; ++di) {
        float phi = (float(di) + jitter) * 3.14159265 / float(dirs);
        vec2 dir = vec2(cos(phi), sin(phi));
        vec3 d3 = vec3(dir, 0.0);
        vec3 ortho = d3 - dot(d3, to_eye) * to_eye;
        vec3 axis = cross(d3, to_eye);
        vec3 pn = n - axis * dot(n, axis);     // normal in the slice plane
        float pn_len = length(pn);
        if (pn_len < 1e-4) continue;
        float cos_n = clamp(dot(pn, to_eye) / pn_len, -1.0, 1.0);
        float ang_n = sign(dot(ortho, pn)) * acos(cos_n);
        // Start each side at the face's own plane: open sky.
        float h_cos0 = cos(ang_n - 1.5707963);
        float h_cos1 = cos(ang_n + 1.5707963);
        for (int s = 0; s < steps; ++s) {
            // Denser near the point, never on it; the step offset follows
            // the tile too, so neighbours sample between each other.
            float t = (float(s) + fract(jitter * 7.0 + 0.5)) / float(steps);
            t = t * t;
            vec2 off = dir * max(r_uv * t, u_texel * 1.5);
            for (int side = 0; side < 2; ++side) {
                vec2 suv = side == 0 ? uv0 - off : uv0 + off;
                if (suv.x < 0.0 || suv.x > 1.0 || suv.y < 0.0 || suv.y > 1.0)
                    continue;
                float sd = texture(u_depth, suv).r;
                if (sd >= 1.0) continue;        // sky: no horizon there
                vec3 delta = view_pos(suv, sd) - pb;
                float dist = length(delta);
                if (dist < 1e-6) continue;
                float shc = dot(delta / dist, to_eye);
                // Counts whole only close by, and fades from half the
                // radius out to one and a half: the corner is darkest at the
                // contact and opens out softly, and a surface far in front
                // of the point (a separate object between us and it) is no
                // corner at all.
                float fall = 1.0 - smoothstep(0.5 * u_radius, 1.5 * u_radius, dist);
                if (side == 0) {
                    h_cos0 = max(h_cos0, mix(cos(ang_n - 1.5707963), shc, fall));
                } else {
                    h_cos1 = max(h_cos1, mix(cos(ang_n + 1.5707963), shc, fall));
                }
            }
        }
        float h0 = ang_n + max(-acos(h_cos0) - ang_n, -1.5707963);
        float h1 = ang_n + min(acos(h_cos1) - ang_n, 1.5707963);
        float sn = sin(ang_n);
        float a0 = -cos(2.0 * h0 - ang_n) + cos_n + 2.0 * h0 * sn;
        float a1 = -cos(2.0 * h1 - ang_n) + cos_n + 2.0 * h1 * sn;
        vis += pn_len * 0.25 * (a0 + a1);
        // What this slice gives with nothing in the way. Its integral over
        // every direction is exactly 1, but two slices a pixel only add up
        // to about it: an open floor came out a shade grey all over.
        open_sky += pn_len * (cos_n + ang_n * sn);
    }
    vis = open_sky > 1e-4 ? clamp(vis / open_sky, 0.0, 1.0) : 1.0;
    // A face seen nearly edge on: its normal, read off a depth that jumps
    // from pixel to pixel, is noise, and the noise reads as occlusion (a
    // roof's far slope came out black). Fade the term out there.
    float facing = dot(n, to_eye);
    vis = mix(1.0, vis, smoothstep(0.08, 0.3, facing));
    fragColor = vec4(vec3(vis), 1.0);
}
