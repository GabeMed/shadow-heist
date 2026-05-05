#version 330 core

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelViewMatrix;
uniform mat3 p3d_NormalMatrix;
uniform float time;

in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec4 p3d_Color;

out vec3 v_normal;
out vec3 v_pos;
out vec4 v_color;

void main() {
    // Wobble orgânico: deslocamento senoidal ao longo da normal
    float wobble = sin(time * 1.8 + p3d_Vertex.x * 4.0 + p3d_Vertex.z * 3.0) * 0.025;
    vec4 displaced = p3d_Vertex + vec4(p3d_Normal * wobble, 0.0);

    gl_Position = p3d_ModelViewProjectionMatrix * displaced;
    v_normal    = normalize(p3d_NormalMatrix * p3d_Normal);
    v_pos       = (p3d_ModelViewMatrix * displaced).xyz;
    v_color     = p3d_Color;
}
