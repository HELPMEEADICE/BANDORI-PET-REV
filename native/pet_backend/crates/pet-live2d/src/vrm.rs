use crate::{Live2dError, ModelInfo};
use neocari::{assets::DecodedTexture, moc3::Moc3DrawableMesh};
use std::path::Path;

pub struct VrmAdapter {
    pub model: pet_vrm::VrmModel,
    info: ModelInfo,
}
impl VrmAdapter {
    pub fn load(path: &Path) -> Result<Self, Live2dError> {
        let model = pet_vrm::VrmModel::load(path)?;
        let info = ModelInfo {
            format: pet_config::ModelFormat::Vrm,
            motion_groups: model.motion_names.clone(),
            expression_names: model.expression_names.clone(),
            texture_count: model.textures.len(),
            canvas_width: 1.,
            canvas_height: 1.,
        };
        Ok(Self { model, info })
    }
    pub fn info(&self) -> &ModelInfo {
        &self.info
    }
    pub fn meshes(&self) -> &[Moc3DrawableMesh] {
        &self.model.projected
    }
    pub fn textures(&self) -> &[DecodedTexture] {
        &self.model.textures
    }
    pub fn take_textures(&mut self) -> Vec<DecodedTexture> {
        std::mem::take(&mut self.model.textures)
    }
    pub fn face_height(&self) -> Option<f32> {
        self.model.face_height()
    }
    pub fn hit_test_area(&mut self, _x: f32, _y: f32) -> Option<String> {
        None
    }
    pub fn active_motion_group(&self) -> Option<&str> {
        self.model.active_motion()
    }
}
impl std::ops::Deref for VrmAdapter {
    type Target = pet_vrm::VrmModel;
    fn deref(&self) -> &Self::Target {
        &self.model
    }
}
impl std::ops::DerefMut for VrmAdapter {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.model
    }
}
