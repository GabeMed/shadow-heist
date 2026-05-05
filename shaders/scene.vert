#version 330 core
// scene.vert — world-space lighting setup for level geometry and props.
// Forwards world-space position + normal to the fragment stage so the
// fragment shader can run a multi-light Blinn-Phong evaluation.

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;

in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec4 p3d_Color;

out vec3 v_world_pos;
out vec3 v_world_normal;
out vec4 v_color;

void main() {
    // World-space position for per-fragment light vectors.
    vec4 wpos = p3d_ModelMatrix * p3d_Vertex;
    v_world_pos = wpos.xyz;

    // Normal transform: mat3(ModelMatrix) is correct for uniform scale only,
    // which holds for our axis-aligned level geometry. Non-uniform scale
    // would require the inverse-transpose explicitly.
    v_world_normal = normalize(mat3(p3d_ModelMatrix) * p3d_Normal);

    v_color = p3d_Color;
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
