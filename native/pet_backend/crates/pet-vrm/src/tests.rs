use super::*;

fn fixture(legacy: bool) -> VrmModel {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(if legacy {
            "minimal-vrm0.vrm"
        } else {
            "minimal-vrm1.vrm"
        });
    VrmModel::load(&path).unwrap()
}

#[test]
fn pointer_tracking_rotates_head_in_screen_direction_during_motion_fades() {
    for legacy in [true, false] {
        for (x, y) in [(1., 0.), (-1., 0.), (0., 1.), (0., -1.)] {
            let mut tracked = fixture(legacy);
            let mut neutral = fixture(legacy);
            tracked.set_drag(x, y);
            for _ in 0..90 {
                tracked.update(1. / 120.);
                neutral.update(1. / 120.);
            }
            assert!(tracked.play_motion("Wave"));
            assert!(neutral.play_motion("Wave"));
            tracked.update(1. / 120.);
            neutral.update(1. / 120.);
            let head = tracked.humanoid["head"];
            let forward = if legacy { Vec3::Z } else { Vec3::NEG_Z };
            let direction = |model: &VrmModel| {
                let rotation = model.nodes[head].world.to_scale_rotation_translation().1;
                model.view.transform_vector3(rotation * forward)
            };
            let difference = direction(&tracked) - direction(&neutral);
            if x != 0. {
                assert!(
                    difference.x * x > 0.2,
                    "legacy={legacy}, drag=({x},{y}), delta={difference:?}"
                );
            } else {
                assert!(
                    difference.y * y > 0.15,
                    "legacy={legacy}, drag=({x},{y}), delta={difference:?}"
                );
            }
            assert_ne!(
                tracked.primitives[0].vertices[0].position,
                neutral.primitives[0].vertices[0].position
            );
            tracked.set_drag(0., 0.);
            for _ in 0..240 {
                tracked.update(1. / 120.);
                neutral.update(1. / 120.);
            }
            assert!(direction(&tracked).distance(direction(&neutral)) < 0.001);
        }
    }
}
#[test]
fn vrm_versions_load_mtoon_morphs_and_physics() {
    for legacy in [true, false] {
        let mut model = fixture(legacy);
        assert_eq!(model.legacy, legacy);
        assert!(model.spring_count() >= 2);
        assert_eq!(model.colliders.len(), 1);
        assert!(!model.materials[0].unlit);
        assert!(model.materials[0].outline_width > 0.);
        let old = model.primitives[0].vertices.clone();
        let name = model.expression_names[0].clone();
        assert!(model.play_expression(&name));
        model.update(1. / 60.);
        assert_ne!(old[0].position, model.primitives[0].vertices[0].position);
        assert!(!model.play_motion("missing"));
        assert!(model.play_motion("SampleArm"));
        let before = model.nodes[2].pose.r;
        model.update(0.1);
        assert!(model.nodes[2].pose.r.angle_between(before) > 0.001);
    }
}
#[test]
fn desktop_motion_excites_hair_and_clothing_and_settles() {
    for legacy in [true, false] {
        let mut model = fixture(legacy);
        model.set_auto_breath(false);
        model.update(1. / 60.);
        model.set_desktop_position(0, 0, 0.002);
        model.set_desktop_position(30, 0, 0.002);
        model.update(1. / 120.);
        for i in [3, 4] {
            assert!(
                model.nodes[i].pose.r.angle_between(model.nodes[i].rest.r) > 0.001,
                "spring {i} did not move"
            );
        }
        for _ in 0..600 {
            assert!(model.update(1. / 120.));
        }
        assert!(model.primitives.iter().flat_map(|p| &p.vertices).all(|v| v
            .position
            .iter()
            .chain(&v.normal)
            .all(|n| n.is_finite())));
        for spring in &model.springs {
            assert!(spring.displacement(&model.nodes) < 0.1);
        }
        assert!(!model.update(f32::NAN));
        assert!(!model.update(-1.));
    }
}
#[test]
fn fixed_step_is_independent_of_presentation_rate() {
    let mut a = fixture(true);
    let mut b = fixture(true);
    for _ in 0..60 {
        a.update(1. / 60.);
    }
    for _ in 0..120 {
        b.update(1. / 120.);
    }
    for (a, b) in a.primitives[0]
        .vertices
        .iter()
        .zip(&b.primitives[0].vertices)
    {
        assert!(Vec3::from(a.position).distance(Vec3::from(b.position)) < 1e-5);
    }
}
#[test]
fn orthographic_view_faces_front_without_depth_scaling() {
    let model = fixture(true);
    let x = model.view.transform_vector3(Vec3::X).truncate().length();
    let y = model.view.transform_vector3(Vec3::Y).truncate().length();
    let z = model.view.transform_vector3(Vec3::Z).truncate().length();
    assert!((x - 1.).abs() < 1e-5 && (y - 1.).abs() < 1e-5 && z < 1e-5);
    let a = model.view.transform_point3(Vec3::new(0.2, 0.5, -2.));
    let b = model.view.transform_point3(Vec3::new(0.2, 0.5, 2.));
    assert_eq!(a.truncate(), b.truncate());
}

fn largest_body_step(model: &VrmModel, before: &[Transform]) -> f32 {
    model
        .humanoid
        .values()
        .map(|&i| model.last_pose[i].r.angle_between(before[i].r))
        .fold(0., f32::max)
}

#[test]
fn switching_and_interrupting_motions_preserves_pose_continuity() {
    let mut model = fixture(true);
    for _ in 0..120 {
        model.update(1. / 120.);
    }
    for name in ["Wave", "Thinking", "LookAround", "Idle"] {
        let before = model.last_pose.clone();
        assert!(model.play_motion(name));
        assert!(largest_body_step(&model, &before) < 0.001);
        model.update(1. / 120.);
        assert!(
            largest_body_step(&model, &before) < 0.035,
            "{name} snapped on entry"
        );
        for _ in 0..80 {
            model.update(1. / 120.);
        }
    }
    let time = model.time;
    assert!(model.play_motion("Idle"));
    assert_eq!(model.time, time, "idle must not restart on behavior resets");
}

#[test]
fn idle_loop_closes_and_interactions_return_to_idle_smoothly() {
    let mut model = fixture(true);
    let clip = model.clips.get("Idle").unwrap();
    let period = clip.duration - (clip.duration * 0.15).min(0.65);
    let base: Vec<_> = model.nodes.iter().map(|n| n.pose).collect();
    clip.apply_looped(period - 0.0001, &mut model.nodes, &model.humanoid, true);
    let before: Vec<_> = model.nodes.iter().map(|n| n.pose).collect();
    for (node, pose) in model.nodes.iter_mut().zip(base) {
        node.pose = pose;
    }
    clip.apply_looped(period + 0.0001, &mut model.nodes, &model.humanoid, true);
    for &i in model.humanoid.values() {
        assert!(
            model.nodes[i].pose.r.angle_between(before[i].r) < 0.002,
            "rotation discontinuity at loop seam"
        );
        assert!(
            model.nodes[i].pose.t.distance(before[i].t) < 0.001,
            "translation discontinuity at loop seam"
        );
    }
    model.play_motion("Wave");
    let mut returned = false;
    for _ in 0..700 {
        let before = model.last_pose.clone();
        let was_wave = model.active_motion() == Some("Wave");
        model.update(1. / 120.);
        if was_wave && model.active_motion() == Some("Idle") {
            assert!(largest_body_step(&model, &before) < 0.035);
            returned = true;
        }
    }
    assert!(returned);
    assert!(model.is_motion_finished());
    assert_eq!(model.active_motion(), Some("Idle"));
}

#[test]
fn expressions_fade_and_blinks_use_varied_intervals() {
    let mut model = fixture(true);
    model.play_expression("happy");
    model.update(1. / 120.);
    let first = model.face.weight("joy");
    assert!(first > 0. && first < 0.1);
    for _ in 0..60 {
        model.update(1. / 120.);
    }
    let peak = model.face.weight("joy");
    assert!(peak > 0.5 && peak <= 0.65);
    model.clear_expression();
    model.update(1. / 120.);
    let fading = model.face.weight("joy");
    assert!(fading < peak && fading > 0.4);
    for _ in 0..120 {
        model.update(1. / 120.);
    }
    assert!(model.face.weight("joy") < 0.001);
    let mut face = performance::Face::new(&Value::Null);
    let mut starts = Vec::new();
    let mut previous = 0.;
    for frame in 0..2400 {
        face.update(1. / 120., &[], ("relaxed", 0.), true, 0., [0.; 2]);
        if face.blink > 0. && previous == 0. {
            starts.push(frame as f32 / 120.);
        }
        previous = face.blink;
    }
    assert!(starts.len() >= 4);
    assert!(((starts[2] - starts[1]) - (starts[1] - starts[0])).abs() > 0.2);
}

#[test]
fn centimeter_source_animation_keeps_desktop_root_in_place() {
    let mut model = fixture(true);
    let hips = model.humanoid["hips"];
    for _ in 0..1600 {
        model.update(1. / 120.);
        assert!(
            model.nodes[hips].pose.t.distance(model.nodes[hips].rest.t) < 0.08,
            "mocap units or origin moved the avatar out of its window"
        );
    }
}
