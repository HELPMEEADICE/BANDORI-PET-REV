//! Hit testing and click-动作 resolution.
//!
//! * [`hit`] — pure-CPU hit testing: screen space → model space → triangle coverage
//!   → texture alpha sample. No GPU readback, so it can run on the interaction
//!   thread from a published [`hit::FrameSnapshot`] (spec §2.4).
//! * [`region`] — the seven-region coordinate classification (spec §2.6).
//! * [`matching`] — the four-level motion-name matching, the tag→expression table,
//!   the AUTOMATIC buckets and preset expansion (spec §2.6).

pub mod hit;
pub mod matching;
pub mod region;

pub use hit::{FrameSnapshot, HitDrawable, HitResult, HitVertex};
pub use matching::{
    choose_auto_motion, expression_candidates, resolve_click_action, resolve_expression_by_tag,
    resolve_motion_by_tag, resolve_preset,
};
pub use region::{classify_region, region_for_point, Bounds, HEAD_MAX_Y_RATIO, UPPER_MAX_Y_RATIO};
