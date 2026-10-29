//! Seven-region classification (spec §2.6, extracted verbatim in
//! `BANDORI-PET-REV-behavior-spec.md` §2).
//!
//! The Python original works in widget pixels with an optional hit-area bounding
//! box. LITE keeps the same ratios but normalizes against the model content box,
//! which makes the classification independent of window size and DPI.

use pet_config::{ClickRegion, CLICK_REGIONS};

/// `y_ratio` below this value inside an unnamed/body hit area counts as the head.
pub const HEAD_MAX_Y_RATIO: f32 = 0.38;
/// Vertical split between upper and lower body (`y_ratio < 0.64` is upper body).
pub const UPPER_MAX_Y_RATIO: f32 = 0.64;
/// `x_ratio` below this value is the left column.
pub const LEFT_MAX_X_RATIO: f32 = 0.38;
/// `x_ratio` above this value is the right column.
pub const RIGHT_MIN_X_RATIO: f32 = 0.62;

/// A model-space axis-aligned bounding box.
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
    /// Builds a box from two corners (any order).
    pub fn from_corners(a: (f32, f32), b: (f32, f32)) -> Self {
        Self {
            min_x: a.0.min(b.0),
            min_y: a.1.min(b.1),
            max_x: a.0.max(b.0),
            max_y: a.1.max(b.1),
        }
    }

    /// Width.
    pub fn width(&self) -> f32 {
        self.max_x - self.min_x
    }

    /// Height.
    pub fn height(&self) -> f32 {
        self.max_y - self.min_y
    }

    /// `true` when the box is large enough to be used for ratio normalization.
    pub fn is_usable(&self) -> bool {
        self.width() > 1e-4 && self.height() > 1e-4
    }
}

/// Normalizes a model-space point inside `bounds` to `0.0..=1.0` ratios.
pub fn ratios_for_point(point: (f32, f32), bounds: Option<Bounds>) -> (f32, f32) {
    match bounds.filter(Bounds::is_usable) {
        Some(bounds) => (
            ((point.0 - bounds.min_x) / bounds.width()).clamp(0.0, 1.0),
            // Model space is y-up, UI ratios are y-down.
            (1.0 - (point.1 - bounds.min_y) / bounds.height()).clamp(0.0, 1.0),
        ),
        None => (0.5, 0.5),
    }
}

/// Classifies normalized ratios into one of the seven regions.
///
/// * `area_name` is the (already lower-cased) hit-area name from the model, or
///   empty for `.moc3` assets which ship no hit areas.
/// * Mirrors `click_motion_region_for_point` exactly: head/face short-circuits,
///   unnamed areas above `0.38` count as the head, then the `0.64` / `0.38` /
///   `0.62` splits.
pub fn classify_region(x_ratio: f32, y_ratio: f32, area_name: &str) -> ClickRegion {
    let x_ratio = x_ratio.clamp(0.0, 1.0);
    let y_ratio = y_ratio.clamp(0.0, 1.0);
    let area = area_name.trim().to_ascii_lowercase();

    if area == "head" || area == "face" {
        return ClickRegion::Head;
    }
    if matches!(area.as_str(), "" | "body" | "hit") && y_ratio < HEAD_MAX_Y_RATIO {
        return ClickRegion::Head;
    }

    let upper = y_ratio < UPPER_MAX_Y_RATIO;
    let horizontal = if x_ratio < LEFT_MAX_X_RATIO {
        0
    } else if x_ratio > RIGHT_MIN_X_RATIO {
        2
    } else {
        1
    };
    let key_index = (if upper { 1 } else { 4 }) + horizontal;
    // `CLICK_REGIONS` is ordered head, upper_left, upper_center, upper_right,
    // lower_left, lower_center, lower_right; the head entry (index 0) is handled above.
    CLICK_REGIONS
        .get(key_index)
        .copied()
        .unwrap_or(ClickRegion::UpperBodyCenter)
}

/// Convenience wrapper: classify a model-space point with optional bounds.
pub fn region_for_point(point: (f32, f32), bounds: Option<Bounds>, area_name: &str) -> ClickRegion {
    let (x_ratio, y_ratio) = ratios_for_point(point, bounds);
    classify_region(x_ratio, y_ratio, area_name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn head_area_wins_unconditionally() {
        assert_eq!(classify_region(0.9, 0.9, "head"), ClickRegion::Head);
        assert_eq!(classify_region(0.1, 0.95, "FACE"), ClickRegion::Head);
    }

    #[test]
    fn unnamed_top_band_is_head() {
        assert_eq!(classify_region(0.5, 0.2, ""), ClickRegion::Head);
        assert_eq!(classify_region(0.5, 0.2, "body"), ClickRegion::Head);
        // Named non-body areas are not promoted to head.
        assert_eq!(
            classify_region(0.5, 0.2, "arm"),
            ClickRegion::UpperBodyCenter
        );
    }

    #[test]
    fn body_grid_matches_python_thresholds() {
        assert_eq!(
            classify_region(0.1, 0.5, "body"),
            ClickRegion::UpperBodyLeft
        );
        assert_eq!(
            classify_region(0.5, 0.5, "body"),
            ClickRegion::UpperBodyCenter
        );
        assert_eq!(
            classify_region(0.9, 0.5, "body"),
            ClickRegion::UpperBodyRight
        );
        assert_eq!(
            classify_region(0.1, 0.8, "body"),
            ClickRegion::LowerBodyLeft
        );
        assert_eq!(
            classify_region(0.5, 0.8, "body"),
            ClickRegion::LowerBodyCenter
        );
        assert_eq!(
            classify_region(0.9, 0.8, "body"),
            ClickRegion::LowerBodyRight
        );
        // 0.62 itself is still center (strict >).
        assert_eq!(
            classify_region(0.62, 0.5, "body"),
            ClickRegion::UpperBodyCenter
        );
        // 0.64 itself is lower body (strict <).
        assert_eq!(
            classify_region(0.5, 0.64, "body"),
            ClickRegion::LowerBodyCenter
        );
    }

    #[test]
    fn point_ratios_are_y_flipped() {
        let bounds = Bounds::from_corners((-1.0, -1.0), (1.0, 1.0));
        let (x, y) = ratios_for_point((0.0, 0.8), Some(bounds));
        assert!((x - 0.5).abs() < 1e-6);
        assert!((y - 0.1).abs() < 1e-6, "top of the model is y≈0: {y}");
        assert_eq!(
            region_for_point((0.0, 0.8), Some(bounds), ""),
            ClickRegion::Head
        );
    }

    #[test]
    fn degenerate_bounds_fall_back_to_center() {
        let bounds = Bounds::from_corners((0.0, 0.0), (0.0, 0.0));
        assert_eq!(ratios_for_point((5.0, 5.0), Some(bounds)), (0.5, 0.5));
    }
}
