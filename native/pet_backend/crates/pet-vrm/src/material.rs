//! VRM0 Unity MToon and VRM1 VRMC_materials_mtoon material mapping.
use super::{idx, invalid, number, vec3, Result};
use glam::Vec3;
use serde_json::Value;

#[derive(Clone, Debug)]
pub struct Material {
    pub hit_texture: usize,
    /// Main, shade, normal, emission, rim, matcap, outline width, UV mask,
    /// shading shift/grade. Missing textures have semantic defaults on the GPU.
    pub maps: [Option<usize>; 9],
    pub texture: Option<usize>,
    pub color: [f32; 4],
    pub shade: [f32; 3],
    pub emission: [f32; 3],
    pub normal_scale: f32,
    pub rim: [f32; 3],
    pub rim_power: f32,
    pub rim_lift: f32,
    pub rim_lighting_mix: f32,
    pub matcap: [f32; 3],
    pub outline_color: [f32; 3],
    pub outline_width: f32,
    pub outline_mode: u32,
    pub outline_lighting_mix: f32,
    pub shade_shift: f32,
    pub shade_toony: f32,
    pub cutoff: f32,
    pub alpha_mode: u32,
    pub transparent: bool,
    pub depth_write: bool,
    pub cull: u32,
    pub queue: i32,
    pub unlit: bool,
    pub legacy: bool,
    pub gi: f32,
    pub grade_rate: f32,
    pub shift_scale: f32,
    pub uv_offset: [f32; 2],
    pub uv_scale: [f32; 2],
    pub uv_rotation: f32,
    pub uv_animation: [f32; 3],
}
impl Default for Material {
    fn default() -> Self {
        Self {
            hit_texture: 0,
            maps: [None; 9],
            texture: None,
            color: [1.; 4],
            shade: [0.; 3],
            emission: [0.; 3],
            normal_scale: 1.,
            rim: [0.; 3],
            rim_power: 5.,
            rim_lift: 0.,
            rim_lighting_mix: 1.,
            matcap: [0.; 3],
            outline_color: [0.; 3],
            outline_width: 0.,
            outline_mode: 0,
            outline_lighting_mix: 1.,
            shade_shift: 0.,
            shade_toony: 0.9,
            cutoff: 0.5,
            alpha_mode: 0,
            transparent: false,
            depth_write: true,
            cull: 2,
            queue: 2000,
            unlit: true,
            legacy: false,
            gi: 0.1,
            grade_rate: 1.,
            shift_scale: 1.,
            uv_offset: [0.; 2],
            uv_scale: [1.; 2],
            uv_rotation: 0.,
            uv_animation: [0.; 3],
        }
    }
}
impl Material {
    pub(crate) fn load(
        m: gltf::Material<'_>,
        json: &Value,
        vrm: &Value,
        legacy: bool,
        texture_count: usize,
    ) -> Result<Self> {
        let index = m.index().unwrap();
        let old = &vrm["materialProperties"][index];
        let raw = &json["materials"][index];
        let toon = &raw["extensions"]["VRMC_materials_mtoon"];
        let f = &old["floatProperties"];
        let v = &old["vectorProperties"];
        let textures = &old["textureProperties"];
        let scalar = |old: &str, new: &str, default| {
            number(if legacy { &f[old] } else { &toon[new] }, default)
        };
        let color = |old: &str, new: &str, default| {
            vec3(if legacy { &v[old] } else { &toon[new] }, default).to_array()
        };
        let map = |old: &str, new: &str| {
            if legacy {
                idx(&textures[old])
            } else {
                idx(&toon[new]["index"])
            }
        };
        let pbr = m.pbr_metallic_roughness();
        let main = if legacy {
            idx(&textures["_MainTex"])
        } else {
            None
        }
        .or_else(|| pbr.base_color_texture().map(|t| t.texture().index()));
        let mut result = Self {
            texture: main,
            maps: [
                main,
                map("_ShadeTexture", "shadeMultiplyTexture"),
                if legacy {
                    idx(&textures["_BumpMap"])
                } else {
                    m.normal_texture().map(|t| t.texture().index())
                },
                if legacy {
                    idx(&textures["_EmissionMap"])
                } else {
                    m.emissive_texture().map(|t| t.texture().index())
                },
                map("_RimTexture", "rimMultiplyTexture"),
                map("_SphereAdd", "matcapTexture"),
                map("_OutlineWidthTexture", "outlineWidthMultiplyTexture"),
                map("_UvAnimMaskTexture", "uvAnimationMaskTexture"),
                map("_ShadingGradeTexture", "shadingShiftTexture"),
            ],
            color: if legacy && v["_Color"].is_array() {
                [
                    number(&v["_Color"][0], 1.),
                    number(&v["_Color"][1], 1.),
                    number(&v["_Color"][2], 1.),
                    number(&v["_Color"][3], 1.),
                ]
            } else {
                pbr.base_color_factor()
            },
            shade: color("_ShadeColor", "shadeColorFactor", Vec3::ZERO),
            emission: if legacy {
                vec3(&v["_EmissionColor"], Vec3::ZERO).to_array()
            } else {
                m.emissive_factor()
            },
            normal_scale: if legacy {
                number(&f["_BumpScale"], 1.)
            } else {
                m.normal_texture().map(|t| t.scale()).unwrap_or(1.)
            },
            rim: color("_RimColor", "parametricRimColorFactor", Vec3::ZERO),
            rim_power: scalar("_RimFresnelPower", "parametricRimFresnelPowerFactor", 5.),
            rim_lift: scalar("_RimLift", "parametricRimLiftFactor", 0.),
            rim_lighting_mix: scalar("_RimLightingMix", "rimLightingMixFactor", 1.),
            matcap: if legacy && textures["_SphereAdd"].is_u64() {
                [1.; 3]
            } else {
                vec3(&toon["matcapFactor"], Vec3::ONE).to_array()
            },
            outline_color: color("_OutlineColor", "outlineColorFactor", Vec3::ZERO),
            outline_width: scalar("_OutlineWidth", "outlineWidthFactor", 0.)
                * if legacy { 0.01 } else { 1. },
            outline_mode: if legacy {
                number(&f["_OutlineWidthMode"], 0.) as u32
            } else {
                match toon["outlineWidthMode"].as_str() {
                    Some("worldCoordinates") => 1,
                    Some("screenCoordinates") => 2,
                    _ => 0,
                }
            },
            outline_lighting_mix: if legacy && number(&f["_OutlineColorMode"], 0.) == 0. {
                0.
            } else {
                scalar("_OutlineLightingMix", "outlineLightingMixFactor", 1.)
            },
            shade_shift: scalar("_ShadeShift", "shadingShiftFactor", 0.),
            shade_toony: scalar("_ShadeToony", "shadingToonyFactor", 0.9),
            alpha_mode: if legacy && f["_BlendMode"].is_number() {
                match number(&f["_BlendMode"], 0.) as u32 {
                    1 => 1,
                    2 | 3 => 2,
                    _ => 0,
                }
            } else {
                match m.alpha_mode() {
                    gltf::material::AlphaMode::Opaque => 0,
                    gltf::material::AlphaMode::Mask => 1,
                    gltf::material::AlphaMode::Blend => 2,
                }
            },
            cutoff: if legacy {
                number(&f["_Cutoff"], 0.5)
            } else {
                m.alpha_cutoff().unwrap_or(0.5)
            },
            cull: if legacy {
                number(&f["_CullMode"], 2.) as u32
            } else if m.double_sided() {
                0
            } else {
                2
            },
            depth_write: if legacy {
                number(&f["_ZWrite"], 1.) > 0.
            } else {
                m.alpha_mode() != gltf::material::AlphaMode::Blend
                    || toon["transparentWithZWrite"].as_bool().unwrap_or(false)
            },
            queue: if legacy {
                old["renderQueue"].as_i64().unwrap_or(2000) as i32
            } else {
                2000
            },
            unlit: if legacy {
                old["shader"].as_str() != Some("VRM/MToon")
            } else {
                !toon.is_object()
            },
            legacy,
            gi: scalar("_IndirectLightIntensity", "giEqualizationFactor", 0.9),
            grade_rate: number(&f["_ShadingGradeRate"], 1.),
            shift_scale: number(&toon["shadingShiftTexture"]["scale"], 1.),
            uv_animation: [
                scalar("_UvAnimScrollX", "uvAnimationScrollXSpeedFactor", 0.),
                scalar("_UvAnimScrollY", "uvAnimationScrollYSpeedFactor", 0.),
                scalar("_UvAnimRotation", "uvAnimationRotationSpeedFactor", 0.)
                    * if legacy { std::f32::consts::TAU } else { 1. },
            ],
            ..Self::default()
        };
        result.transparent = result.alpha_mode == 2;
        if !legacy {
            result.queue = if result.transparent {
                if result.depth_write {
                    2500
                } else {
                    3000
                }
            } else if result.alpha_mode == 1 {
                2450
            } else {
                2000
            };
            result.queue += number(&toon["renderQueueOffsetNumber"], 0.) as i32;
        }
        if legacy && v["_MainTex"].is_array() {
            result.uv_offset = [number(&v["_MainTex"][0], 0.), number(&v["_MainTex"][1], 0.)];
            result.uv_scale = [number(&v["_MainTex"][2], 1.), number(&v["_MainTex"][3], 1.)];
        }
        if let Some(t) = pbr.base_color_texture().and_then(|t| t.texture_transform()) {
            result.uv_offset = t.offset();
            result.uv_scale = t.scale();
            result.uv_rotation = t.rotation();
        }
        if result.maps.iter().flatten().any(|&i| i >= texture_count) {
            return Err(invalid("MToon texture index outside texture array"));
        }
        Ok(result)
    }
    /// Layout matches the WGSL Material uniform (twelve vec4s).
    pub fn uniform(&self) -> [[f32; 4]; 12] {
        [
            self.color,
            [self.shade[0], self.shade[1], self.shade[2], self.cutoff],
            [
                self.emission[0],
                self.emission[1],
                self.emission[2],
                self.normal_scale,
            ],
            [self.rim[0], self.rim[1], self.rim[2], self.rim_power],
            [
                self.outline_color[0],
                self.outline_color[1],
                self.outline_color[2],
                self.outline_width,
            ],
            [
                self.shade_shift,
                self.shade_toony,
                if self.unlit { 1. } else { 0. },
                self.alpha_mode as f32,
            ],
            [
                self.rim_lift,
                self.rim_lighting_mix,
                self.outline_lighting_mix,
                self.outline_mode as f32,
            ],
            [self.matcap[0], self.matcap[1], self.matcap[2], self.gi],
            [
                self.uv_offset[0],
                self.uv_offset[1],
                self.uv_scale[0],
                self.uv_scale[1],
            ],
            [
                self.uv_animation[0],
                self.uv_animation[1],
                self.uv_animation[2],
                self.uv_rotation,
            ],
            [
                if self.legacy { 1. } else { 0. },
                self.grade_rate,
                self.shift_scale,
                0.,
            ],
            [0.; 4],
        ]
    }
}
