//! Smooth body transitions and restrained facial performance for desktop use.
use crate::{number, Transform};
use serde_json::Value;
use std::collections::BTreeMap;

pub(crate) struct Transition {
    pub from: Vec<Transform>,
    pub started: f32,
    pub duration: f32,
}
pub(crate) struct MotionProfile {
    pub looping: bool,
    pub speed: f32,
    pub fade: f32,
    pub expression: &'static str,
    pub strength: f32,
}
impl MotionProfile {
    pub fn new(name: &str, settings: &Value) -> Self {
        let (expression, strength) = match name {
            "Wave" => ("happy", 0.38),
            "Blush" => ("happy", 0.28),
            "Relax" => ("relaxed", 0.18),
            "LookAround" => ("relaxed", 0.10),
            "Thinking" => ("relaxed", 0.06),
            _ => ("relaxed", 0.10),
        };
        Self {
            looping: settings["loop"].as_bool().unwrap_or(name == "Idle"),
            speed: number(&settings["speed"], if name == "Idle" { 0.85 } else { 0.9 })
                .clamp(0.25, 2.),
            fade: number(&settings["fade"], 0.55).clamp(0.15, 2.),
            expression,
            strength: number(&settings["expression_strength"], strength).clamp(0., 1.),
        }
    }
}
pub(crate) fn canonical_expression(name: &str) -> &str {
    match name {
        "joy" | "happy" => "happy",
        "fun" | "relaxed" => "relaxed",
        "sorrow" | "sad" => "sad",
        "a" | "aa" => "aa",
        "i" | "ih" => "ih",
        "u" | "ou" => "ou",
        "e" | "ee" => "ee",
        "o" | "oh" => "oh",
        _ => name,
    }
}
pub(crate) struct Face {
    pub weights: BTreeMap<String, f32>,
    pub explicit: Option<String>,
    strengths: BTreeMap<String, f32>,
    elapsed: f32,
    next_blink: f32,
    blink_started: Option<f32>,
    blink_index: u32,
    pub blink: f32,
    mouth: f32,
    drag: [f32; 2],
}
impl Face {
    pub fn new(settings: &Value) -> Self {
        let strengths = settings["expression_strengths"]
            .as_object()
            .into_iter()
            .flatten()
            .map(|(name, v)| (name.clone(), number(v, 0.65).clamp(0., 1.)))
            .collect();
        Self {
            weights: BTreeMap::new(),
            explicit: None,
            strengths,
            elapsed: 0.,
            next_blink: 2.8,
            blink_started: None,
            blink_index: 0,
            blink: 0.,
            mouth: 0.,
            drag: [0.; 2],
        }
    }
    pub fn update(
        &mut self,
        dt: f32,
        names: &[String],
        ambient: (&str, f32),
        blink_enabled: bool,
        mouth: f32,
        drag: [f32; 2],
    ) {
        self.elapsed += dt;
        if blink_enabled && self.elapsed >= self.next_blink && self.blink_started.is_none() {
            self.blink_started = Some(self.elapsed);
            self.blink_index += 1;
            // Varied intervals and occasional follow-up blink, deterministic for replay.
            let interval = if self.blink_index.is_multiple_of(5) {
                0.38
            } else {
                3.1 + (self.blink_index as f32 * 2.39996).sin().abs() * 2.4
            };
            self.next_blink = self.elapsed + interval;
        }
        self.blink = if blink_enabled {
            self.blink_started
                .map(|start| {
                    let t = self.elapsed - start;
                    if t < 0.065 {
                        crate::smoothstep(t / 0.065)
                    } else {
                        1. - crate::smoothstep((t - 0.065) / 0.13)
                    }
                })
                .unwrap_or(0.)
        } else {
            0.
        };
        if self
            .blink_started
            .is_some_and(|t| self.elapsed - t >= 0.195)
        {
            self.blink_started = None;
        }
        self.mouth += (mouth - self.mouth) * (1. - (-dt / 0.055).exp());
        for (smoothed, target) in self.drag.iter_mut().zip(drag) {
            *smoothed += (target - *smoothed) * (1. - (-dt / 0.18).exp());
        }
        let blend = 1. - (-dt / 0.14).exp();
        for name in names {
            let canonical = canonical_expression(name);
            let target = if let Some(explicit) = &self.explicit {
                if explicit == name {
                    self.strengths.get(name).copied().unwrap_or(
                        if ["aa", "ih", "ou", "ee", "oh", "blink"].contains(&canonical) {
                            1.
                        } else {
                            0.65
                        },
                    )
                } else {
                    0.
                }
            } else if canonical == ambient.0 {
                ambient.1
            } else {
                0.
            };
            let weight = self.weights.entry(name.clone()).or_default();
            *weight += (target - *weight) * blend;
        }
    }
    pub fn weight(&self, name: &str) -> f32 {
        let base = self.weights.get(name).copied().unwrap_or(0.);
        match canonical_expression(name) {
            "blink" => base.max(self.blink),
            "aa" => base.max(self.mouth),
            _ => base,
        }
    }
    pub fn drag(&self) -> [f32; 2] {
        self.drag
    }
    pub fn explicit_count(&self) -> usize {
        self.weights.values().filter(|&&w| w > 0.001).count()
    }
}
