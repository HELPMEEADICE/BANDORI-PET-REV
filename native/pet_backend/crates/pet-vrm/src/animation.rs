//! VRMA humanoid tracks in normalized world-rest coordinates.
use super::{document, idx, invalid, nodes, Node, Result};
use glam::{Mat4, Quat, Vec3};
use std::collections::BTreeMap;

enum Values {
    Rotation(Vec<Quat>),
    Translation(Vec<Vec3>),
}
struct Track {
    bone: String,
    times: Vec<f32>,
    values: Values,
    step: bool,
    cubic: bool,
    parent_rest: Quat,
    parent_rest_matrix: Mat4,
    rest_world: Quat,
    rest_translation: Vec3,
}
pub(crate) struct Clip {
    tracks: Vec<Track>,
    pub duration: f32,
    hips_height: f32,
}
pub(crate) const BUILTIN_MOTIONS: &[(&str, &[u8])] = &[
    ("Idle", include_bytes!("../assets/idle-natural.vrma")),
    ("Wave", include_bytes!("../assets/wave.vrma")),
    ("LookAround", include_bytes!("../assets/look-around.vrma")),
    ("Thinking", include_bytes!("../assets/thinking.vrma")),
    ("Relax", include_bytes!("../assets/relax.vrma")),
    ("Blush", include_bytes!("../assets/blush.vrma")),
];
impl Clip {
    pub fn load(bytes: &[u8]) -> Result<Self> {
        let (gltf, json) = document(bytes)?;
        let ext = &json["extensions"]["VRMC_vrm_animation"];
        let map = ext["humanoid"]["humanBones"]
            .as_object()
            .ok_or_else(|| invalid("VRMA missing humanoid mapping"))?;
        let by_node: BTreeMap<_, _> = map
            .iter()
            .filter_map(|(name, v)| Some((idx(&v["node"])?, name.clone())))
            .collect();
        let (nodes, _) = nodes(&gltf)?;
        let blob = gltf
            .blob
            .as_deref()
            .ok_or_else(|| invalid("VRMA missing binary"))?;
        let mut tracks = Vec::new();
        let mut duration = 0f32;
        let animation = gltf
            .animations()
            .next()
            .ok_or_else(|| invalid("VRMA has no animation"))?;
        for channel in animation.channels() {
            let node = channel.target().node().index();
            let Some(bone) = by_node.get(&node) else {
                continue;
            };
            let reader = channel.reader(|_| Some(blob));
            let times: Vec<_> = reader
                .read_inputs()
                .ok_or_else(|| invalid("missing VRMA times"))?
                .collect();
            if times.is_empty()
                || times.iter().any(|t| !t.is_finite())
                || times.windows(2).any(|w| w[0] >= w[1])
            {
                return Err(invalid("invalid VRMA times"));
            }
            duration = duration.max(*times.last().unwrap());
            let values = match reader
                .read_outputs()
                .ok_or_else(|| invalid("missing VRMA values"))?
            {
                gltf::animation::util::ReadOutputs::Rotations(r) => {
                    Values::Rotation(r.into_f32().map(Quat::from_array).collect())
                }
                gltf::animation::util::ReadOutputs::Translations(t) if bone == "hips" => {
                    Values::Translation(t.map(Vec3::from).collect())
                }
                _ => continue,
            };
            let cubic =
                channel.sampler().interpolation() == gltf::animation::Interpolation::CubicSpline;
            let count = match &values {
                Values::Rotation(v) => v.len(),
                Values::Translation(v) => v.len(),
            };
            if count != times.len() * if cubic { 3 } else { 1 } {
                return Err(invalid("invalid VRMA keyframe count"));
            }
            let parent_rest = nodes[node]
                .parent
                .map(|p| nodes[p].rest_world.to_scale_rotation_translation().1)
                .unwrap_or(Quat::IDENTITY);
            let rest_world = nodes[node].rest_world.to_scale_rotation_translation().1;
            let parent_rest_matrix = nodes[node]
                .parent
                .map(|p| nodes[p].rest_world)
                .unwrap_or(Mat4::IDENTITY);
            let mut rest_translation = nodes[node].rest.t;
            if let Values::Translation(values) = &values {
                let first = values[usize::from(cubic)];
                // Keep recorded weight shifts, removing the capture scene origin.
                rest_translation.x = first.x;
                rest_translation.z = first.z;
            }
            tracks.push(Track {
                bone: bone.clone(),
                times,
                values,
                step: channel.sampler().interpolation() == gltf::animation::Interpolation::Step,
                cubic,
                parent_rest,
                parent_rest_matrix,
                rest_world,
                rest_translation,
            });
        }
        if tracks.is_empty() {
            return Err(invalid("VRMA has no supported humanoid tracks"));
        }
        let hips_height = map
            .get("hips")
            .and_then(|v| idx(&v["node"]))
            .and_then(|i| nodes.get(i))
            .map(|n| n.rest_world.w_axis.y.abs())
            .unwrap_or(1.)
            .max(0.001);
        Ok(Self {
            tracks,
            duration: duration.max(0.001),
            hips_height,
        })
    }
    pub fn apply(
        &self,
        time: f32,
        nodes: &mut [Node],
        humanoid: &BTreeMap<String, usize>,
        legacy: bool,
    ) {
        for track in &self.tracks {
            let Some(&target) = humanoid.get(&track.bone) else {
                continue;
            };
            let upper = track
                .times
                .partition_point(|&t| t <= time)
                .min(track.times.len() - 1);
            let lower = upper.saturating_sub(usize::from(track.times[upper] > time));
            let span = track.times[upper] - track.times[lower];
            let t = if track.step || span < 1e-7 {
                0.
            } else {
                ((time - track.times[lower]) / span).clamp(0., 1.)
            };
            let at = |key: usize| if track.cubic { key * 3 + 1 } else { key };
            match &track.values {
                Values::Rotation(values) => {
                    let q = if track.cubic && lower != upper {
                        let a = glam::Vec4::from_array(values[at(lower)].to_array());
                        let b = glam::Vec4::from_array(values[at(upper)].to_array());
                        let out = glam::Vec4::from_array(values[lower * 3 + 2].to_array()) * span;
                        let input = glam::Vec4::from_array(values[upper * 3].to_array()) * span;
                        Quat::from_array(hermite(a, b, out, input, t).normalize().to_array())
                    } else {
                        values[at(lower)]
                            .normalize()
                            .slerp(values[at(upper)].normalize(), t)
                    };
                    let mut delta = track.parent_rest * q * track.rest_world.inverse();
                    if legacy {
                        delta = Quat::from_xyzw(-delta.x, delta.y, -delta.z, delta.w);
                    }
                    let parent = nodes[target]
                        .parent
                        .map(|p| nodes[p].rest_world.to_scale_rotation_translation().1)
                        .unwrap_or(Quat::IDENTITY);
                    nodes[target].pose.r = (parent.inverse()
                        * delta
                        * nodes[target].rest_world.to_scale_rotation_translation().1)
                        .normalize();
                }
                Values::Translation(values) => {
                    let v = if track.cubic && lower != upper {
                        hermite(
                            values[at(lower)],
                            values[at(upper)],
                            values[lower * 3 + 2] * span,
                            values[upper * 3] * span,
                            t,
                        )
                    } else {
                        values[at(lower)].lerp(values[at(upper)], t)
                    };
                    let mut offset = v - track.rest_translation;
                    // Hips translation is in the source parent's coordinate frame.
                    offset = track.parent_rest_matrix.transform_vector3(offset);
                    if legacy {
                        offset.x = -offset.x;
                        offset.z = -offset.z;
                    }
                    let height = nodes[target].rest_world.w_axis.y.abs();
                    let parent = nodes[target]
                        .parent
                        .map(|p| nodes[p].rest_world)
                        .unwrap_or(glam::Mat4::IDENTITY);
                    nodes[target].pose.t += parent
                        .inverse()
                        .transform_vector3(offset * (height / self.hips_height));
                }
            }
        }
    }

    /// Overlap the tail with the start; wrap without a discontinuous pose reset.
    pub fn apply_looped(
        &self,
        time: f32,
        nodes: &mut [Node],
        humanoid: &BTreeMap<String, usize>,
        legacy: bool,
    ) {
        let overlap = (self.duration * 0.15).min(0.65);
        let period = (self.duration - overlap).max(0.001);
        let time = time.rem_euclid(period);
        if time >= overlap {
            self.apply(time, nodes, humanoid, legacy);
            return;
        }
        let base: Vec<_> = nodes.iter().map(|n| n.pose).collect();
        self.apply(period + time, nodes, humanoid, legacy);
        let end: Vec<_> = nodes.iter().map(|n| n.pose).collect();
        for (node, pose) in nodes.iter_mut().zip(base) {
            node.pose = pose;
        }
        self.apply(time, nodes, humanoid, legacy);
        let weight = super::smoothstep(time / overlap.max(0.001));
        for (node, end) in nodes.iter_mut().zip(end) {
            node.pose = super::blend_pose(end, node.pose, weight);
        }
    }
}
fn hermite<T>(a: T, b: T, out: T, input: T, t: f32) -> T
where
    T: std::ops::Mul<f32, Output = T> + std::ops::Add<Output = T>,
{
    a * (2. * t * t * t - 3. * t * t + 1.)
        + out * (t * t * t - 2. * t * t + t)
        + b * (-2. * t * t * t + 3. * t * t)
        + input * (t * t * t - t * t)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn natural_motions_have_full_body_tracks_and_dense_keys() {
        for (name, bytes) in BUILTIN_MOTIONS {
            let clip = Clip::load(bytes).unwrap();
            assert!(clip.duration > 3., "{name} is too short");
            assert!(clip.tracks.len() > 15, "{name} has too few body tracks");
            assert!(clip.tracks.iter().any(|t| t.bone == "rightUpperArm"));
            assert!(clip.tracks.iter().all(|t| t.times.len() > 50));
        }
    }
}
