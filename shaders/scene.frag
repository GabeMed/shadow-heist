#version 330 core
// scene.frag — Blinn-Phong evaluation for ambient + directional moonlight
// + N attenuated point lights (candles, eye-glow). World-space lighting.
//
// Uniform contract (filled by core/level_manager.py SceneLighting task):
//   ambient_color        : low-light night-mansion fill.
//   dir_light_dir        : direction TO the directional light (moonlight).
//   dir_light_color      : moonlight RGB.
//   num_point_lights     : how many entries in the point arrays are live.
//   point_pos[i]         : world-space position of point light i.
//   point_color[i]       : light color (linear, can exceed 1.0 for HDR-ish).
//   point_atten[i]       : (constant, linear, quadratic) attenuation triple.
//   camera_world_pos     : view origin for the specular half-vector.
//   p3d_ColorScale       : Panda's setColorScale uniform (camo, highlight pulse).

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

in vec3 v_world_pos;
in vec3 v_world_normal;
in vec4 v_color;

out vec4 fragColor;

void main() {
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(camera_world_pos - v_world_pos);

    vec3 base = v_color.rgb * p3d_ColorScale.rgb;

    // Ambient — soft global term so unlit corners don't go pure black.
    vec3 lit = ambient_color * base;

    // Directional moonlight: cool, broad, no attenuation.
    {
        vec3  L    = normalize(dir_light_dir);
        float diff = max(dot(N, L), 0.0);
        vec3  H    = normalize(L + V);
        float spec = pow(max(dot(N, H), 0.0), 32.0);
        lit += base * dir_light_color * diff;
        lit += dir_light_color * spec * 0.20;
    }

    // Point lights — quadratic attenuation, warm bulbs.
    int count = min(num_point_lights, MAX_POINT_LIGHTS);
    for (int i = 0; i < count; ++i) {
        vec3  to_light = point_pos[i] - v_world_pos;
        float dist     = length(to_light);
        vec3  L        = to_light / max(dist, 1e-4);

        // 1 / (k_c + k_l*d + k_q*d^2). atten triple matches Panda3D's
        // PointLight.attenuation convention.
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
