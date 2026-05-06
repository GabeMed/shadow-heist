#version 330 core
// scene.frag — Blinn-Phong shading + raytraced AABB shadows.
//
// Replaces the previous shadow-map pipeline with a Whitted-style hard-shadow
// pass: every fragment casts a ray toward each light and slab-tests against
// every wall/door AABB uploaded by the Python side. Hits before the light →
// no diffuse / no specular. Compared to shadow maps this gets us correct
// self-shadowing of arbitrarily-oriented geometry, omnidirectional point
// shadows for free, and crisp pixel-perfect contact shadows — the same
// qualitative wins an "RTX" pipeline advertises.

#define MAX_POINT_LIGHTS 32
#define MAX_AABBS        256

uniform vec3 ambient_color;

uniform vec3 dir_light_dir;
uniform vec3 dir_light_color;

uniform int  num_point_lights;
uniform vec3 point_pos   [MAX_POINT_LIGHTS];
uniform vec3 point_color [MAX_POINT_LIGHTS];
uniform vec3 point_atten [MAX_POINT_LIGHTS];

uniform vec3 camera_world_pos;
uniform vec4 p3d_ColorScale;

uniform vec3  fog_color;
uniform float fog_density;

// Raytraced shadow scene: list of axis-aligned bounding boxes.
uniform int  num_aabbs;
uniform vec3 aabb_min[MAX_AABBS];
uniform vec3 aabb_max[MAX_AABBS];

uniform sampler2D p3d_Texture0;

in vec3 v_world_pos;
in vec3 v_world_normal;
in vec4 v_color;
in vec2 v_uv;

out vec4 fragColor;

// Slab test: returns true if `ro + t*rd` enters any AABB while
// 0 < t < tmax. Branch-free per box, with an accumulator per ray.
bool ray_hits_world(vec3 ro, vec3 rd, float tmax) {
    vec3 inv = 1.0 / rd;
    int count = min(num_aabbs, MAX_AABBS);
    for (int i = 0; i < count; ++i) {
        vec3 t1 = (aabb_min[i] - ro) * inv;
        vec3 t2 = (aabb_max[i] - ro) * inv;
        vec3 tmin3 = min(t1, t2);
        vec3 tmax3 = max(t1, t2);
        float tnear = max(max(tmin3.x, tmin3.y), tmin3.z);
        float tfar  = min(min(tmax3.x, tmax3.y), tmax3.z);
        // Hit if interval is non-empty AND ends before the light AND
        // starts in front of the surface (ignore self-hit at t≈0).
        if (tfar > max(tnear, 0.0008) && tnear < tmax) {
            return true;
        }
    }
    return false;
}

void main() {
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(camera_world_pos - v_world_pos);

    vec4 tex_sample = texture(p3d_Texture0, v_uv);
    vec3 base = v_color.rgb * p3d_ColorScale.rgb * tex_sample.rgb;
    vec3 lit  = ambient_color * base;

    // Bias the ray origin off the surface so we don't self-occlude.
    vec3 ro_base = v_world_pos + N * 0.01;

    // Directional moonlight + raytraced shadow.
    {
        vec3  L      = normalize(dir_light_dir);
        float diff   = max(dot(N, L), 0.0);
        if (diff > 0.0) {
            // Send the shadow ray "to infinity" along the light direction.
            // 500 world units is well past any wall in the scene.
            bool blocked = ray_hits_world(ro_base, L, 500.0);
            if (!blocked) {
                vec3  H    = normalize(L + V);
                float spec = pow(max(dot(N, H), 0.0), 32.0);
                lit += base * dir_light_color * diff;
                lit += dir_light_color * spec * 0.20;
            }
        }
    }

    int count = min(num_point_lights, MAX_POINT_LIGHTS);
    for (int i = 0; i < count; ++i) {
        vec3  to_light = point_pos[i] - v_world_pos;
        float dist     = length(to_light);
        vec3  L        = to_light / max(dist, 1e-4);

        float att = 1.0 / max(point_atten[i].x
                            + point_atten[i].y * dist
                            + point_atten[i].z * dist * dist, 1e-4);

        // Cheap early-out: if the light is too dim at this distance to push a
        // visible pixel through (after ambient), skip the shadow ray entirely.
        float strength = att * max(max(point_color[i].r, point_color[i].g),
                                                          point_color[i].b);
        if (strength < 0.01) continue;

        float diff = max(dot(N, L), 0.0);
        if (diff <= 0.0) continue;

        // Cast frag → light point. tmax = dist so anything past the light
        // doesn't count. Self-bias already in ro_base.
        bool blocked = ray_hits_world(ro_base, L, dist - 0.02);
        if (blocked) continue;

        vec3  H    = normalize(L + V);
        float spec = pow(max(dot(N, H), 0.0), 48.0);

        lit += base * point_color[i] * diff * att;
        lit += point_color[i] * spec * 0.35 * att;
    }

    if (fog_density > 0.0) {
        float dist = length(camera_world_pos - v_world_pos);
        float f    = exp(-fog_density * dist);
        lit = mix(fog_color, lit, clamp(f, 0.0, 1.0));
    }

    fragColor = vec4(lit, v_color.a * p3d_ColorScale.a);
}
