#version 330 core
noperspective in vec2 g_pixel;
flat in float g_length;
flat in vec2 g_width;
flat in vec3 g_color;
flat in vec3 g_info;
flat in vec4 g_dash0;
flat in vec4 g_dash1;
flat in vec2 g_caps;
flat in vec2 g_depth_side;
flat in vec2 g_depth_along;
uniform float u_endpoint;
uniform float u_scale;
uniform int u_dashes;
uniform int u_hidden;
uniform float u_hidden_fade;
uniform float u_fade;
uniform vec3 u_background;
uniform vec3 u_fade_color;
out vec4 fragColor;
void main() {
    float along = g_pixel.x;
    if (u_hidden == 1 && u_hidden_fade < 0.01) {
        if (mod(max(along, 0.0), 8.0 * u_scale) >= 4.0 * u_scale) discard;
    } else if (u_dashes == 1 && g_info.z > 0.5) {
        int count = int(g_info.z + 0.5);
        float period = 0.0;
        for (int i=0; i<8; i++) {
            if (i < count) period += i < 4 ? g_dash0[i] : g_dash1[i - 4];
        }
        float t = mod(max(along, 0.0) / u_scale, max(period, 0.001));
        for (int i=0; i<8; i++) {
            if (i >= count) break;
            float step = i < 4 ? g_dash0[i] : g_dash1[i - 4];
            if (t < step) { if (i % 2 == 1) discard; break; }
            t -= step;
        }
    }
    float width = mix(g_width.x, g_width.y, clamp(along / g_length, 0.0, 1.0));
    if (u_endpoint > 0.0 && ((g_caps.x > 0.5 && along >= 0.0 && along < u_endpoint * u_scale)
            || (g_caps.y > 0.5 && along <= g_length && along > g_length - u_endpoint * u_scale))) {
        width += 2.0 * u_scale;
    }
    float coverage = clamp(width * 0.5 + 0.5 - abs(g_pixel.y), 0.0, 1.0);
    if (coverage <= 0.0) discard;
    // Match adjacent faces at each covered pixel, rather than pulling the
    // entire expanded quad forward. Its center keeps the real edge depth.
    float extension = min(along, 0.0) + max(along - g_length, 0.0);
    vec2 delta = g_depth_side * g_pixel.y + g_depth_along * extension;
    // Depth is tested at MSAA samples, while varyings are evaluated at
    // the pixel center. Cover that subpixel difference on sloped faces.
    float margin = 0.75 * (max(abs(g_depth_side.x), abs(g_depth_side.y))
                         + max(abs(g_depth_along.x), abs(g_depth_along.y)));
    float bias = min(max(0.0, -min(delta.x, delta.y)) + margin, 0.01) + 1e-6;
    gl_FragDepth = max(0.0, gl_FragCoord.z - bias * 0.5);
    vec3 color = mix(g_color, u_background, u_hidden_fade);
    color = mix(color, u_fade_color, u_fade);
    fragColor = vec4(color, coverage);
}
