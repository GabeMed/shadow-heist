#version 330 core
uniform vec4 p3d_ColorScale;
in vec4 v_color;
out vec4 fragColor;
void main() {
    fragColor = v_color * p3d_ColorScale;
}
