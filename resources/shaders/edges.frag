#version 330 core
noperspective in vec2 g_pixel;
flat in float g_length;
flat in vec2 g_width;
flat in vec3 g_color;
flat in vec3 g_info;
flat in vec4 g_dash0;
flat in vec4 g_dash1;
flat in vec2 g_caps;
flat in vec2 g_limits;
flat in int g_cap;
flat in vec2 g_depth_side;
flat in vec2 g_depth_along;
uniform float u_endpoint;
uniform int u_endpoint_type;
uniform float u_endpoint_size;
uniform int u_marker_pass;
uniform float u_scale;
uniform int u_dashes;
uniform int u_hidden;
uniform float u_hidden_fade;
uniform float u_fade;
uniform vec3 u_background;
uniform vec3 u_fade_color;
out vec4 fragColor;

// Positive signed coverage inside a marker, measured in framebuffer pixels.
float marker(vec2 point, float radius) {
    if (u_endpoint_type == 1) return radius - length(point);
    if (u_endpoint_type == 2) return radius - max(abs(point.x), abs(point.y));
    return min(radius + point.y, (radius - point.y - 2.0 * abs(point.x)) / sqrt(5.0));
}

float stroke_coverage() {
    float along = g_pixel.x;
    bool gap = false;
    if (u_hidden == 1 && u_hidden_fade < 0.01) {
        gap = mod(max(along, 0.0), 8.0 * u_scale) >= 4.0 * u_scale;
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
            if (t < step) { gap = i % 2 == 1; break; }
            t -= step;
        }
    }
    float width = mix(g_width.x, g_width.y, clamp(along / g_length, 0.0, 1.0));
    if (u_endpoint > 0.0 && u_endpoint_type == 0 && ((g_caps.x > 0.5 && along >= 0.0 && along < u_endpoint * u_scale)
            || (g_caps.y > 0.5 && along <= g_length && along > g_length - u_endpoint * u_scale))) {
        width += 2.0 * u_scale;
    }
    float radius = width * 0.5;
    float distance = min(radius - abs(g_pixel.y), min(along - g_limits.x, g_limits.y - along));
    if (g_cap == 1 || g_cap == 3) {
        // Flush rounded ends fit inside the requested length. Extended
        // rounded ends use the same capsule, with a quarter-width overhang.
        float rx = min(radius, (g_limits.y - g_limits.x) * 0.5);
        float center = clamp(along, g_limits.x + rx, g_limits.y - rx);
        bool at_cut = (g_caps.x < 0.5 && along < g_limits.x + rx)
                   || (g_caps.y < 0.5 && along > g_limits.y - rx);
        if (!at_cut) distance = (1.0 - length(vec2((along - center) / max(rx, 1e-4),
                                                  g_pixel.y / radius))) * min(rx, radius);
    }
    return gap ? 0.0 : clamp(distance + 0.5, 0.0, 1.0);
}

void main() {
    float coverage = u_marker_pass == 1
        ? clamp(marker(g_pixel, u_endpoint_size * u_scale * 0.5) + 0.5, 0.0, 1.0)
        : stroke_coverage();
    if (coverage <= 0.0) discard;
    // Match adjacent faces at each covered pixel, rather than pulling the
    // entire expanded quad forward. Its center keeps the real edge depth.
    float along = g_pixel.x;
    float extension = min(along, 0.0) + max(along - g_length, 0.0);
    vec2 delta = g_depth_side * g_pixel.y + g_depth_along * extension;
    if (u_marker_pass == 1) delta = -g_depth_side * abs(g_pixel.y) - g_depth_along * abs(g_pixel.x);
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
