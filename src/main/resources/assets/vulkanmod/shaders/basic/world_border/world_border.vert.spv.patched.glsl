#version 450
layout(std140, binding = 0) uniform VKUniforms {
    vec3 ModelOffset;
    mat4 TextureMat;
};
#extension GL_ARB_shader_draw_parameters : require

// Dynamic Transforms - Stub for world_border shader
// Defines model offset and texture matrix for dynamic transformations

vec4 projection_from_position(vec4 position) {
    vec4 projection = position * 0.5;
    projection.xy = vec2(projection.x + projection.w, projection.y + projection.w);
    projection.zw = position.zw;
    return projection;
}

layout(location = 0) in vec3 Position;
layout(location = 1) in vec2 UV0;

layout(location = 0) out vec2 texCoord0;

void main() {
    vec3 pos = Position + ModelOffset;
    gl_Position = ProjMat * ModelViewMat * vec4(pos, 1.0);

    texCoord0 = (TextureMat * vec4(UV0, 0.0, 1.0)).xy;
}
