//! Measures CPU animation and GPU upload preparation with a real moc/moc3 model.
//! Run in release mode; presentation, GPU waits and optional PNGs are not timed.

use std::collections::hash_map::DefaultHasher;
use std::error::Error;
use std::hash::{Hash, Hasher};
use std::path::Path;
use std::time::Instant;

use neocari::render::wgpu::WgpuLive2dRenderer;
use pet_live2d::ModelHandle;
use pet_render::{Gpu, ModelGpu};
use pet_window::sizing::{content_size, ModelLayout};

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args().skip(1);
    let path = args
        .next()
        .ok_or("usage: render_benchmark MODEL [FRAMES] [PNG_DIR]")?;
    let frames = args
        .next()
        .map(|n| n.parse::<usize>())
        .transpose()?
        .unwrap_or(600);
    if frames == 0 {
        return Err("FRAMES must be positive".into());
    }
    let output = args.next();
    let mut model = ModelHandle::load(Path::new(&path))?;
    // Disable the random blink timer so geometry checksums can be compared.
    model.set_auto_blink(false);
    model.set_auto_breath(false);
    if let Some(group) = model.info().default_motion_group().map(str::to_owned) {
        assert!(model.play_motion(&group));
    }
    let layout = ModelLayout::new(
        content_size(model.meshes()).ok_or("empty model")?,
        model.face_height(),
        model.info().format,
    );
    let matrix = layout.matrix(model.flips_y());
    let gpu = Gpu::new(true, None)?;
    let renderer = WgpuLive2dRenderer::new(&gpu.device, wgpu::TextureFormat::Rgba8Unorm);
    let mut uploaded = ModelGpu::new(&gpu, &renderer, model.meshes(), model.textures(), matrix)?;
    let mut animation = Vec::with_capacity(frames);
    let mut upload = Vec::with_capacity(frames);
    let mut checksum = DefaultHasher::new();
    for frame in 0..frames + 120 {
        let time = frame as f32 / 60.0;
        model.set_drag(time.sin() * 0.7, (time * 0.7).cos() * 0.5);
        model.set_lip_sync((time * 3.0).sin().max(0.0), (time * 2.0).sin());
        let start = Instant::now();
        assert!(model.update(1.0 / 60.0));
        let animated = start.elapsed();
        let start = Instant::now();
        uploaded.update_meshes(&gpu, &renderer, model.meshes())?;
        let prepared = start.elapsed();
        if frame >= 120 {
            animation.push(animated.as_secs_f64() * 1e6);
            upload.push(prepared.as_secs_f64() * 1e6);
        }
        // Submit/drain each frame, avoiding an ever-growing staging queue. This
        // is outside the measured CPU work and does not measure rendered FPS.
        gpu.queue.submit([]);
        gpu.device.poll(wgpu::PollType::wait_indefinitely())?;
        for mesh in model.meshes() {
            mesh.opacity().to_bits().hash(&mut checksum);
            mesh.draw_order().to_bits().hash(&mut checksum);
            mesh.render_order().hash(&mut checksum);
            for vertex in mesh.vertices() {
                vertex.position().map(f32::to_bits).hash(&mut checksum);
            }
        }
        if let Some(output) = output.as_ref().filter(|_| [120, 300, 600].contains(&frame)) {
            std::fs::create_dir_all(output)?;
            let rgba = uploaded.capture_rgba(&gpu, 512, 512)?;
            let reference =
                pet_render::render_preview(model.meshes(), model.textures(), matrix, 512, 512)?;
            assert_eq!(
                rgba, reference,
                "updated GPU frame differs from a fresh upload at {frame}"
            );
            assert!(rgba.as_chunks::<4>().0.iter().any(|pixel| pixel[3] > 0));
            image::save_buffer(
                Path::new(output).join(format!("frame-{frame}.png")),
                &rgba,
                512,
                512,
                image::ColorType::Rgba8,
            )?;
        }
    }
    let summarize = |mut values: Vec<f64>| {
        values.sort_by(f64::total_cmp);
        (
            values[values.len() / 2],
            values[(values.len() - 1) * 95 / 100],
        )
    };
    let (animation_median, animation_p95) = summarize(animation);
    let (upload_median, upload_p95) = summarize(upload);
    println!(
        "{}",
        serde_json::json!({
            "model": path,
            "adapter": gpu.adapter_info.name,
            "frames": frames,
            "drawables": model.meshes().len(),
            "vertices": model.meshes().iter().map(|m| m.vertices().len()).sum::<usize>(),
            "animation_median_us": animation_median,
            "animation_p95_us": animation_p95,
            "upload_median_us": upload_median,
            "upload_p95_us": upload_p95,
            "geometry_checksum": format!("{:016x}", checksum.finish()),
        })
    );
    Ok(())
}
