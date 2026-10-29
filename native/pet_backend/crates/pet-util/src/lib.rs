//! Small helpers shared by the pet, the renderer and the behavior state machine.

pub mod rng;
pub mod time_of_day;

pub use rng::Rng;

/// Linear interpolation.
pub fn lerp(from: f32, to: f32, weight: f32) -> f32 {
    from + (to - from) * weight
}

/// Clamps to `0.0..=1.0`.
pub fn clamp01(value: f32) -> f32 {
    value.clamp(0.0, 1.0)
}

/// Smoothstep easing on `0.0..=1.0`.
pub fn smoothstep(value: f32) -> f32 {
    let value = clamp01(value);
    value * value * (3.0 - 2.0 * value)
}

/// Ease-in-out cubic.
pub fn ease_in_out(value: f32) -> f32 {
    let value = clamp01(value);
    if value < 0.5 {
        4.0 * value * value * value
    } else {
        1.0 - (-2.0 * value + 2.0).powi(3) / 2.0
    }
}

/// Maps `value` from `in_range` to `out_range`, clamping to the input range.
pub fn remap(value: f32, in_range: (f32, f32), out_range: (f32, f32)) -> f32 {
    let (in_min, in_max) = in_range;
    if (in_max - in_min).abs() < f32::EPSILON {
        return out_range.0;
    }
    let clamped = value.clamp(in_min.min(in_max), in_min.max(in_max));
    let weight = (clamped - in_min) / (in_max - in_min);
    out_range.0 + (out_range.1 - out_range.0) * weight
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn remap_and_easing_behave() {
        assert!((remap(0.5, (0.0, 1.0), (0.0, 10.0)) - 5.0).abs() < 1e-6);
        assert!((remap(2.0, (0.0, 1.0), (0.0, 10.0)) - 10.0).abs() < 1e-6);
        assert!((smoothstep(0.5) - 0.5).abs() < 1e-6);
        assert!((ease_in_out(0.0) - 0.0).abs() < 1e-6);
        assert!((ease_in_out(1.0) - 1.0).abs() < 1e-6);
    }
}
