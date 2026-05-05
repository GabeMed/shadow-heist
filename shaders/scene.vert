#version 330 core
// scene.vert — world-space lighting setup for level geometry and props.
// Forwards world-space position + normal to the fragment stage so the
// fragment shader can run a multi-light Blinn-Phong evaluation, and the
// shadow-space clip position for moonlight shadow sampling.

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform mat4 shadow_vp;

in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec4 p3d_Color;
in vec2 p3d_MultiTexCoord0;

out vec3 v_world_pos;
out vec3 v_world_normal;
out vec4 v_color;
out vec4 v_shadow_clip;
out vec2 v_uv;

void main() {
    vec4 wpos = p3d_ModelMatrix * p3d_Vertex;
    v_world_pos = wpos.xyz;
    v_world_normal = normalize(mat3(p3d_ModelMatrix) * p3d_Normal);
    v_color = p3d_Color;
    v_uv = p3d_MultiTexCoord0;

    // Project world position into the moonlight shadow camera's clip space.
    v_shadow_clip = shadow_vp * vec4(wpos.xyz, 1.0);

    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
