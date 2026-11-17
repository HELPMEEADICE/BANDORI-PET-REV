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
fn morph_accessors_share_storage_without_aliasing_other_streams_or_documents() {
    let manifest = serde_json::json!({
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 48}],
        "bufferViews": [{"buffer": 0, "byteLength": 24},
                        {"buffer": 0, "byteOffset": 24, "byteLength": 24}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC3"}
        ]
    });
    let document = gltf::Gltf::from_slice(&serde_json::to_vec(&manifest).unwrap()).unwrap();
    let accessors: Vec<_> = document.accessors().collect();
    let mut cache = HashMap::new();
    let values = [[0., 1., 2.], [3., 4., 5.]];
    let first = morph_attribute(
        &mut cache,
        Some(accessors[0].clone()),
        Some(values.into_iter()),
    );
    // A cache hit must not decode or traverse the stream again.
    let shared = morph_attribute(
        &mut cache,
        Some(accessors[0].clone()),
        Some(std::iter::from_fn(|| -> Option<[f32; 3]> {
            panic!("decoded twice")
        })),
    );
    let other = morph_attribute(
        &mut cache,
        Some(accessors[1].clone()),
        Some(values.into_iter()),
    );
    assert!(Arc::ptr_eq(&first, &shared));
    assert!(!Arc::ptr_eq(&first, &other));
    assert_eq!(&*first, &[Vec3::new(0., 1., 2.), Vec3::new(3., 4., 5.)]);
    let missing = morph_attribute(&mut cache, None, Some(values.into_iter()));
    assert!(missing.is_empty());
    assert_eq!(cache.len(), 2);
    drop(cache);
    assert_eq!(Arc::strong_count(&first), 2);
    let separate = morph_attribute(
        &mut HashMap::new(),
        Some(accessors[0].clone()),
        Some(values.into_iter()),
    );
    assert!(!Arc::ptr_eq(&first, &separate));
}

#[test]
fn pointer_tracking_corrects_inverted_screen_direction_during_motion_fades() {
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
                    difference.x * x < -0.2,
                    "legacy={legacy}, drag=({x},{y}), delta={difference:?}"
                );
            } else {
                assert!(
                    difference.y * y < -0.15,
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

#[test]
fn sparse_morph_skinning_matches_the_scalar_reference() {
    for legacy in [true, false] {
        let mut model = fixture(legacy);
        let primitive = &mut model.primitives[0];
        primitive.morphs = (0..6)
            .map(|m| {
                (
                    (0..primitive.bind.len())
                        .map(|i| Vec3::new(i as f32 * 0.01, m as f32 * 0.02, 0.))
                        .collect(),
                    Arc::from(if m % 2 == 0 {
                        vec![]
                    } else {
                        vec![Vec3::X * 0.1; primitive.bind.len()]
                    }),
                )
            })
            .collect();
        // Include inactive targets, clamped weights, missing base weights and
        // several expression binds contributing to the same target.
        primitive.weights = vec![0., -0.5, 0.3, 1.2];
        model.expressions = vec![
            Expression {
                name: "test-a".into(),
                binds: vec![(primitive.mesh, 0, 0.5), (primitive.mesh, 2, 0.5)],
            },
            Expression {
                name: "test-b".into(),
                binds: vec![(primitive.mesh, 2, 0.8), (primitive.mesh, 4, 0.7)],
            },
        ];
        model.face.weights.insert("test-a".into(), 0.6);
        model.face.weights.insert("test-b".into(), 0.9);
        let mut weights = BTreeMap::<(usize, usize), f32>::new();
        for expression in &model.expressions {
            for &(mesh, target, weight) in &expression.binds {
                *weights.entry((mesh, target)).or_default() +=
                    weight * model.face.weight(&expression.name);
            }
        }
        let expected: Vec<Vec<Vertex>> = model
            .primitives
            .iter()
            .map(|p| {
                p.bind
                    .iter()
                    .enumerate()
                    .map(|(i, bind)| {
                        let mut position = bind.position;
                        let mut normal = bind.normal;
                        for (m, (positions, normals)) in p.morphs.iter().enumerate() {
                            let weight = (p.weights.get(m).copied().unwrap_or(0.)
                                + weights.get(&(p.mesh, m)).copied().unwrap_or(0.))
                            .clamp(0., 1.);
                            if weight != 0. {
                                position +=
                                    positions.get(i).copied().unwrap_or(Vec3::ZERO) * weight;
                                normal += normals.get(i).copied().unwrap_or(Vec3::ZERO) * weight;
                            }
                        }
                        let transform = if let Some(s) = p.skin {
                            let skin = &model.skins[s];
                            let mut matrix = Mat4::ZERO;
                            let mut total = 0.;
                            for (&joint, &weight) in bind.joints.iter().zip(&bind.weights) {
                                if weight > 0. {
                                    matrix += (model.nodes[skin.joints[joint as usize]].world
                                        * skin.inverse[joint as usize])
                                        * weight;
                                    total += weight;
                                }
                            }
                            if total > 1e-6 {
                                matrix * (1. / total)
                            } else {
                                model.nodes[p.node].world
                            }
                        } else {
                            model.nodes[p.node].world
                        };
                        Vertex {
                            position: model
                                .view
                                .transform_point3(transform.transform_point3(position))
                                .to_array(),
                            normal: model
                                .view
                                .transform_vector3(transform.transform_vector3(normal))
                                .normalize_or_zero()
                                .to_array(),
                            uv: bind.uv,
                        }
                    })
                    .collect()
            })
            .collect();
        model.skin();
        for (p, expected) in model.primitives.iter().zip(expected) {
            for (actual, expected) in p.vertices.iter().zip(expected) {
                assert!(Vec3::from(actual.position).distance(Vec3::from(expected.position)) < 1e-6);
                assert!(Vec3::from(actual.normal).distance(Vec3::from(expected.normal)) < 1e-6);
                assert_eq!(actual.uv, expected.uv);
            }
        }
    }
}

#[test]
fn shared_hit_vertices_preserve_u32_triangles_chunk_boundaries_and_uvs() {
    let mut model = fixture(false);
    let primitive = &mut model.primitives[0];
    for i in primitive.bind.len()..65_540 {
        let source = &primitive.bind[i % 3];
        primitive.bind.push(BindVertex {
            position: source.position,
            normal: source.normal,
            uv: [i as f32 / 65_540., (i % 7) as f32 / 7.],
            joints: source.joints,
            weights: source.weights,
        });
    }
    primitive.indices = [65_536, 2, 65_539, 65_536, 65_539, 2].repeat(10_001);
    let material = &mut model.materials[primitive.material];
    material.uv_scale = [1.2, 0.7];
    material.uv_rotation = 0.6;
    material.uv_offset = [0.2, -0.3];
    model.prepare_hit_projections();
    assert_eq!(model.hit_projections.len(), 2);
    assert_eq!(model.projected[0].indices().len(), 60_000);
    assert_eq!(model.projected[1].indices().len(), 6);
    let sources: Vec<_> = model
        .hit_projections
        .iter()
        .map(|p| p.sources.as_ptr())
        .collect();
    for _ in 0..3 {
        model.update(1. / 60.);
        let primitive = &model.primitives[0];
        let material = &model.materials[primitive.material];
        for (chunk, mesh) in primitive.indices.chunks(60_000).zip(&model.projected) {
            assert_eq!(mesh.vertices().len(), 3);
            assert_eq!(mesh.texture_index(), material.hit_texture as i32);
            for (&source, &index) in chunk.iter().zip(mesh.indices()) {
                let actual = mesh.vertices()[index as usize];
                let vertex = primitive.vertices[source as usize];
                assert_eq!(actual.position(), [vertex.position[0], vertex.position[1]]);
                let x = vertex.uv[0] * material.uv_scale[0];
                let y = vertex.uv[1] * material.uv_scale[1];
                let expected = [
                    x * material.uv_rotation.cos() - y * material.uv_rotation.sin()
                        + material.uv_offset[0],
                    x * material.uv_rotation.sin()
                        + y * material.uv_rotation.cos()
                        + material.uv_offset[1],
                ];
                for (actual, expected) in actual.uv().iter().zip(expected) {
                    assert!((actual - expected).abs() < 1e-6);
                }
            }
        }
        assert_eq!(
            sources,
            model
                .hit_projections
                .iter()
                .map(|p| p.sources.as_ptr())
                .collect::<Vec<_>>()
        );
    }
}

#[test]
fn embedded_texture_sources_keep_manifest_order_and_shared_references() {
    let colors = [[10, 20, 30, 40], [50, 60, 70, 80]];
    let mut blob = std::io::Cursor::new(Vec::new());
    let mut views = Vec::new();
    for color in colors {
        let offset = blob.position();
        image::DynamicImage::ImageRgba8(image::RgbaImage::from_pixel(2, 3, image::Rgba(color)))
            .write_to(&mut blob, image::ImageFormat::Png)
            .unwrap();
        views.push(serde_json::json!({"buffer": 0, "byteOffset": offset, "byteLength": blob.position() - offset}));
    }
    let data = serde_json::json!({
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": blob.get_ref().len()}],
        "bufferViews": views,
        "images": [{"bufferView": 0, "mimeType": "image/png"},
                   {"bufferView": 1, "mimeType": "image/png"},
                   {"uri": "unused-thumbnail.png"}],
        "textures": [{"source": 1}, {"source": 0}, {"source": 1}],
    });
    let gltf = gltf::Gltf::from_slice(&serde_json::to_vec(&data).unwrap()).unwrap();
    let textures = load_textures(&gltf, blob.get_ref()).unwrap();
    assert_eq!(textures.len(), 3);
    for (texture, color) in textures.iter().zip([colors[1], colors[0], colors[1]]) {
        assert_eq!((texture.width(), texture.height()), (2, 3));
        assert!(texture.rgba().chunks_exact(4).all(|pixel| pixel == color));
    }
    assert!(load_textures(&gltf, &[]).is_err());
}
