//! Stable face measurements for equal perceived size across Cubism generations.

use std::path::Path;

use neocari::assets::{Moc2RuntimeModel, RuntimeModel};
use neocari::json::Cdi3;
use neocari::moc3::{Moc3DrawableMesh, Moc3OffscreenInfo};

fn mesh_height<'a>(meshes: impl Iterator<Item = &'a Moc3DrawableMesh>) -> Option<f32> {
    let (mut min, mut max) = (f32::INFINITY, f32::NEG_INFINITY);
    for vertex in meshes.flat_map(|mesh| mesh.vertices()) {
        let y = vertex.position()[1];
        min = min.min(y);
        max = max.max(y);
    }
    let height = max - min;
    (height.is_finite() && height > 1e-4).then_some(height)
}

pub(crate) fn moc2_face_height(model: &Moc2RuntimeModel) -> Option<f32> {
    let scene = model.runtime().scene();
    mesh_height(
        scene
            .parts()
            .iter()
            .filter(|part| part.id().to_ascii_uppercase().contains("_FACE"))
            .flat_map(|part| part.drawables())
            .filter_map(|&index| model.meshes().get(index)),
    )
}

pub(crate) fn moc3_face_height(model: &RuntimeModel, model_dir: &Path) -> Option<f32> {
    let runtime = model.runtime();
    let manifest = runtime.model();
    let cdi_path = model_dir.join(manifest.display_info()?);
    let cdi = Cdi3::from_json_str(&std::fs::read_to_string(cdi_path).ok()?).ok()?;
    let bytes = std::fs::read(model_dir.join(manifest.moc())).ok()?;
    let parts = Moc3OffscreenInfo::parse(&bytes).ok()?;
    // The face outline excludes hair, ears, and oversized expression shadows.
    // Bandori uses Japanese display names with numeric internal part ids.
    for label in ["輪郭", "顔", "face"] {
        let indices: Vec<_> = cdi
            .parts()
            .iter()
            .filter(|part| {
                part.name()
                    .trim()
                    .trim_start_matches('*')
                    .eq_ignore_ascii_case(label)
            })
            .filter_map(|part| runtime.part_index(part.id()))
            .collect();
        let height = mesh_height(runtime.meshes().iter().enumerate().filter_map(
            |(index, mesh)| {
                let parent = usize::try_from(parts.drawable_parent_part_index(index)?).ok()?;
                indices.contains(&parent).then_some(mesh)
            },
        ));
        if height.is_some() {
            return height;
        }
    }
    None
}
