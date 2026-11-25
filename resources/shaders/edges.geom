#version 330 core
layout(lines) in;
layout(triangle_strip, max_vertices=4) out;
in EdgeVertex {
    vec3 world;
    vec3 normal0;
    vec3 normal1;
    vec3 color;
    vec3 info;
    vec4 dash0;
    vec4 dash1;
} edge[];
uniform vec2 u_viewport;
uniform vec3 u_eye;
uniform vec3 u_forward;
uniform int u_perspective;
uniform int u_edges;
uniform int u_profiles;
uniform float u_profile_width;
uniform int u_profile_cap;
uniform float u_depth_width;
uniform float u_depth_near;
uniform float u_depth_range;
uniform float u_extension;
uniform float u_endpoint;
uniform int u_endpoint_type;
uniform float u_endpoint_size;
uniform int u_marker_pass;
uniform float u_scale;
uniform int u_color_mode;
uniform vec3 u_color;
uniform vec3 u_axis0;
uniform vec3 u_axis1;
uniform vec3 u_axis2;
uniform vec4 u_clip_plane;
uniform mat4 u_plane_to_clip;
uniform int u_clip_enable;
uniform vec4 u_style_ground_clip;
out float g_ground_distance;
uniform int u_hidden;
noperspective out vec2 g_pixel;
flat out float g_length;
flat out vec2 g_width;
flat out vec3 g_color;
flat out vec3 g_info;
flat out vec4 g_dash0;
flat out vec4 g_dash1;
flat out vec2 g_caps;
flat out vec2 g_limits;
flat out int g_cap;
flat out vec2 g_depth_side;
flat out vec2 g_depth_along;
float line_length;
vec2 line_width;
vec3 line_color;
vec2 plane_slope0;
vec2 plane_slope1;
vec2 line_caps;
vec2 line_limits;
int line_cap;
vec2 depth_side;
vec2 depth_along;
float line_depth_start;
float line_depth_step;

vec2 plane_slope(vec3 normal, vec3 world) {
    vec4 plane = u_plane_to_clip * vec4(normal, -dot(normal, world));
    return abs(plane.z) > 1e-8 ? -plane.xy / plane.z : vec2(0.0);
}

bool clip_segment(inout vec4 a, inout vec4 b, inout vec3 wa, inout vec3 wb,
                  float da, float db, inout bvec2 cut) {
    if (da < 0.0 && db < 0.0) return false;
    if (da < 0.0) {
        float t = da / (da - db);
        a = mix(a, b, t); wa = mix(wa, wb, t); cut.x = true;
    } else if (db < 0.0) {
        float t = db / (db - da);
        b = mix(b, a, t); wb = mix(wb, wa, t); cut.y = true;
    }
    return true;
}

void corner(vec4 center, vec3 world, vec2 shift, float along, float side) {
    g_ground_distance = dot(vec4(world, 1.0), u_style_ground_clip);
    gl_Position = center + vec4(shift * 2.0 / u_viewport * center.w, 0.0, 0.0);
    if (u_marker_pass == 0) {
        // Expanded XY corners must extrapolate the line's depth as well.
        // Keeping the old endpoint Z compresses the depth slope over the
        // longer quad and lets adjacent faces cut translucent blocks into it.
        gl_Position.z = (line_depth_start + along * line_depth_step) * center.w;
    }
    gl_ClipDistance[0] = u_clip_enable == 1 ? dot(vec4(world, 1.0), u_clip_plane) : 1.0;
    g_pixel = vec2(along, side);
    g_length = line_length;
    g_width = line_width;
    g_color = line_color;
    g_info = edge[0].info;
    g_dash0 = edge[0].dash0;
    g_dash1 = edge[0].dash1;
    g_caps = line_caps;
    g_limits = line_limits;
    g_cap = line_cap;
    g_depth_side = depth_side;
    g_depth_along = depth_along;
    EmitVertex();
}

void main() {
    vec4 a = gl_in[0].gl_Position, b = gl_in[1].gl_Position;
    vec3 wa = edge[0].world, wb = edge[1].world;
    if (u_marker_pass == 1) {
        if (a.w <= 1e-7 || a.z + a.w < 0.0) return;
        if (u_clip_enable == 1 && dot(vec4(wa, 1.0), u_clip_plane) < 0.0) return;
        float r = u_endpoint_size * u_scale * 0.5 + 0.5;
        line_length = 1.0; line_width = vec2(1.0);
        line_limits = vec2(0.0); line_caps = vec2(0.0); line_cap = 0;
        depth_along = vec2(edge[0].dash0.x);
        depth_side = vec2(edge[0].dash0.y);
        line_color = u_color;
        if ((u_color_mode == 1 || (u_color_mode == 2 && u_hidden == 0))
                && edge[0].color.x >= 0.0) line_color = edge[0].color;
        // Marker quads use screen axes, independent of each branch's angle.
        corner(a, wa, vec2(-r, -r), -r, -r);
        corner(a, wa, vec2(-r, r), -r, r);
        corner(a, wa, vec2(r, -r), r, -r);
        corner(a, wa, vec2(r, r), r, r);
        EndPrimitive();
        return;
    }
    vec3 direction = wb - wa;
    plane_slope0 = plane_slope(edge[0].normal0, wa);
    plane_slope1 = plane_slope(edge[0].normal1, wa);
    vec3 toward = u_perspective == 1 ? u_eye - (wa + wb) * 0.5 : -u_forward;
    bool profile = edge[0].info.y > 0.5
        || dot(edge[0].normal0, toward) * dot(edge[0].normal1, toward) < 0.0;
    if (edge[0].info.x > 0.5 && !(u_profiles == 1 && profile)) return;
    if (u_edges == 0 && !(u_profiles == 1 && profile)) return;
    bvec2 cut = bvec2(false);
    if (u_clip_enable == 1 && !clip_segment(a, b, wa, wb,
            dot(vec4(wa, 1.0), u_clip_plane), dot(vec4(wb, 1.0), u_clip_plane), cut)) return;
    if (!clip_segment(a, b, wa, wb, a.z + a.w, b.z + b.w, cut)) return;
    if (a.w <= 1e-7 || b.w <= 1e-7) return;
    line_caps = vec2(cut.x ? 0.0 : 1.0, cut.y ? 0.0 : 1.0);
    vec2 delta = (b.xy / b.w - a.xy / a.w) * u_viewport * 0.5;
    float len = length(delta);
    if (len < 1e-4) return;
    line_depth_start = a.z / a.w;
    line_depth_step = (b.z / b.w - line_depth_start) / len;
    vec2 tangent = delta / len, normal = vec2(-tangent.y, tangent.x);
    depth_side = vec2(dot(plane_slope0, normal * 2.0 / u_viewport),
                      dot(plane_slope1, normal * 2.0 / u_viewport));
    depth_along = vec2(dot(plane_slope0, tangent * 2.0 / u_viewport),
                       dot(plane_slope1, tangent * 2.0 / u_viewport));
    float base = u_profiles == 1 && profile ? u_profile_width : 1.0;
    vec2 depth = vec2(dot(wa - u_eye, u_forward), dot(wb - u_eye, u_forward));
    vec2 widths = max(vec2(base), mix(vec2(1.0), vec2(max(1.0, u_depth_width)),
        clamp(vec2(1.0) - (depth - u_depth_near) / max(u_depth_range, 1e-4), 0.0, 1.0))) * u_scale;
    float before = cut.x ? 0.0 : u_extension * u_scale;
    float after = cut.y ? 0.0 : u_extension * u_scale;
    // A retraction that consumes a short segment hides it, never reverses it.
    if (len + before + after <= 1e-4) return;
    line_cap = u_profiles == 1 && profile ? u_profile_cap : 0;
    line_limits = vec2(-before, len + after);
    if (line_cap >= 2) {
        float inset = line_cap == 2 ? 2.0 * u_scale : 0.0;
        if (!cut.x) line_limits.x -= max(0.0, widths.x * 0.5 - inset);
        if (!cut.y) line_limits.y += max(0.0, widths.y * 0.5 - inset);
    }
    float radius = max(widths.x, widths.y) * 0.5;
    if (u_endpoint > 0.0 && u_endpoint_type == 0) radius += u_scale;
    radius += 0.5;
    before = -line_limits.x + 0.5;
    after = line_limits.y - len + 0.5;
    line_length = len; line_width = widths;
    line_color = u_color;
    if (u_color_mode == 1 && edge[0].color.x >= 0.0) line_color = edge[0].color;
    if (u_color_mode == 2 && u_hidden == 0) {
        vec3 d = normalize(direction);
        if (abs(dot(d, u_axis0)) >= 0.999999) line_color = vec3(0.85, 0.20, 0.20);
        else if (abs(dot(d, u_axis1)) >= 0.999999) line_color = vec3(0.20, 0.65, 0.25);
        else if (abs(dot(d, u_axis2)) >= 0.999999) line_color = vec3(0.20, 0.35, 0.90);
    }
    corner(a, wa, -tangent * before - normal * radius, -before, -radius);
    corner(a, wa, -tangent * before + normal * radius, -before, radius);
    corner(b, wb, tangent * after - normal * radius, len + after, -radius);
    corner(b, wb, tangent * after + normal * radius, len + after, radius);
    EndPrimitive();
}
