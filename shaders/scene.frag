#version 330 core
// scene.frag — Blinn-Phong evaluation for ambient + directional moonlight
// (with PCF shadow mapping) + N attenuated point lights.

#define MAX_POINT_LIGHTS 16

uniform vec3 ambient_color;

uniform vec3 dir_light_dir;
uniform vec3 dir_light_color;

uniform int  num_point_lights;
uniform vec3 point_pos   [MAX_POINT_LIGHTS];
uniform vec3 point_color [MAX_POINT_LIGHTS];
uniform vec3 point_atten [MAX_POINT_LIGHTS];

uniform vec3 camera_world_pos;
uniform vec4 p3d_ColorScale;

uniform sampler2D shadow_map;

in vec3 v_world_pos;
in vec3 v_world_normal;
in vec4 v_color;
in vec4 v_shadow_clip;

out vec4 fragColor;

// PCF 3x3 sample. Returns 1.0 = fully lit, 0.0 = fully shadowed.
float sample_shadow(vec3 N, vec3 L) {
    if (v_shadow_clip.w <= 0.0) return 1.0;

    vec3 ndc = v_shadow_clip.xyz / v_shadow_clip.w;
    vec2 uv  = ndc.xy * 0.5 + 0.5;
    float current = ndc.z * 0.5 + 0.5;

    // Outside the shadow-camera frustum: assume lit.
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0 || current > 1.0) {
        return 1.0;
    }

    // Slope-scaled bias to avoid shadow acne on slanted surfaces.
    float ndotl = max(dot(N, L), 0.0);
    float bias  = max(0.0035 * (1.0 - ndotl), 0.0008);

    vec2 texel = 1.0 / vec2(textureSize(shadow_map, 0));
    float shade = 0.0;
    for (int x = -1; x <= 1; ++x) {
        for (int y = -1; y <= 1; ++y) {
            float depth = texture(shadow_map, uv + vec2(x, y) * texel).r;
            shade += (current - bias > depth) ? 0.0 : 1.0;
        }
    }
    return shade / 9.0;
}

void main() {
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(camera_world_pos - v_world_pos);

    vec3 base = v_color.rgb * p3d_ColorScale.rgb;
    vec3 lit  = ambient_color * base;

    // Directional moonlight + shadow.
    {
        vec3  L      = normalize(dir_light_dir);
        float diff   = max(dot(N, L), 0.0);
        vec3  H      = normalize(L + V);
        float spec   = pow(max(dot(N, H), 0.0), 32.0);
        float shadow = sample_shadow(N, L);

        lit += base * dir_light_color * diff * shadow;
        lit += dir_light_color * spec * 0.20 * shadow;
    }

    int count = min(num_point_lights, MAX_POINT_LIGHTS);
    for (int i = 0; i < count; ++i) {
        vec3  to_light = point_pos[i] - v_world_pos;
        float dist     = length(to_light);
        vec3  L        = to_light / max(dist, 1e-4);

        float att = 1.0 / max(point_atten[i].x
                            + point_atten[i].y * dist
                            + point_atten[i].z * dist * dist, 1e-4);

        float diff = max(dot(N, L), 0.0);
        vec3  H    = normalize(L + V);
        float spec = pow(max(dot(N, H), 0.0), 48.0);

        lit += base * point_color[i] * diff * att;
        lit += point_color[i] * spec * 0.35 * att;
    }

    fragColor = vec4(lit, v_color.a * p3d_ColorScale.a);
}
