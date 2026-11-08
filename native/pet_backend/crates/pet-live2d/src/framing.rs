//! Stable face measurements for equal perceived size across Cubism generations.

use neocari::assets::Moc2RuntimeModel;
use neocari::moc3::Moc3DrawableMesh;

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
