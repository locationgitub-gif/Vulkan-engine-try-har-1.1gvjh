#version 450
layout(std140, binding = 0) uniform VKUniforms {
    mat4 ModelViewMat;
    mat4 ProjMat;
};

#version 450

vec4 projection_from_position(vec4 position) {
    vec4 projection = position * 0.5;
    projection.xy = vec2(projection.x + projection.w, projection.y + projection.w);
    projection.zw = position.zw;
    return projection;
}

layout(location = 0) in vec3 Position;

layout(location = 0) out vec4 texProj0;

void main() {
    gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);

    texProj0 = projection_from_position(gl_Position);
}
