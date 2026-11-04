//! Self-contained VRM 0.x/1.0 avatars. GPU-independent animation and physics.
mod animation;
mod material;
mod performance;
mod physics;
#[cfg(test)]
mod tests;
pub use material::Material;

use animation::Clip;
use glam::{Mat4, Quat, Vec3};
use neocari::{
    assets::DecodedTexture,
    moc3::{Moc3DrawableMesh, Moc3DrawableVertex},
};
use performance::{Face, MotionProfile, Transition};
use physics::Spring;
use serde_json::Value;
use std::{collections::BTreeMap, path::Path};

#[derive(Debug, thiserror::Error)]
pub enum VrmError {
    #[error("VRM I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("VRM glTF: {0}")]
    Gltf(#[from] gltf::Error),
    #[error("VRM JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("VRM texture: {0}")]
    Image(#[from] image::ImageError),
    #[error("invalid or unsupported VRM: {0}")]
    Invalid(String),
}
type Result<T> = std::result::Result<T, VrmError>;

#[derive(Clone, Copy)]
pub(crate) struct Transform {
    pub t: Vec3,
    pub r: Quat,
    pub s: Vec3,
}
impl Transform {
    fn matrix(self) -> Mat4 {
        Mat4::from_scale_rotation_translation(self.s, self.r, self.t)
    }
}
pub(crate) struct Node {
    pub parent: Option<usize>,
    pub children: Vec<usize>,
    pub rest: Transform,
    pub pose: Transform,
    pub world: Mat4,
    pub rest_world: Mat4,
}

/// World vertices after morphing and skinning, shared by rendering and hit tests.
#[repr(C)]
#[derive(Clone, Copy, Debug, bytemuck::Pod, bytemuck::Zeroable)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
}
struct BindVertex {
    position: Vec3,
    normal: Vec3,
    uv: [f32; 2],
    joints: [u16; 4],
    weights: [f32; 4],
}
struct Skin {
    joints: Vec<usize>,
    inverse: Vec<Mat4>,
}
/// One indexed triangle draw. `vertices` are in orthographic view space.
pub struct Primitive {
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u32>,
    pub material: usize,
    node: usize,
    skin: Option<usize>,
    bind: Vec<BindVertex>,
    morphs: Vec<(Vec<Vec3>, Vec<Vec3>)>,
    weights: Vec<f32>,
    mesh: usize,
}
struct Expression {
    name: String,
    binds: Vec<(usize, usize, f32)>,
}

pub struct VrmModel {
    pub primitives: Vec<Primitive>,
    pub materials: Vec<Material>,
    pub textures: Vec<DecodedTexture>,
    pub projected: Vec<Moc3DrawableMesh>,
    pub legacy: bool,
    pub(crate) nodes: Vec<Node>,
    pub(crate) order: Vec<usize>,
    pub(crate) humanoid: BTreeMap<String, usize>,
    skins: Vec<Skin>,
    pub(crate) springs: Vec<Spring>,
    pub(crate) colliders: Vec<physics::Collider>,
    pub motion_names: Vec<String>,
    pub expression_names: Vec<String>,
    clips: BTreeMap<String, Clip>,
    motion_profiles: BTreeMap<String, MotionProfile>,
    transition: Option<Transition>,
    last_pose: Vec<Transform>,
    finished_action: bool,
    active: Option<String>,
    time: f32,
    elapsed: f32,
    accumulator: f32,
    view: Mat4,
    expressions: Vec<Expression>,
    face: Face,
    blink: bool,
    breath: bool,
    drag: [f32; 2],
    mouth: f32,
    desktop_position: Option<(i32, i32)>,
}

fn smoothstep(t: f32) -> f32 {
    let t = t.clamp(0., 1.);
    t * t * (3. - 2. * t)
}
fn blend_pose(a: Transform, b: Transform, weight: f32) -> Transform {
    Transform {
        t: a.t.lerp(b.t, weight),
        r: a.r.slerp(b.r, weight).normalize(),
        s: a.s.lerp(b.s, weight),
    }
}

fn invalid(msg: &str) -> VrmError {
    VrmError::Invalid(msg.into())
}
fn idx(v: &Value) -> Option<usize> {
    v.as_u64().and_then(|n| usize::try_from(n).ok())
}
fn number(v: &Value, default: f32) -> f32 {
    v.as_f64()
        .map(|v| v as f32)
        .filter(|v| v.is_finite())
        .unwrap_or(default)
}
fn vec3(v: &Value, default: Vec3) -> Vec3 {
    if v.is_array() {
        Vec3::new(
            number(&v[0], default.x),
            number(&v[1], default.y),
            number(&v[2], default.z),
        )
    } else if v.is_object() {
        Vec3::new(
            number(&v["x"], default.x),
            number(&v["y"], default.y),
            number(&v["z"], default.z),
        )
    } else {
        default
    }
}
pub(crate) fn document(bytes: &[u8]) -> Result<(gltf::Gltf, Value)> {
    let gltf = gltf::Gltf::from_slice(bytes)?;
    let glb = gltf::binary::Glb::from_slice(bytes)?;
    let json = serde_json::from_slice(&glb.json)?;
    if gltf
        .buffers()
        .any(|b| !matches!(b.source(), gltf::buffer::Source::Bin))
    {
        return Err(invalid("VRM/VRMA must embed all buffers"));
    }
    Ok((gltf, json))
}
pub(crate) fn nodes(gltf: &gltf::Gltf) -> Result<(Vec<Node>, Vec<usize>)> {
    let mut nodes: Vec<_> = gltf
        .nodes()
        .map(|n| {
            let (t, r, s) = n.transform().decomposed();
            let rest = Transform {
                t: Vec3::from(t),
                r: Quat::from_array(r).normalize(),
                s: Vec3::from(s),
            };
            Node {
                parent: None,
                children: n.children().map(|n| n.index()).collect(),
                rest,
                pose: rest,
                world: Mat4::IDENTITY,
                rest_world: Mat4::IDENTITY,
            }
        })
        .collect();
    for i in 0..nodes.len() {
        for child in nodes[i].children.clone() {
            if nodes[child].parent.replace(i).is_some() {
                return Err(invalid("node has multiple parents"));
            }
        }
    }
    let mut order = Vec::new();
    let mut pending: Vec<_> = (0..nodes.len())
        .filter(|&i| nodes[i].parent.is_none())
        .collect();
    while let Some(i) = pending.pop() {
        order.push(i);
        pending.extend_from_slice(&nodes[i].children);
    }
    if order.len() != nodes.len() {
        return Err(invalid("cyclic node hierarchy"));
    }
    update_world(&mut nodes, &order);
    for node in &mut nodes {
        node.rest_world = node.world;
    }
    Ok((nodes, order))
}
pub(crate) fn update_world(nodes: &mut [Node], order: &[usize]) {
    for &i in order {
        nodes[i].world = nodes[i]
            .parent
            .map(|p| nodes[p].world)
            .unwrap_or(Mat4::IDENTITY)
            * nodes[i].pose.matrix();
    }
}

impl VrmModel {
    pub fn load(path: &Path) -> Result<Self> {
        let (gltf, json) = document(&std::fs::read(path)?)?;
        let legacy = json["extensions"]["VRM"].is_object();
        let vrm = &json["extensions"][if legacy { "VRM" } else { "VRMC_vrm" }];
        if !vrm.is_object() {
            return Err(invalid("missing VRM / VRMC_vrm extension"));
        }
        let blob = gltf
            .blob
            .as_deref()
            .ok_or_else(|| invalid("missing GLB binary"))?;
        let (nodes, order) = nodes(&gltf)?;
        let mut humanoid = BTreeMap::new();
        if legacy {
            for bone in vrm["humanoid"]["humanBones"]
                .as_array()
                .into_iter()
                .flatten()
            {
                if let (Some(name), Some(i)) = (bone["bone"].as_str(), idx(&bone["node"])) {
                    // VRM0 names the three thumb bones differently from VRMA/VRM1.
                    let name = match name {
                        "leftThumbProximal" => "leftThumbMetacarpal",
                        "leftThumbIntermediate" => "leftThumbProximal",
                        "rightThumbProximal" => "rightThumbMetacarpal",
                        "rightThumbIntermediate" => "rightThumbProximal",
                        _ => name,
                    };
                    humanoid.insert(name.into(), i);
                }
            }
        } else if let Some(bones) = vrm["humanoid"]["humanBones"].as_object() {
            for (name, bone) in bones {
                if let Some(i) = idx(&bone["node"]) {
                    humanoid.insert(name.clone(), i);
                }
            }
        }
        if !humanoid.contains_key("hips") || humanoid.values().any(|&i| i >= nodes.len()) {
            return Err(invalid("invalid humanoid bones"));
        }
        let images: Vec<_> = gltf
            .images()
            .map(|im| {
                let gltf::image::Source::View { view, .. } = im.source() else {
                    return Err(invalid("VRM images must be embedded"));
                };
                let data = blob
                    .get(view.offset()..view.offset() + view.length())
                    .ok_or_else(|| invalid("image outside buffer"))?;
                let rgba = image::load_from_memory(data)?.into_rgba8();
                Ok(DecodedTexture::new(
                    rgba.width(),
                    rgba.height(),
                    rgba.into_raw(),
                ))
            })
            .collect::<Result<_>>()?;
        let mut textures = Vec::new();
        for texture in gltf.textures() {
            textures.push(images[texture.source().index()].clone());
        }
        let mut materials = gltf
            .materials()
            .map(|m| Material::load(m, &json, vrm, legacy, textures.len()))
            .collect::<Result<Vec<_>>>()?;
        let default_material = materials.len();
        materials.push(Material::default());
        let white_texture = textures.len();
        textures.push(DecodedTexture::new(1, 1, vec![255; 4]));
        for material in &mut materials {
            material.hit_texture = if material.alpha_mode == 0 {
                white_texture
            } else {
                material.texture.unwrap_or(white_texture)
            };
        }
        let skins = gltf
            .skins()
            .map(|s| {
                let joints: Vec<_> = s.joints().map(|n| n.index()).collect();
                let inverse = s
                    .reader(|_| Some(blob))
                    .read_inverse_bind_matrices()
                    .map(|it| it.map(|m| Mat4::from_cols_array_2d(&m)).collect())
                    .unwrap_or_else(|| vec![Mat4::IDENTITY; joints.len()]);
                Skin { joints, inverse }
            })
            .collect::<Vec<_>>();
        let mut primitives = Vec::new();
        for node in gltf.nodes() {
            if let Some(mesh) = node.mesh() {
                for p in mesh.primitives() {
                    if p.mode() != gltf::mesh::Mode::Triangles {
                        return Err(invalid("only triangle primitives are supported"));
                    }
                    let reader = p.reader(|_| Some(blob));
                    let positions: Vec<_> = reader
                        .read_positions()
                        .ok_or_else(|| invalid("missing positions"))?
                        .map(Vec3::from)
                        .collect();
                    let normals: Vec<_> = reader
                        .read_normals()
                        .map(|it| it.map(Vec3::from).collect())
                        .unwrap_or_else(|| vec![Vec3::Y; positions.len()]);
                    let uvs: Vec<_> = reader
                        .read_tex_coords(0)
                        .map(|it| it.into_f32().collect())
                        .unwrap_or_else(|| vec![[0.; 2]; positions.len()]);
                    let joints: Vec<_> = reader
                        .read_joints(0)
                        .map(|it| it.into_u16().collect())
                        .unwrap_or_else(|| vec![[0; 4]; positions.len()]);
                    let weights: Vec<_> = reader
                        .read_weights(0)
                        .map(|it| it.into_f32().collect())
                        .unwrap_or_else(|| vec![[1., 0., 0., 0.]; positions.len()]);
                    if [normals.len(), uvs.len(), joints.len(), weights.len()]
                        .iter()
                        .any(|&n| n != positions.len())
                    {
                        return Err(invalid("mismatched vertex attributes"));
                    }
                    let indices: Vec<_> = reader
                        .read_indices()
                        .map(|it| it.into_u32().collect())
                        .unwrap_or_else(|| (0..positions.len() as u32).collect());
                    if indices.iter().any(|&i| i as usize >= positions.len()) {
                        return Err(invalid("index outside vertex buffer"));
                    }
                    let skin = node.skin().map(|s| s.index());
                    if let Some(s) = skin {
                        if joints.iter().zip(&weights).any(|(js, ws)| {
                            js.iter()
                                .zip(ws)
                                .any(|(&j, &w)| w > 0. && j as usize >= skins[s].joints.len())
                        }) {
                            return Err(invalid("invalid skin joint"));
                        }
                    }
                    let bind = (0..positions.len())
                        .map(|i| BindVertex {
                            position: positions[i],
                            normal: normals[i],
                            uv: uvs[i],
                            joints: joints[i],
                            weights: weights[i],
                        })
                        .collect();
                    let morphs: Vec<_> = reader
                        .read_morph_targets()
                        .map(|(p, n, _)| {
                            (
                                p.map(|it| it.map(Vec3::from).collect()).unwrap_or_default(),
                                n.map(|it| it.map(Vec3::from).collect()).unwrap_or_default(),
                            )
                        })
                        .collect();
                    let morph_weights = node
                        .weights()
                        .or_else(|| mesh.weights())
                        .map(|w| w.to_vec())
                        .unwrap_or_else(|| vec![0.; morphs.len()]);
                    primitives.push(Primitive {
                        vertices: Vec::new(),
                        indices,
                        material: p.material().index().unwrap_or(default_material),
                        node: node.index(),
                        skin,
                        bind,
                        morphs,
                        weights: morph_weights,
                        mesh: mesh.index(),
                    });
                }
            }
        }
        if primitives.is_empty() {
            return Err(invalid("no renderable meshes"));
        }
        let mut expressions = Vec::new();
        if legacy {
            for e in vrm["blendShapeMaster"]["blendShapeGroups"]
                .as_array()
                .into_iter()
                .flatten()
            {
                let name = e["presetName"]
                    .as_str()
                    .filter(|s| *s != "unknown")
                    .or(e["name"].as_str())
                    .unwrap_or("expression")
                    .to_owned();
                let binds = e["binds"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|b| {
                        Some((
                            idx(&b["mesh"])?,
                            idx(&b["index"])?,
                            number(&b["weight"], 0.) / 100.,
                        ))
                    })
                    .collect();
                expressions.push(Expression { name, binds });
            }
        } else {
            for kind in ["preset", "custom"] {
                if let Some(map) = vrm["expressions"][kind].as_object() {
                    for (name, e) in map {
                        let binds = e["morphTargetBinds"]
                            .as_array()
                            .into_iter()
                            .flatten()
                            .filter_map(|b| {
                                let n = idx(&b["node"])?;
                                let m = gltf.nodes().nth(n)?.mesh()?.index();
                                Some((m, idx(&b["index"])?, number(&b["weight"], 0.)))
                            })
                            .collect();
                        expressions.push(Expression {
                            name: name.clone(),
                            binds,
                        });
                    }
                }
            }
        }
        let sidecar = path.with_extension("pet.json");
        let settings: Value = if sidecar.is_file() {
            serde_json::from_slice(&std::fs::read(&sidecar)?)?
        } else {
            Value::Null
        };
        let yaw = number(&settings["camera"]["yaw"], 0.).to_radians()
            + if legacy { 0. } else { std::f32::consts::PI };
        let elevation = number(&settings["camera"]["elevation"], 0.)
            .clamp(-80., 80.)
            .to_radians();
        let mut clips = BTreeMap::new();
        for (name, bytes) in animation::BUILTIN_MOTIONS {
            clips.insert((*name).into(), Clip::load(bytes)?);
        }
        if let Some(motions) = settings["motions"].as_object() {
            for (name, file) in motions {
                if let Some(file) = file.as_str() {
                    let clip = Clip::load(&std::fs::read(
                        path.parent().unwrap_or(Path::new(".")).join(file),
                    )?)?;
                    clips.insert(name.clone(), clip);
                }
            }
        }
        let expression_names = expressions.iter().map(|e| e.name.clone()).collect();
        let mut motion_names = vec!["Idle".into()];
        motion_names.extend(clips.keys().filter(|name| name.as_str() != "Idle").cloned());
        let motion_profiles = clips
            .keys()
            .map(|name| {
                (
                    name.clone(),
                    MotionProfile::new(name, &settings["motion_settings"][name]),
                )
            })
            .collect();
        let mut model = Self {
            primitives,
            materials,
            textures,
            projected: Vec::new(),
            legacy,
            nodes,
            order,
            humanoid,
            skins,
            springs: Vec::new(),
            colliders: Vec::new(),
            motion_names,
            expression_names,
            clips,
            motion_profiles,
            transition: None,
            last_pose: Vec::new(),
            finished_action: false,
            active: Some("Idle".into()),
            time: 0.,
            elapsed: 0.,
            accumulator: 0.,
            view: Mat4::from_scale(Vec3::new(-1., 1., 1.))
                * Mat4::from_quat(Quat::from_rotation_x(-elevation) * Quat::from_rotation_y(yaw)),
            expressions,
            face: Face::new(&settings),
            blink: true,
            breath: true,
            drag: [0.; 2],
            mouth: 0.,
            desktop_position: None,
        };
        model.springs = physics::load(
            &json,
            &model.nodes,
            &model.order,
            &mut model.colliders,
            legacy,
        )?;
        model.evaluate_pose();
        model.skin();
        if let Some(name) = settings["default_motion"].as_str() {
            if !model.play_motion(name) {
                return Err(invalid("unknown default_motion"));
            }
        }
        tracing::info!(
            primitives = model.primitives.len(),
            vertices = model
                .primitives
                .iter()
                .map(|p| p.vertices.len())
                .sum::<usize>(),
            springs = model.springs.len(),
            colliders = model.colliders.len(),
            "VRM loaded (front-facing orthographic camera)"
        );
        Ok(model)
    }

    pub fn play_motion(&mut self, name: &str) -> bool {
        // Keep existing saved click/default mappings usable after replacing the demo.
        let name = if name == "SampleArm" { "Wave" } else { name };
        if !self.motion_names.iter().any(|s| s == name) {
            return false;
        }
        if self.active.as_deref() == Some(name)
            && self.motion_profiles.get(name).is_some_and(|p| p.looping)
        {
            return true;
        }
        let duration = self
            .motion_profiles
            .get(name)
            .map(|p| p.fade)
            .unwrap_or(0.55);
        self.transition = (!self.last_pose.is_empty()).then(|| Transition {
            from: self.last_pose.clone(),
            started: self.elapsed,
            duration,
        });
        self.active = Some(name.into());
        self.time = 0.;
        self.finished_action = false;
        true
    }
    pub fn active_motion(&self) -> Option<&str> {
        self.active.as_deref()
    }
    pub fn stop_motions(&mut self) {
        self.transition = Some(Transition {
            from: self.last_pose.clone(),
            started: self.elapsed,
            duration: 0.55,
        });
        self.active = None;
    }
    pub fn is_motion_finished(&self) -> bool {
        self.finished_action
            || self.active.is_none()
            || self
                .active
                .as_ref()
                .and_then(|n| self.clips.get(n))
                .is_some_and(|c| {
                    self.time >= c.duration
                        && !self
                            .active
                            .as_ref()
                            .and_then(|n| self.motion_profiles.get(n))
                            .is_some_and(|p| p.looping)
                })
    }
    pub fn play_expression(&mut self, name: &str) -> bool {
        let canonical = performance::canonical_expression(name);
        let Some(actual) = self
            .expression_names
            .iter()
            .find(|s| s.as_str() == name)
            .or_else(|| {
                self.expression_names
                    .iter()
                    .find(|s| performance::canonical_expression(s) == canonical)
            })
        else {
            return false;
        };
        self.face.explicit = Some(actual.clone());
        true
    }
    pub fn clear_expression(&mut self) {
        self.face.explicit = None;
    }
    pub fn active_expression_count(&self) -> usize {
        self.face.explicit_count()
    }
    pub fn set_drag(&mut self, x: f32, y: f32) {
        self.drag = [x.clamp(-1., 1.), y.clamp(-1., 1.)];
    }
    pub fn set_auto_blink(&mut self, v: bool) {
        self.blink = v;
    }
    pub fn set_auto_breath(&mut self, v: bool) {
        self.breath = v;
    }
    pub fn set_lip_sync(&mut self, open: f32, _form: f32) {
        self.mouth = open.clamp(0., 1.);
    }
    pub fn set_mouth_open(&mut self, v: f32) {
        self.set_lip_sync(v, 0.);
    }
    pub fn elapsed(&self) -> f32 {
        self.elapsed
    }
    pub fn spring_count(&self) -> usize {
        self.springs.len()
    }
    pub fn physics_displacement(&self) -> f32 {
        self.springs
            .iter()
            .map(|s| s.displacement(&self.nodes))
            .sum()
    }
    /// Screen translation excites the same simulated hair/clothing chains.
    pub fn set_desktop_position(&mut self, x: i32, y: i32, units_per_pixel: f32) {
        if let Some((old_x, old_y)) = self.desktop_position {
            let delta = Vec3::new(
                (x as f32 - old_x as f32) * units_per_pixel,
                -(y as f32 - old_y as f32) * units_per_pixel,
                0.,
            )
            .clamp_length_max(0.2);
            let delta = self.view.inverse().transform_vector3(delta);
            for spring in &mut self.springs {
                spring.translate_inertia(delta, &self.nodes);
            }
        }
        self.desktop_position = Some((x, y));
    }
    pub fn update(&mut self, dt: f32) -> bool {
        if !dt.is_finite() || dt < 0. {
            return false;
        }
        self.accumulator = (self.accumulator + dt.min(0.1)).min(0.1);
        while self.accumulator >= 1. / 120. {
            self.accumulator -= 1. / 120.;
            self.time += 1. / 120.
                * self
                    .active
                    .as_ref()
                    .and_then(|n| self.motion_profiles.get(n))
                    .map(|p| p.speed)
                    .unwrap_or(1.);
            self.elapsed += 1. / 120.;
            let done = self
                .active
                .as_ref()
                .and_then(|name| self.clips.get(name).zip(self.motion_profiles.get(name)))
                .is_some_and(|(clip, profile)| !profile.looping && self.time >= clip.duration);
            if done {
                self.play_motion("Idle");
                self.finished_action = true;
            }
            let ambient = self
                .active
                .as_ref()
                .and_then(|name| self.motion_profiles.get(name))
                .map(|p| (p.expression, p.strength))
                .unwrap_or(("relaxed", 0.08));
            self.face.update(
                1. / 120.,
                &self.expression_names,
                ambient,
                self.blink,
                self.mouth,
                self.drag,
            );
            self.evaluate_pose();
            physics::step(self, 1. / 120.);
        }
        self.skin();
        true
    }
    fn rotate_bone(&mut self, name: &str, q: Quat) {
        if let Some(&i) = self.humanoid.get(name) {
            self.nodes[i].pose.r = self.nodes[i].rest.r * q;
        }
    }
    fn evaluate_pose(&mut self) {
        for n in &mut self.nodes {
            n.pose = n.rest;
        }
        // A relaxed standing pose for clips that only animate a subset of bones.
        let sign = if self.legacy { -1. } else { 1. };
        self.rotate_bone("leftUpperArm", Quat::from_rotation_z(-sign * 1.15));
        self.rotate_bone("rightUpperArm", Quat::from_rotation_z(sign * 1.15));
        if self.breath
            && self
                .active
                .as_ref()
                .and_then(|name| self.clips.get(name))
                .is_none()
        {
            self.rotate_bone(
                "spine",
                Quat::from_rotation_z((self.elapsed * 1.7).sin() * 0.018),
            );
            self.rotate_bone(
                "chest",
                Quat::from_rotation_x((self.elapsed * 2.).sin() * 0.012),
            );
        }
        if let Some(clip) = self.active.as_ref().and_then(|n| self.clips.get(n)) {
            if self
                .active
                .as_ref()
                .and_then(|n| self.motion_profiles.get(n))
                .is_some_and(|p| p.looping)
            {
                clip.apply_looped(self.time, &mut self.nodes, &self.humanoid, self.legacy);
            } else {
                clip.apply(
                    self.time.min(clip.duration),
                    &mut self.nodes,
                    &self.humanoid,
                    self.legacy,
                );
            }
        }
        if let Some(&head) = self.humanoid.get("head") {
            let drag = self.face.drag();
            self.nodes[head].pose.r = (self.nodes[head].pose.r
                * Quat::from_euler(glam::EulerRot::YXZ, drag[0] * 0.20, -drag[1] * 0.12, 0.))
            .normalize();
        }
        if let Some(transition) = &self.transition {
            let t = (self.elapsed - transition.started) / transition.duration;
            for (node, &from) in self.nodes.iter_mut().zip(&transition.from) {
                node.pose = blend_pose(from, node.pose, smoothstep(t));
            }
            if t >= 1. {
                self.transition = None;
            }
        }
        self.last_pose = self.nodes.iter().map(|n| n.pose).collect();
        update_world(&mut self.nodes, &self.order);
    }
    fn skin(&mut self) {
        let mut morph_weights: BTreeMap<(usize, usize), f32> = BTreeMap::new();
        for e in &self.expressions {
            let weight = self.face.weight(&e.name);
            if weight > 0. {
                for &(mesh, target, w) in &e.binds {
                    *morph_weights.entry((mesh, target)).or_default() += w * weight;
                }
            }
        }
        let palettes: Vec<Vec<Mat4>> = self
            .skins
            .iter()
            .map(|s| {
                s.joints
                    .iter()
                    .zip(&s.inverse)
                    .map(|(&j, inv)| self.nodes[j].world * *inv)
                    .collect()
            })
            .collect();
        let mut hit_mesh = 0;
        for p in &mut self.primitives {
            p.vertices.clear();
            for (i, b) in p.bind.iter().enumerate() {
                let mut position = b.position;
                let mut normal = b.normal;
                for (m, (positions, normals)) in p.morphs.iter().enumerate() {
                    let w = (p.weights.get(m).copied().unwrap_or(0.)
                        + morph_weights.get(&(p.mesh, m)).copied().unwrap_or(0.))
                    .clamp(0., 1.);
                    if w != 0. {
                        if let Some(dp) = positions.get(i) {
                            position += *dp * w;
                        }
                        if let Some(dn) = normals.get(i) {
                            normal += *dn * w;
                        }
                    }
                }
                let transform = if let Some(s) = p.skin {
                    let mut mat = Mat4::ZERO;
                    let mut total = 0.;
                    for (&j, &w) in b.joints.iter().zip(&b.weights) {
                        if w > 0. {
                            mat += palettes[s][j as usize] * w;
                            total += w;
                        }
                    }
                    if total > 1e-6 {
                        mat * (1. / total)
                    } else {
                        self.nodes[p.node].world
                    }
                } else {
                    self.nodes[p.node].world
                };
                let position = self
                    .view
                    .transform_point3(transform.transform_point3(position));
                let normal = self
                    .view
                    .transform_vector3(transform.transform_vector3(normal))
                    .normalize_or_zero();
                p.vertices.push(Vertex {
                    position: position.to_array(),
                    normal: normal.to_array(),
                    uv: b.uv,
                });
            }
            // Chunk triangles for the existing u16 alpha-hit-test facade. Render
            // buffers keep the original u32 indices and full 3D depth.
            for chunk in p.indices.chunks(60_000) {
                let material = &self.materials[p.material];
                let uv_transform = |uv: [f32; 2]| {
                    let angle = material.uv_rotation;
                    let x = uv[0] * material.uv_scale[0];
                    let y = uv[1] * material.uv_scale[1];
                    [
                        x * angle.cos() - y * angle.sin() + material.uv_offset[0],
                        x * angle.sin() + y * angle.cos() + material.uv_offset[1],
                    ]
                };
                let vertices = chunk
                    .iter()
                    .map(|&i| {
                        let v = p.vertices[i as usize];
                        Moc3DrawableVertex::new([v.position[0], v.position[1]], uv_transform(v.uv))
                    })
                    .collect();
                let texture = material.hit_texture as i32;
                let mesh = Moc3DrawableMesh::from_parts(
                    texture,
                    0,
                    1.,
                    0.,
                    vertices,
                    (0..chunk.len() as u16).collect(),
                    Vec::new(),
                );
                if hit_mesh < self.projected.len() {
                    self.projected[hit_mesh] = mesh;
                } else {
                    self.projected.push(mesh);
                }
                hit_mesh += 1;
            }
        }
        self.projected.truncate(hit_mesh);
    }
}
