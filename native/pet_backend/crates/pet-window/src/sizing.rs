//! Face-normalized model sizing with a separate, padded animation viewport.

use neocari::core::Matrix44;
use neocari::moc3::Moc3DrawableMesh;
use pet_config::ModelFormat;

/// Model-space axis-aligned bounding box.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Bounds {
    /// Minimum x.
    pub min_x: f32,
    /// Minimum y.
    pub min_y: f32,
    /// Maximum x.
    pub max_x: f32,
    /// Maximum y.
    pub max_y: f32,
}

impl Bounds {
    /// Width in model units.
    pub fn width(&self) -> f32 {
        self.max_x - self.min_x
    }

    /// Height in model units.
    pub fn height(&self) -> f32 {
        self.max_y - self.min_y
    }

    /// Center x.
    pub fn center_x(&self) -> f32 {
        (self.min_x + self.max_x) * 0.5
    }

    /// Center y.
    pub fn center_y(&self) -> f32 {
        (self.min_y + self.max_y) * 0.5
    }

    /// Aspect ratio (width / height).
    pub fn aspect(&self) -> f32 {
        if self.height().abs() < 1e-6 {
            1.0
        } else {
            self.width() / self.height()
        }
    }
}

/// Reference bust height at 100% scale, before animation padding.
pub const BASE_LOGICAL_HEIGHT: f32 = 500.0;

/// Shared neutral face height at 100%, close to the original moc bust scale.
pub const BASE_FACE_HEIGHT: f32 = 120.0;

/// Static framing: animation never changes the model's apparent size.
#[derive(Debug, Clone, Copy)]
pub struct ModelLayout {
    /// Model-space viewport, including transparent room for arms and hair.
    pub viewport: Bounds,
    pixels_per_unit: f32,
}

impl ModelLayout {
    pub fn pixel(content: Bounds) -> Self {
        Self {
            viewport: content,
            pixels_per_unit: 1.0,
        }
    }

    pub fn crop_bottom(mut self, ratio: f32) -> Self {
        self.viewport.min_y =
            self.viewport.max_y - self.viewport.height() * ratio.clamp(0.625, 1.0);
        self
    }
    /// Uses the neutral face as a common ruler for bust and full-body models.
    /// Models without face metadata fall back to conventional format framing.
    pub fn new(content: Bounds, face_height: Option<f32>, format: ModelFormat) -> Self {
        let reference_height = face_height
            .filter(|height| height.is_finite() && *height > 1e-4)
            .map(|height| height * BASE_LOGICAL_HEIGHT / BASE_FACE_HEIGHT)
            .unwrap_or_else(|| {
                content.height()
                    * if format == ModelFormat::Moc3 {
                        0.65
                    } else {
                        1.0
                    }
            });
        let pad_x = reference_height * 0.35;
        let pad_y = reference_height * 0.15;
        Self {
            viewport: Bounds {
                min_x: content.min_x - pad_x,
                max_x: content.max_x + pad_x,
                min_y: content.min_y - pad_y,
                max_y: content.max_y + pad_y,
            },
            pixels_per_unit: BASE_LOGICAL_HEIGHT / reference_height,
        }
    }

    /// Physical size, keeping the same scale on both axes even at size limits.
    pub fn window_size(&self, scale_percent: f32, dpr: f64) -> (u32, u32) {
        let scale = (scale_percent / 100.0).clamp(0.25, 5.0) as f64 * dpr;
        let width = self.viewport.width() as f64 * self.pixels_per_unit as f64 * scale;
        let height = self.viewport.height() as f64 * self.pixels_per_unit as f64 * scale;
        let limit = (8192.0 / width.max(height)).min(1.0);
        (
            (width * limit).round().max(1.0) as u32,
            (height * limit).round().max(1.0) as u32,
        )
    }

    /// Uses the padded viewport for both rendering and inverse hit testing.
    pub fn matrix(&self, flip_y: bool) -> Matrix44 {
        fit_matrix(self.viewport, 1.0, flip_y)
    }
}

/// Computes the content AABB of a model's meshes.
pub fn content_size(meshes: &[Moc3DrawableMesh]) -> Option<Bounds> {
    let mut bounds: Option<Bounds> = None;
    for vertex in meshes.iter().flat_map(|mesh| mesh.vertices()) {
        let [x, y] = vertex.position();
        bounds = Some(match bounds {
            Some(current) => Bounds {
                min_x: current.min_x.min(x),
                min_y: current.min_y.min(y),
                max_x: current.max_x.max(x),
                max_y: current.max_y.max(y),
            },
            None => Bounds {
                min_x: x,
                min_y: y,
                max_x: x,
                max_y: y,
            },
        });
    }
    bounds.filter(|bounds| bounds.width() > 1e-4 && bounds.height() > 1e-4)
}

/// Builds the model → clip transform that fits `bounds` exactly into the window.
///
/// Desktop pets pass the padded viewport; static previews pass content bounds.
///
/// `flip_y` is **not** a preference: Cubism 2 model coordinates put the origin at
/// the top-left corner with y pointing down, while Cubism 3+ points y up. Neocari's
/// own `render_moc2` example compensates with `matrix.scale(scale_x, -scale_y)`,
/// and `moc2::layout` documents the same thing. Passing the wrong value renders the
/// character upside down (and drags its click regions along with it).
pub fn fit_matrix(bounds: Bounds, view_fill: f32, flip_y: bool) -> Matrix44 {
    let view_fill = view_fill.clamp(0.1, 4.0);
    let scale_x = 2.0 * view_fill / bounds.width();
    let scale_y = 2.0 * view_fill / bounds.height();
    let signed_scale_y = if flip_y { -scale_y } else { scale_y };
    let mut matrix = Matrix44::identity();
    matrix.scale(scale_x, signed_scale_y);
    matrix.translate(
        -bounds.center_x() * scale_x,
        -bounds.center_y() * signed_scale_y,
    );
    matrix
}

#[cfg(test)]
mod tests {
    use super::*;
    use neocari::moc3::Moc3DrawableVertex;

    fn quad(min: (f32, f32), max: (f32, f32)) -> Moc3DrawableMesh {
        Moc3DrawableMesh::from_parts(
            0,
            0,
            1.0,
            0.0,
            vec![
                Moc3DrawableVertex::new([min.0, max.1], [0.0, 0.0]),
                Moc3DrawableVertex::new([max.0, max.1], [1.0, 0.0]),
                Moc3DrawableVertex::new([max.0, min.1], [1.0, 1.0]),
                Moc3DrawableVertex::new([min.0, min.1], [0.0, 1.0]),
            ],
            vec![0, 1, 2, 0, 2, 3],
            Vec::new(),
        )
    }

    #[test]
    fn bounds_cover_every_vertex() {
        let meshes = vec![quad((-1.0, -1.5), (1.0, 1.5)), quad((0.0, 0.0), (0.5, 0.5))];
        let bounds = content_size(&meshes).unwrap();
        assert_eq!(bounds.min_y, -1.5);
        assert_eq!(bounds.max_x, 1.0);
    }

    #[test]
    fn padding_adds_room_without_shrinking_the_model() {
        let bounds = Bounds {
            min_x: -0.5,
            min_y: -0.75,
            max_x: 0.5,
            max_y: 0.75,
        };
        let layout = ModelLayout::new(bounds, None, ModelFormat::Moc);
        let (width, height) = layout.window_size(100.0, 1.0);
        assert_eq!(height, 650);
        assert!((width as f32 - (500.0 * bounds.aspect() + 350.0)).abs() < 1.0);
        let matrix = layout.matrix(false);
        let visible_height = (matrix.transform_y(bounds.max_y) - matrix.transform_y(bounds.min_y))
            * height as f32
            / 2.0;
        assert!((visible_height - 500.0).abs() < 0.01);
        let (scaled_width, scaled_height) = layout.window_size(200.0, 1.5);
        assert_eq!(scaled_height, 1950);
        assert!((scaled_width as f32 - width as f32 * 3.0).abs() <= 1.0);
    }

    #[test]
    fn default_zoom_applies_dpi_once_for_live2d_and_pixel_models() {
        let bounds = Bounds {
            min_x: -0.5,
            min_y: -1.0,
            max_x: 0.5,
            max_y: 1.0,
        };
        for layout in [
            ModelLayout::new(bounds, Some(0.4), ModelFormat::Moc),
            ModelLayout::new(bounds, Some(0.4), ModelFormat::Moc3),
            ModelLayout::pixel(bounds),
        ] {
            for config in [
                pet_config::Config::default(),
                pet_config::Config {
                    live2d_scale: 0,
                    ..Default::default()
                },
                pet_config::Config {
                    live2d_scale: 200,
                    ..Default::default()
                },
            ] {
                let (base_width, base_height) =
                    layout.window_size(config.effective_scale_percent(), 1.0);
                for dpr in [1.0, 1.25, 1.5, 2.0, 3.0] {
                    let (width, height) = layout.window_size(config.effective_scale_percent(), dpr);
                    assert!((width as f64 - base_width as f64 * dpr).abs() <= 1.0);
                    assert!((height as f64 - base_height as f64 * dpr).abs() <= 1.0);
                }
            }
        }
    }

    #[test]
    fn face_scale_matches_across_coordinate_systems_and_body_lengths() {
        for (bounds, face, format, flip_y) in [
            (
                Bounds {
                    min_x: 300.0,
                    min_y: 350.0,
                    max_x: 1700.0,
                    max_y: 2900.0,
                },
                600.0,
                ModelFormat::Moc,
                true,
            ),
            (
                Bounds {
                    min_x: -0.22,
                    min_y: -0.73,
                    max_x: 0.22,
                    max_y: 0.55,
                },
                0.2,
                ModelFormat::Moc3,
                false,
            ),
        ] {
            let layout = ModelLayout::new(bounds, Some(face), format);
            for (scale, dpr) in [(50.0, 1.0), (100.0, 1.5), (200.0, 2.0)] {
                let (width, height) = layout.window_size(scale, dpr);
                let matrix = layout.matrix(flip_y);
                let face_pixels = (matrix.transform_y(face) - matrix.transform_y(0.0)).abs()
                    * height as f32
                    / 2.0;
                assert!((face_pixels - BASE_FACE_HEIGHT * scale / 100.0 * dpr as f32).abs() < 0.5);
                let pixels_x =
                    (matrix.transform_x(face) - matrix.transform_x(0.0)).abs() * width as f32 / 2.0;
                assert!(
                    (face_pixels - pixels_x).abs() < 0.5,
                    "must preserve proportions"
                );
                assert!(matrix.transform_x(bounds.min_x) > -1.0);
                assert!(matrix.transform_x(bounds.max_x) < 1.0);
            }
        }
    }

    #[test]
    fn texture_limit_preserves_aspect_and_bad_face_metadata_uses_fallback() {
        let bounds = Bounds {
            min_x: -0.5,
            min_y: -1.0,
            max_x: 0.5,
            max_y: 1.0,
        };
        let fallback = ModelLayout::new(bounds, None, ModelFormat::Moc3);
        for face in [f32::NAN, f32::INFINITY, 0.0, -1.0] {
            let layout = ModelLayout::new(bounds, Some(face), ModelFormat::Moc3);
            assert_eq!(
                layout.window_size(100.0, 1.0),
                fallback.window_size(100.0, 1.0)
            );
        }
        let (width, height) = fallback.window_size(500.0, 4.0);
        assert_eq!(height, 8192);
        assert!((width as f32 / height as f32 - fallback.viewport.aspect()).abs() < 0.001);
    }

    #[test]
    fn flip_matrix_puts_model_down_y_at_the_bottom() {
        // Cubism 2 space: head at y = 0.2 (near the top-left origin), feet at y = 1.8.
        let bounds = Bounds {
            min_x: -1.0,
            min_y: 0.2,
            max_x: 1.0,
            max_y: 1.8,
        };
        let flipped = fit_matrix(bounds, 1.0, true);
        // Larger model y must map to a *lower* clip y when flipping.
        assert!(flipped.transform_y(1.8) < flipped.transform_y(0.2));
        assert!((flipped.transform_y(1.8) + 1.0).abs() < 1e-6);
        assert!((flipped.transform_y(0.2) - 1.0).abs() < 1e-6);
        let straight = fit_matrix(bounds, 1.0, false);
        assert!(straight.transform_y(1.8) > straight.transform_y(0.2));
    }

    #[test]
    fn fit_matrix_maps_content_to_full_clip_space() {
        let bounds = Bounds {
            min_x: -1.0,
            min_y: -2.0,
            max_x: 1.0,
            max_y: 2.0,
        };
        let matrix = fit_matrix(bounds, 1.0, false);
        // Corners map to the clip-space corners.
        assert!((matrix.transform_x(-1.0) + 1.0).abs() < 1e-6);
        assert!((matrix.transform_x(1.0) - 1.0).abs() < 1e-6);
        assert!((matrix.transform_y(-2.0) + 1.0).abs() < 1e-6);
        assert!((matrix.transform_y(2.0) - 1.0).abs() < 1e-6);
        // Inverse round trip.
        let x = matrix.invert_transform_x(0.25);
        assert!((matrix.transform_x(x) - 0.25).abs() < 1e-6);
    }
}
