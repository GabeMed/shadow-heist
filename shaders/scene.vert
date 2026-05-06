#version 330 core
// scene.vert — pass-through to the raytraced fragment stage.
// Produces world-space position + normal so the fragment can shoot shadow
// rays at the AABB list uploaded from Python.

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;

in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec4 p3d_Color;
in vec2 p3d_MultiTexCoord0;

out vec3 v_world_pos;
out vec3 v_world_normal;
out vec4 v_color;
out vec2 v_uv;

void main() {
    vec4 wpos = p3d_ModelMatrix * p3d_Vertex;
    v_world_pos = wpos.xyz;
    v_world_normal = normalize(mat3(p3d_ModelMatrix) * p3d_Normal);
    v_color = p3d_Color;
    v_uv = p3d_MultiTexCoord0;
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
