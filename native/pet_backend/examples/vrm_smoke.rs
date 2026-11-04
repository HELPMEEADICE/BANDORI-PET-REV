//! Real-asset animation, physics, alpha-hit and wgpu capture validation.
//! cargo run --example vrm_smoke -- MODEL.vrm OUTPUT_DIR [FRAMES]
use pet_input::hit::{AlphaTexture, FrameSnapshot};
use pet_live2d::ModelHandle;
use pet_render::{Gpu, ModelGpu};
use pet_window::sizing::{content_size, upper_body_bounds, ModelLayout};
use std::{error::Error, path::Path, sync::Arc, time::Instant};

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let path = args
        .first()
        .ok_or("usage: vrm_smoke MODEL.vrm OUTPUT_DIR [FRAMES]")?;
    let output = args.get(1).ok_or("missing output directory")?;
    let frames: usize = args.get(2).map(|s| s.parse()).transpose()?.unwrap_or(180);
    if frames < 60 {
        return Err("FRAMES must be >= 60".into());
    }
    std::fs::create_dir_all(output)?;
    let mut model = ModelHandle::load(Path::new(path))?;
    let bounds = content_size(model.meshes()).ok_or("missing bounds")?;
    let upper_body =
        upper_body_bounds(model.meshes(), model.face_height(), model.flips_y()).unwrap_or(bounds);
    let layout = ModelLayout::from_upper_body(bounds, upper_body);
    let matrix = layout.matrix(false);
    let (width, height) = layout.window_size(100., 1.);
    let gpu = Gpu::new(true, None)?;
    let mut uploaded = ModelGpu::new_vrm(
        &gpu,
        model.vrm().ok_or("not VRM")?,
        matrix,
        wgpu::TextureFormat::Rgba8Unorm,
    )?;
    let hit_textures = Arc::new(
        model
            .take_textures()
            .into_iter()
            .map(AlphaTexture::from)
            .collect(),
    );
    let joints = model.vrm().unwrap().spring_count();
    let vertices = model
        .vrm()
        .unwrap()
        .primitives
        .iter()
        .map(|p| p.vertices.len())
        .sum::<usize>();
    let mut samples = Vec::new();
    let mut displacement = 0f32;
    let mut hits = 0;
    let mut initial = None;
    let mut changed = false;
    assert!(model.play_motion("SampleArm"));
    for frame in 0..frames {
        let start = Instant::now();
        let vrm = model.vrm_mut().unwrap();
        vrm.set_desktop_position(if frame < 30 { 0 } else { 40 }, 0, 0.002);
        model.set_drag((frame as f32 * 0.03).sin() * 0.5, 0.);
        assert!(model.update(1. / 60.));
        let vrm = model.vrm().unwrap();
        displacement = displacement.max(vrm.physics_displacement());
        uploaded.update_vrm(&gpu, vrm);
        samples.push(start.elapsed().as_secs_f64() * 1000.);
        gpu.queue.submit([]);
        gpu.device.poll(wgpu::PollType::wait_indefinitely())?;
        if [0, frames / 2, frames - 1].contains(&frame) {
            let rgba = uploaded.capture_rgba(&gpu, width, height)?;
            assert!(rgba.as_chunks::<4>().0.iter().any(|p| p[3] > 0));
            let snapshot = FrameSnapshot::new(model.meshes(), Arc::clone(&hit_textures), matrix);
            assert!(!snapshot.hit_test((0., 0.), (width, height), 8).hit);
            for y in (0..height).step_by(10) {
                for x in (0..width).step_by(10) {
                    if rgba[((y * width + x) * 4 + 3) as usize] > 200 {
                        hits += usize::from(
                            snapshot
                                .hit_test((x as f32 + 0.5, y as f32 + 0.5), (width, height), 8)
                                .hit,
                        );
                    }
                }
            }
            if let Some(first) = &initial {
                changed |= first != &rgba;
            } else {
                initial = Some(rgba.clone());
            }
            image::save_buffer(
                Path::new(output).join(format!("frame-{frame}.png")),
                &rgba,
                width,
                height,
                image::ColorType::Rgba8,
            )?;
        }
    }
    assert!(changed, "VRMA did not change rendered pixels");
    assert!(hits > 0, "visible pixels were not interactive");
    if joints > 0 {
        assert!(displacement > 0.001, "spring bones did not react");
    }
    samples.sort_by(f64::total_cmp);
    println!(
        "{}",
        serde_json::json!({"model":path,"adapter":gpu.adapter_info.name,"frames":frames,"vertices":vertices,"spring_joints":joints,"max_spring_displacement":displacement,"visible_hit_samples":hits,"cpu_update_upload_median_ms":samples[frames/2],"cpu_update_upload_p95_ms":samples[(frames-1)*95/100],"animation_changed_pixels":changed})
    );
    Ok(())
}
