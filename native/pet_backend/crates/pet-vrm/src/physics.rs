//! Fixed-step Verlet springs with length constraints and sphere/capsule collision.
use super::{idx, invalid, number, update_world, vec3, Node, Result, VrmModel};
use glam::{Mat4, Quat, Vec3};
use serde_json::Value;

pub(crate) struct Collider {
    node: usize,
    offset: Vec3,
    tail: Vec3,
    radius: f32,
}
pub(crate) struct Spring {
    node: usize,
    axis: Vec3,
    current: Vec3,
    previous: Vec3,
    center: Option<usize>,
    stiffness: f32,
    drag: f32,
    gravity: Vec3,
    radius: f32,
    colliders: Vec<usize>,
    initialized: bool,
}
impl Spring {
    pub fn displacement(&self, nodes: &[Node]) -> f32 {
        let center = self
            .center
            .map(|i| nodes[i].world)
            .unwrap_or(Mat4::IDENTITY);
        let parent = nodes[self.node]
            .parent
            .map(|i| nodes[i].world)
            .unwrap_or(Mat4::IDENTITY);
        center
            .transform_point3(self.current)
            .distance((parent * nodes[self.node].rest.matrix()).transform_point3(self.axis))
    }
    pub fn translate_inertia(&mut self, delta: Vec3, nodes: &[Node]) {
        if self.initialized {
            let delta = self
                .center
                .map(|i| nodes[i].world.inverse().transform_vector3(delta))
                .unwrap_or(delta);
            self.current -= delta;
            self.previous -= delta;
        }
    }
}
pub(crate) fn load(
    json: &Value,
    nodes: &[Node],
    order: &[usize],
    colliders: &mut Vec<Collider>,
    legacy: bool,
) -> Result<Vec<Spring>> {
    let ext = &json["extensions"][if legacy { "VRM" } else { "VRMC_springBone" }];
    let ext = if legacy {
        &ext["secondaryAnimation"]
    } else {
        ext
    };
    let mut groups = Vec::<Vec<usize>>::new();
    if legacy {
        for g in ext["colliderGroups"].as_array().into_iter().flatten() {
            let node = idx(&g["node"]).ok_or_else(|| invalid("invalid collider node"))?;
            let mut group = Vec::new();
            for c in g["colliders"].as_array().into_iter().flatten() {
                let offset = vec3(&c["offset"], Vec3::ZERO);
                group.push(colliders.len());
                colliders.push(Collider {
                    node,
                    offset,
                    tail: offset,
                    radius: number(&c["radius"], 0.).max(0.),
                });
            }
            groups.push(group);
        }
    } else {
        for c in ext["colliders"].as_array().into_iter().flatten() {
            let node = idx(&c["node"]).ok_or_else(|| invalid("invalid collider node"))?;
            let capsule = c["shape"]["capsule"].is_object();
            let shape = &c["shape"][if capsule { "capsule" } else { "sphere" }];
            let offset = vec3(&shape["offset"], Vec3::ZERO);
            colliders.push(Collider {
                node,
                offset,
                tail: if capsule {
                    vec3(&shape["tail"], offset)
                } else {
                    offset
                },
                radius: number(&shape["radius"], 0.).max(0.),
            });
        }
        for g in ext["colliderGroups"].as_array().into_iter().flatten() {
            groups.push(
                g["colliders"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(idx)
                    .collect(),
            );
        }
    }
    if colliders.iter().any(|c| c.node >= nodes.len())
        || groups.iter().flatten().any(|&i| i >= colliders.len())
    {
        return Err(invalid("invalid spring collider reference"));
    }
    let mut springs = Vec::new();
    let definitions = &ext[if legacy { "boneGroups" } else { "springs" }];
    for group in definitions.as_array().into_iter().flatten() {
        let refs: Vec<_> = group["colliderGroups"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(idx)
            .collect();
        if refs.iter().any(|&g| g >= groups.len()) {
            return Err(invalid("invalid spring collider group"));
        }
        let group_colliders: Vec<_> = refs
            .iter()
            .flat_map(|&g| groups[g].iter().copied())
            .collect();
        let center = idx(&group["center"]);
        if center.is_some_and(|i| i >= nodes.len()) {
            return Err(invalid("invalid spring center"));
        }
        let mut joints = Vec::<(usize, Value)>::new();
        if legacy {
            let mut pending: Vec<_> = group["bones"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(idx)
                .collect();
            while let Some(i) = pending.pop() {
                let n = nodes.get(i).ok_or_else(|| invalid("invalid spring root"))?;
                joints.push((i, group.clone()));
                pending.extend_from_slice(&n.children);
            }
        } else {
            for j in group["joints"].as_array().into_iter().flatten() {
                let i = idx(&j["node"]).ok_or_else(|| invalid("invalid spring joint"))?;
                if i >= nodes.len() {
                    return Err(invalid("invalid spring joint"));
                }
                joints.push((i, j.clone()));
            }
        }
        for (index, (node, settings)) in joints.iter().enumerate() {
            // VRM1 chains explicitly list the child; VRM0 recursively includes all descendants.
            let child = if legacy {
                nodes[*node].children.first().copied()
            } else {
                joints.get(index + 1).map(|j| j.0)
            };
            let axis = child
                .map(|c| {
                    nodes[*node]
                        .rest_world
                        .inverse()
                        .transform_point3(nodes[c].rest_world.w_axis.truncate())
                })
                .unwrap_or_else(|| nodes[*node].rest.t.normalize_or(Vec3::NEG_Y) * 0.07);
            if axis.length() < 1e-6 {
                continue;
            }
            springs.push(Spring {
                node: *node,
                axis,
                current: Vec3::ZERO,
                previous: Vec3::ZERO,
                center,
                stiffness: number(
                    &settings[if legacy { "stiffiness" } else { "stiffness" }],
                    1.,
                )
                .max(0.),
                drag: number(&settings["dragForce"], 0.4).clamp(0., 1.),
                gravity: vec3(&settings["gravityDir"], Vec3::NEG_Y)
                    * number(&settings["gravityPower"], 0.),
                radius: number(&settings["hitRadius"], 0.).max(0.),
                colliders: group_colliders.clone(),
                initialized: false,
            });
        }
    }
    let mut rank = vec![0; nodes.len()];
    for (i, &n) in order.iter().enumerate() {
        rank[n] = i;
    }
    springs.sort_by_key(|s| rank[s.node]);
    springs.dedup_by_key(|s| s.node);
    Ok(springs)
}
pub(crate) fn step(model: &mut VrmModel, dt: f32) {
    for s in &mut model.springs {
        let center = s
            .center
            .map(|i| model.nodes[i].world)
            .unwrap_or(Mat4::IDENTITY);
        let base = model.nodes[s.node].world;
        let origin = base.w_axis.truncate();
        let rest_tail = base.transform_point3(s.axis);
        let length = origin.distance(rest_tail);
        if !s.initialized {
            s.current = center.inverse().transform_point3(rest_tail);
            s.previous = s.current;
            s.initialized = true;
        }
        let inertia = (s.current - s.previous) * (1. - s.drag).powf(dt * 60.);
        let mut next = center.transform_point3(s.current + inertia)
            + (rest_tail - origin).normalize_or_zero() * s.stiffness * dt
            + s.gravity * dt;
        next = constrain(next, origin, length, rest_tail - origin);
        for _ in 0..3 {
            for &c in &s.colliders {
                let c = &model.colliders[c];
                let world = model.nodes[c.node].world;
                let a = world.transform_point3(c.offset);
                let b = world.transform_point3(c.tail);
                let line = b - a;
                let closest = a + line
                    * ((next - a).dot(line) / line.length_squared().max(1e-9)).clamp(0., 1.);
                let scale = world.to_scale_rotation_translation().0.abs().max_element();
                let radius = s.radius + c.radius * scale;
                let offset = next - closest;
                if offset.length_squared() < radius * radius {
                    next = closest
                        + offset.normalize_or((rest_tail - origin).normalize_or(Vec3::Y)) * radius;
                    next = constrain(next, origin, length, rest_tail - origin);
                }
            }
        }
        s.previous = s.current;
        s.current = center.inverse().transform_point3(next);
        let direction = base.inverse().transform_point3(next).normalize_or_zero();
        if direction.length_squared() > 0.5 {
            let delta = Quat::from_rotation_arc(s.axis.normalize(), direction);
            model.nodes[s.node].pose.r = (model.nodes[s.node].pose.r * delta).normalize();
            // Update descendants immediately, so later joints and colliders see
            // their animated parent during this same simulation step.
            update_world(&mut model.nodes, &model.order);
        }
    }
}
fn constrain(tail: Vec3, origin: Vec3, length: f32, fallback: Vec3) -> Vec3 {
    origin + (tail - origin).normalize_or(fallback.normalize_or(Vec3::NEG_Y)) * length
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn length_constraint_survives_zero_distance() {
        let v = constrain(Vec3::ZERO, Vec3::ZERO, 0.2, Vec3::NEG_Y);
        assert!(v.is_finite());
        assert!((v.length() - 0.2).abs() < 1e-6);
    }
}
