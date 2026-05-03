#version 130

uniform vec3  light_dir_view;  // direção PARA a luz, em view space
uniform vec4  light_color;
uniform vec4  ambient_color;
uniform vec4  rim_color;
uniform float rim_power;
uniform vec4  p3d_ColorScale;  // usado pela camuflagem (setColorScale)

in vec3 v_normal;
in vec3 v_pos;
in vec4 v_color;

out vec4 p3d_FragColor;

void main() {
    vec3 N = normalize(v_normal);
    vec3 V = normalize(-v_pos);          // direção para a câmera (view space)
    vec3 L = normalize(light_dir_view);

    // Difuso (Lambert)
    float diff = max(dot(N, L), 0.0);

    // Especular (Blinn-Phong)
    vec3  H    = normalize(L + V);
    float spec = pow(max(dot(N, H), 0.0), 80.0);

    // Rim light / Fresnel: bordas perpendiculares à câmera ficam brilhantes
    float rim = pow(1.0 - max(dot(N, V), 0.0), rim_power);

    vec3 base  = v_color.rgb;
    vec3 color = base * (ambient_color.rgb + diff * light_color.rgb)
               + spec * 0.35 * vec3(0.30, 0.35, 0.50)
               + rim  * rim_color.rgb;

    p3d_FragColor = vec4(color, 1.0) * p3d_ColorScale;
}
