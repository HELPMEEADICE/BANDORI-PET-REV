// Fullscreen-triangle blit used for the quality (render resolution) downscale and
// for window opacity. The source texture holds premultiplied alpha, so scaling
// both rgb and a by the opacity keeps it valid.

@group(0) @binding(0) var source_texture: texture_2d<f32>;
@group(0) @binding(1) var source_sampler: sampler;
@group(0) @binding(2) var<uniform> options: vec4<f32>;

struct VertexOutput {
  @builtin(position) position: vec4<f32>,
  @location(0) uv: vec2<f32>,
};

@vertex
fn vs_blit(@builtin(vertex_index) index: u32) -> VertexOutput {
  // Oversized triangle covering the whole viewport.
  var positions = array<vec2<f32>, 3>(
    vec2<f32>(-1.0, -1.0),
    vec2<f32>(3.0, -1.0),
    vec2<f32>(-1.0, 3.0),
  );
  let position = positions[index];
  var output: VertexOutput;
  output.position = vec4<f32>(position, 0.0, 1.0);
  // y is flipped between clip space and texture coordinates.
  output.uv = vec2<f32>((position.x + 1.0) * 0.5, (1.0 - position.y) * 0.5);
  return output;
}

@fragment
fn fs_blit(input: VertexOutput) -> @location(0) vec4<f32> {
  let sampled = textureSample(source_texture, source_sampler, input.uv);
  let opacity = options.x;
  return vec4<f32>(sampled.rgb * opacity, sampled.a * opacity);
}
