//! Pixel pets use the same native renderer and alpha hit testing as Live2D.
use std::path::Path;

use neocari::assets::DecodedTexture;
use neocari::moc3::{Moc3DrawableMesh, Moc3DrawableVertex};
use pet_config::ModelFormat;
use serde_json::Value;

use crate::{Live2dError, ModelInfo};

pub struct SpriteAdapter {
    info: ModelInfo,
    textures: Vec<DecodedTexture>,
    meshes: Vec<Moc3DrawableMesh>,
    animations: Value,
    active: String,
    elapsed: f32,
    cols: f32,
    rows: f32,
}

impl SpriteAdapter {
    pub fn load(path: &Path) -> Result<Self, Live2dError> {
        let image = image::open(path)
            .map_err(|e| Live2dError::Unsupported(e.to_string()))?
            .into_rgba8();
        let metadata: Value = serde_json::from_slice(
            &std::fs::read(path.with_file_name("frames.json"))
                .map_err(|e| Live2dError::Unsupported(e.to_string()))?,
        )
        .map_err(|e| Live2dError::Unsupported(e.to_string()))?;
        let cols = metadata["spriteSheet"]["totalCols"]
            .as_u64()
            .unwrap_or(8)
            .clamp(1, 256) as f32;
        let rows = metadata["spriteSheet"]["totalRows"]
            .as_u64()
            .unwrap_or(9)
            .clamp(1, 256) as f32;
        let width = image.width() as f32 / cols;
        let height = image.height() as f32 / rows;
        let animations = metadata["animations"].clone();
        let names = animations
            .as_object()
            .ok_or_else(|| Live2dError::Unsupported("invalid sprite animations".into()))?
            .keys()
            .cloned()
            .collect();
        let texture = DecodedTexture::new(image.width(), image.height(), image.into_raw());
        let mut result = Self {
            info: ModelInfo {
                format: ModelFormat::Moc,
                motion_groups: names,
                expression_names: Vec::new(),
                texture_count: 1,
                canvas_width: width,
                canvas_height: height,
            },
            textures: vec![texture],
            meshes: Vec::new(),
            animations,
            active: "idle".into(),
            elapsed: 0.0,
            cols,
            rows,
        };
        result.update(0.0);
        Ok(result)
    }
    pub fn info(&self) -> &ModelInfo {
        &self.info
    }
    pub fn meshes(&self) -> &[Moc3DrawableMesh] {
        &self.meshes
    }
    pub fn textures(&self) -> &[DecodedTexture] {
        &self.textures
    }
    pub fn take_textures(&mut self) -> Vec<DecodedTexture> {
        std::mem::take(&mut self.textures)
    }
    pub fn update(&mut self, dt: f32) -> bool {
        self.elapsed += dt;
        let animation = &self.animations[&self.active];
        let frames = animation["frames"].as_u64().unwrap_or(1).max(1) as usize;
        let fps = animation["fps"].as_f64().unwrap_or(8.0).max(1.0) as f32 / 3.0;
        let frame = (self.elapsed * fps) as usize;
        if frame >= frames && animation["loop"] == false {
            self.active = "idle".into();
            self.elapsed = 0.0;
            return self.update(0.0);
        }
        let col = (frame % frames) as f32;
        let row = animation["row"].as_u64().unwrap_or(0) as f32;
        let (u0, v0, u1, v1) = (
            col / self.cols,
            row / self.rows,
            (col + 1.0) / self.cols,
            (row + 1.0) / self.rows,
        );
        let (w, h) = (self.info.canvas_width, self.info.canvas_height);
        self.meshes = vec![Moc3DrawableMesh::from_parts(
            0,
            0,
            1.0,
            0.0,
            vec![
                Moc3DrawableVertex::new([0.0, 0.0], [u0, v0]),
                Moc3DrawableVertex::new([w, 0.0], [u1, v0]),
                Moc3DrawableVertex::new([w, h], [u1, v1]),
                Moc3DrawableVertex::new([0.0, h], [u0, v1]),
            ],
            vec![0, 1, 2, 0, 2, 3],
            vec![],
        )];
        true
    }
    pub fn play_motion(&mut self, name: &str) -> bool {
        if self.animations.get(name).is_none() {
            return false;
        }
        if self.active != name {
            self.active = name.into();
            self.elapsed = 0.0;
        }
        true
    }
    pub fn play_expression(&mut self, _name: &str) -> bool {
        false
    }
    pub fn clear_expression(&mut self) {}
    pub fn active_expression_count(&self) -> usize {
        0
    }
    pub fn stop_motions(&mut self) {
        self.active = "idle".into();
        self.elapsed = 0.0;
    }
    pub fn is_motion_finished(&self) -> bool {
        self.active == "idle"
    }
    pub fn active_motion_group(&self) -> Option<&str> {
        Some(&self.active)
    }
    pub fn set_drag(&mut self, _x: f32, _y: f32) {}
    pub fn set_auto_blink(&mut self, _enabled: bool) {}
    pub fn set_auto_breath(&mut self, _enabled: bool) {}
    pub fn set_mouth_open(&mut self, _value: f32) {}
    pub fn set_lip_sync(&mut self, _open: f32, _form: f32) {}
    pub fn hit_test_area(&mut self, _x: f32, _y: f32) -> Option<String> {
        None
    }
    pub fn face_height(&self) -> Option<f32> {
        None
    }
}
