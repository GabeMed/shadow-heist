#version 330 core
// Depth-only shadow pass. Writes only gl_Position so the GPU fills the
// shadow map's depth attachment from the directional light's POV.

uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
