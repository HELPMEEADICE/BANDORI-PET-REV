// Native MToon 0.x / VRMC_materials_mtoon 1.0. See docs/VRM_DESKTOP_PET.md.
struct Camera { matrix: mat4x4<f32>, frame: vec4<f32> };
struct Material {
    color: vec4<f32>, shade: vec4<f32>, emission: vec4<f32>, rim: vec4<f32>,
    outline: vec4<f32>, toon: vec4<f32>, rim_params: vec4<f32>, matcap: vec4<f32>,
    uv_transform: vec4<f32>, uv_animation: vec4<f32>, legacy: vec4<f32>, reserved: vec4<f32>,
};
@group(0) @binding(0) var<uniform> camera: Camera;
@group(1) @binding(0) var main_map: texture_2d<f32>;
@group(1) @binding(1) var shade_map: texture_2d<f32>;
@group(1) @binding(2) var normal_map: texture_2d<f32>;
@group(1) @binding(3) var emission_map: texture_2d<f32>;
@group(1) @binding(4) var rim_map: texture_2d<f32>;
@group(1) @binding(5) var matcap_map: texture_2d<f32>;
@group(1) @binding(6) var outline_map: texture_2d<f32>;
@group(1) @binding(7) var uv_mask: texture_2d<f32>;
@group(1) @binding(8) var shift_map: texture_2d<f32>;
@group(1) @binding(9) var map_sampler: sampler;
@group(1) @binding(10) var<uniform> material: Material;
struct Output {
    @builtin(position) position: vec4<f32>,
    @location(0) normal: vec3<f32>, @location(1) uv: vec2<f32>,
    @location(2) view_position: vec3<f32>,
};
fn srgb_to_linear(c: vec3<f32>) -> vec3<f32> {
    return select(pow((c + 0.055) / 1.055, vec3<f32>(2.4)), c / 12.92, c <= vec3<f32>(0.04045));
}
fn linear_to_srgb(c: vec3<f32>) -> vec3<f32> {
    let v = max(c, vec3<f32>(0.0));
    return select(1.055 * pow(v, vec3<f32>(1.0/2.4)) - 0.055, v * 12.92, v <= vec3<f32>(0.0031308));
}
fn rotate_uv(uv: vec2<f32>, angle: f32) -> vec2<f32> {
    let c = cos(angle); let s = sin(angle);
    return vec2<f32>(c * uv.x - s * uv.y, s * uv.x + c * uv.y);
}
fn transformed_uv(uv: vec2<f32>) -> vec2<f32> {
    let base = rotate_uv(uv * material.uv_transform.zw, material.uv_animation.w) + material.uv_transform.xy;
    let texel = textureSampleLevel(uv_mask, map_sampler, base, 0.0);
    let mask = select(texel.b, texel.r, material.legacy.x > 0.5);
    let time = camera.frame.x * mask;
    return rotate_uv(base - 0.5, material.uv_animation.z * time) + 0.5 + material.uv_animation.xy * time;
}
fn projected(p: vec3<f32>, n: vec3<f32>, uv: vec2<f32>) -> Output {
    var out: Output;
    let xy = camera.matrix * vec4<f32>(p.xy, 0.0, 1.0);
    // Constant w: parallel rays, no perspective foreshortening.
    out.position = vec4<f32>(xy.xy, clamp(0.5 + p.z * camera.frame.w, 0.001, 0.999), 1.0);
    out.normal = n; out.uv = uv; out.view_position = p;
    return out;
}
@vertex fn vs_main(@location(0) p: vec3<f32>, @location(1) n: vec3<f32>, @location(2) uv: vec2<f32>) -> Output {
    return projected(p, n, uv);
}
@vertex fn vs_outline(@location(0) p: vec3<f32>, @location(1) n: vec3<f32>, @location(2) uv: vec2<f32>) -> Output {
    let final_uv = transformed_uv(uv);
    let texel = textureSampleLevel(outline_map, map_sampler, final_uv, 0.0);
    let mask = select(texel.g, texel.r, material.legacy.x > 0.5);
    let width = material.outline.w * mask;
    var out = projected(p + normalize(n) * width, n, uv);
    if material.rim_params.w > 1.5 {
        out = projected(p, n, uv);
        let direction = vec2<f32>(camera.matrix[0].x * n.x, camera.matrix[1].y * n.y);
        let aspect = camera.frame.z / max(camera.frame.y, 1.0);
        let offset = direction / max(length(direction), 0.00001) * vec2<f32>(aspect, 1.0);
        out.position.x += offset.x * width * 2.0 * (1.0 - abs(n.z));
        out.position.y += offset.y * width * 2.0 * (1.0 - abs(n.z));
    }
    return out;
}
fn surface_normal(in: Output, front: bool) -> vec3<f32> {
    let n = normalize(select(-in.normal, in.normal, front));
    let tn = textureSample(normal_map, map_sampler, in.uv).xyz * 2.0 - 1.0;
    let dp1 = dpdx(in.view_position); let dp2 = dpdy(in.view_position);
    let duv1 = dpdx(in.uv); let duv2 = dpdy(in.uv);
    let sign_det = select(-1.0, 1.0, duv1.x * duv2.y - duv1.y * duv2.x >= 0.0);
    let tr = (dp1 * duv2.y - dp2 * duv1.y) * sign_det;
    let br = (dp2 * duv1.x - dp1 * duv2.x) * sign_det;
    let tangent = tr / max(length(tr), 0.00001);
    let bitangent = br / max(length(br), 0.00001);
    return normalize(tangent * tn.x * material.emission.w + bitangent * tn.y * material.emission.w + n * tn.z);
}
fn alpha_value(value: f32) -> f32 {
    if material.toon.w < 0.5 { return 1.0; }
    if material.toon.w < 1.5 {
        if value < material.shade.w { discard; }
        return 1.0;
    }
    if value < 0.003 { discard; }
    return value;
}
fn toon_color(in: Output, normal: vec3<f32>, main: vec3<f32>) -> vec3<f32> {
    let lit = srgb_to_linear(main) * material.color.rgb;
    let shade = srgb_to_linear(textureSample(shade_map, map_sampler, in.uv).rgb) * material.shade.rgb;
    let ndotl = dot(normal, normalize(vec3<f32>(-0.3, 0.7, -0.65)));
    let grade = textureSample(shift_map, map_sampler, in.uv).r;
    var intensity: f32;
    if material.legacy.x > 0.5 {
        let shaded = ((ndotl * 0.5 + 0.5) * (1.0 - material.legacy.y * (1.0 - grade))) * 2.0 - 1.0;
        let upper = mix(1.0, material.toon.x, material.toon.y);
        intensity = clamp((shaded - material.toon.x) / max(0.0001, upper - material.toon.x), 0.0, 1.0);
    } else {
        let shifted = ndotl + material.toon.x + grade * material.legacy.z;
        let feather = max(0.0001, 1.0 - material.toon.y);
        intensity = clamp((shifted + feather) / (2.0 * feather), 0.0, 1.0);
    }
    // Neutral desktop environment: white directional light and soft ambient.
    var color = min(mix(shade, lit, intensity) + lit * 0.08, lit);
    color = mix(color, lit, material.toon.z);
    let rim_factor = pow(clamp(1.0 - dot(normal, vec3<f32>(0.0, 0.0, -1.0)) + material.rim_params.x, 0.0, 1.0), max(material.rim.w, 0.0001));
    let rim = material.rim.rgb * rim_factor;
    let matcap_uv = vec2<f32>(normal.x, -normal.y) * 0.5 + 0.5;
    let matcap = srgb_to_linear(textureSample(matcap_map, map_sampler, matcap_uv).rgb) * material.matcap.rgb;
    let rim_lighting = mix(vec3<f32>(1.0), vec3<f32>(1.08), material.rim_params.y);
    color += (rim + matcap) * srgb_to_linear(textureSample(rim_map, map_sampler, in.uv).rgb) * rim_lighting;
    color += srgb_to_linear(textureSample(emission_map, map_sampler, in.uv).rgb) * material.emission.rgb;
    return color;
}
fn surface(vertex: Output, front: bool, encode: bool, outline: bool) -> vec4<f32> {
    var in = vertex;
    in.uv = transformed_uv(vertex.uv);
    let main = textureSample(main_map, map_sampler, in.uv);
    let n = surface_normal(in, front);
    var color = toon_color(in, n, main.rgb);
    if outline { color = material.outline.rgb * mix(vec3<f32>(1.0), color, material.rim_params.z); }
    // Derivatives and texture samples stay outside alpha-dependent control flow.
    let alpha = alpha_value(main.a * material.color.a);
    if encode { color = linear_to_srgb(color); }
    return vec4<f32>(color * alpha, alpha);
}
@fragment fn fs_main(in: Output, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> { return surface(in, front, true, false); }
@fragment fn fs_main_linear(in: Output, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> { return surface(in, front, false, false); }
@fragment fn fs_outline(in: Output, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> { return surface(in, front, true, true); }
@fragment fn fs_outline_linear(in: Output, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> { return surface(in, front, false, true); }
