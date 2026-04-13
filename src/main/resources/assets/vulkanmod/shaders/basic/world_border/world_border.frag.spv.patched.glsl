#version 450
layout(std140, binding = 0) uniform VKUniforms {
    vec3 ModelOffset;
    mat4 TextureMat;
};
#extension GL_ARB_shader_draw_parameters : require

// Dynamic Transforms - Stub for world_border shader
// Defines model offset and texture matrix for dynamic transformations

layout(binding = 1) uniform sampler2D Sampler0;

layout(location = 0) in vec2 texCoord0;

layout(location = 0) out vec4 fragColor;

void main() {
    vec4 color = texture(Sampler0, texCoord0);
    if (color.a == 0.0) {
        discard;
    }
    fragColor = color * ColorModulator;
}
