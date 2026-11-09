//! Render neutral pets at their real desktop scale for visual sizing checks.
//! Usage: cargo run --release --example framing_probe -- OUTPUT_DIR MODEL...
//! MODEL accepts the same archive::member paths as the application.
use std::error::Error;
use std::path::PathBuf;

use pet_assets::ModelCache;
use pet_live2d::ModelHandle;
use pet_window::sizing::{content_size, upper_body_bounds, ModelLayout};

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args().skip(1);
    let output = PathBuf::from(
        args.next()
            .ok_or("usage: framing_probe OUTPUT_DIR MODEL...")?,
    );
    std::fs::create_dir_all(&output)?;
    // Isolate probe extraction from the running application's costume cache.
    let cache = ModelCache::new(output.join("cache"), PathBuf::from("models"));
    for (index, path) in args.enumerate() {
        let resolved = cache.resolve(&path)?;
        let model = ModelHandle::load(&resolved.model_path)?;
        let content = content_size(model.meshes()).ok_or("empty model")?;
        let upper = upper_body_bounds(model.meshes(), model.face_height(), model.flips_y())
            .unwrap_or(content);
        let layout = ModelLayout::from_upper_body(content, upper, model.format());
        let (width, height) = layout.window_size(100.0, 1.0);
        let pixels_per_unit = height as f32 / layout.viewport.height();
        let rgba = pet_render::render_preview(
            model.meshes(),
            model.textures(),
            layout.matrix(model.flips_y()),
            width,
            height,
        )?;
        let image = output.join(format!("{index}.png"));
        image::save_buffer(&image, &rgba, width, height, image::ColorType::Rgba8)?;
        println!(
            "{}",
            serde_json::json!({
                "model": path,
                "image": image,
                "window": [width, height],
                "content_bounds": [content.min_x, content.min_y, content.max_x, content.max_y],
                "upper_bounds": [upper.min_x, upper.min_y, upper.max_x, upper.max_y],
                "pixels_per_unit": pixels_per_unit,
                "face_pixels": model.face_height().map(|face| face * pixels_per_unit),
            })
        );
    }
    Ok(())
}
