#version 330 core
// skybox.frag — gradient sky + fbm nebula + moon disc + glow halo.

in vec3 v_view_dir;
out vec4 fragColor;

uniform vec3  moon_dir;        // direction TO moon, normalized
uniform float moon_size;       // angular radius in [0,1] of dot(view, moon_dir) threshold
uniform vec3  moon_color;
uniform vec3  nebula_tint;
uniform float time;

// Hash + value-noise fbm.
float hash(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float vnoise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float n000 = hash(i + vec3(0,0,0));
    float n100 = hash(i + vec3(1,0,0));
    float n010 = hash(i + vec3(0,1,0));
    float n110 = hash(i + vec3(1,1,0));
    float n001 = hash(i + vec3(0,0,1));
    float n101 = hash(i + vec3(1,0,1));
    float n011 = hash(i + vec3(0,1,1));
    float n111 = hash(i + vec3(1,1,1));
    float nx00 = mix(n000, n100, f.x);
    float nx10 = mix(n010, n110, f.x);
    float nx01 = mix(n001, n101, f.x);
    float nx11 = mix(n011, n111, f.x);
    float nxy0 = mix(nx00, nx10, f.y);
    float nxy1 = mix(nx01, nx11, f.y);
    return mix(nxy0, nxy1, f.z);
}

float fbm(vec3 p) {
    float a = 0.0;
    float w = 0.5;
    for (int i = 0; i < 5; ++i) {
        a += w * vnoise(p);
        p = p * 2.07 + vec3(13.0, 7.0, 3.0);
        w *= 0.5;
    }
    return a;
}

void main() {
    vec3 V = normalize(v_view_dir);

    // Vertical gradient: low horizon (warm dark) → zenith (deep blue/black).
    float h  = clamp(V.z * 0.5 + 0.5, 0.0, 1.0);
    vec3 horizon = vec3(0.045, 0.030, 0.060);
    vec3 zenith  = vec3(0.005, 0.008, 0.020);
    vec3 sky     = mix(horizon, zenith, smoothstep(0.35, 1.0, h));

    // Nebula clouds: layered fbm with slow drift; modulated by altitude.
    vec3 nebP = V * 3.5 + vec3(0.0, 0.0, time * 0.01);
    float n  = fbm(nebP);
    float n2 = fbm(nebP * 2.3 + vec3(11.0, 5.0, 2.0));
    float clouds = smoothstep(0.40, 0.85, n) * (0.55 + 0.45 * n2);
    clouds *= smoothstep(0.10, 0.45, h);   // fade clouds near horizon
    sky += nebula_tint * clouds * 0.55;

    // Stars: pinpoint hash threshold, denser away from moon.
    float star_field = hash(floor(V * 220.0));
    float stars = smoothstep(0.997, 1.0, star_field) * (0.6 + 0.4 * fbm(V * 5.0));
    sky += vec3(0.85, 0.88, 1.0) * stars * (1.0 - clouds * 0.7);

    // Moon disc + soft halo.
    float md = dot(V, normalize(moon_dir));
    float disc = smoothstep(1.0 - moon_size,        1.0 - moon_size * 0.3, md);
    float halo = smoothstep(1.0 - moon_size * 8.0,  1.0,                   md) * 0.45;
    sky += moon_color * (disc * 1.4 + halo);

    fragColor = vec4(sky, 1.0);
}
