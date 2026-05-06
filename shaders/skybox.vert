#version 330 core
// skybox.vert — emits world-space ray direction relative to camera.
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform vec3 camera_world_pos;

in vec4 p3d_Vertex;
out vec3 v_view_dir;

void main() {
    vec4 wpos = p3d_ModelMatrix * p3d_Vertex;
    v_view_dir = normalize(wpos.xyz - camera_world_pos);
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
