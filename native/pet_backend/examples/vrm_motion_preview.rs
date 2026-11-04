//! Capture a reproducible native animation sequence with fixed front framing.
//! vrm_motion_preview MODEL OUTPUT_DIR [MOTION] [SECONDS] [FPS]
use pet_live2d::ModelHandle;
use pet_render::{Gpu, ModelGpu};
use pet_window::sizing::{content_size, upper_body_bounds, ModelLayout};
use std::{error::Error, path::Path};

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let path = args
        .first()
        .ok_or("usage: vrm_motion_preview MODEL OUTPUT_DIR [MOTION] [SECONDS] [FPS]")?;
    let output = args.get(1).ok_or("missing output directory")?;
    let motion = args.get(2).map(String::as_str).unwrap_or("Idle");
    let seconds: f32 = args.get(3).map(|s| s.parse()).transpose()?.unwrap_or(8.);
    let fps: u32 = args.get(4).map(|s| s.parse()).transpose()?.unwrap_or(15);
    if !seconds.is_finite() || !(0.1..=60.).contains(&seconds) || !(1..=60).contains(&fps) {
        return Err("seconds 0.1..60 and FPS 1..60 required".into());
    }
    std::fs::create_dir_all(output)?;
    let mut model = ModelHandle::load(Path::new(path))?;
    let bounds = content_size(model.meshes()).ok_or("empty model")?;
    let upper_body =
        upper_body_bounds(model.meshes(), model.face_height(), model.flips_y()).unwrap_or(bounds);
    let layout = ModelLayout::from_upper_body(bounds, upper_body);
    let matrix = layout.matrix(false);
    let (width, height) = layout.window_size(70., 1.);
    let gpu = Gpu::new(true, None)?;
    let mut uploaded = ModelGpu::new_vrm(
        &gpu,
        model.vrm().ok_or("not VRM")?,
        matrix,
        wgpu::TextureFormat::Rgba8Unorm,
    )?;
    // Start gestures after a second of idle, capturing both crossfades and settle.
    let frames = (seconds * fps as f32).ceil() as usize;
    let mut last_time = 0.;
    let mut triggered = motion == "Idle";
    for frame in 0..frames {
        let time = frame as f32 / fps as f32;
        if !triggered && time >= 1. {
            if !model.play_motion(motion) {
                return Err(format!("unknown motion {motion}").into());
            }
            triggered = true;
        }
        let steps = ((time - last_time) * 120.).round() as u32;
        for _ in 0..steps {
            model.update(1. / 120.);
        }
        last_time += steps as f32 / 120.;
        uploaded.update_vrm(&gpu, model.vrm().unwrap());
        let rgba = uploaded.capture_rgba(&gpu, width, height)?;
        if !rgba.as_chunks::<4>().0.iter().any(|p| p[3] > 0) {
            return Err(format!("avatar left its frame at {time:.3}s").into());
        }
        image::save_buffer(
            Path::new(output).join(format!("{frame:04}.png")),
            &rgba,
            width,
            height,
            image::ColorType::Rgba8,
        )?;
    }
    println!(
        "{}",
        serde_json::json!({"frames":frames,"fps":fps,"motion":motion,"width":width,"height":height,"projection":"front-orthographic"})
    );
    Ok(())
}
