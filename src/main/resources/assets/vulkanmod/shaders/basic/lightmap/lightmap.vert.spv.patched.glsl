#version 450
layout(std140, binding = 0) uniform VKUniforms {
    mat4 ModelViewMat;
    mat4 ProjMat;
};
#extension GL_ARB_shader_draw_parameters : require

layout(location = 0) in vec3 Position;
layout(location = 1) in vec2 UV0;

layout(location = 0) out vec2 texCoord0;

void main() {
    gl_Position = VKUniforms.ProjMat * VKUniforms.ModelViewMat * vec4(Position, 1.0);

    texCoord0 = UV0;
}
