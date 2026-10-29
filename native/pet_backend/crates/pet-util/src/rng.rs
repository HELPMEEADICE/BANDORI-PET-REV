//! A tiny xorshift64* generator.
//!
//! The spec needs randomness for idle/random motion tags, blink timing, name
//! matching candidates and window displacement. A 20-line generator keeps the
//! dependency list short and makes behavior reproducible in tests.

/// xorshift64* pseudo random generator.
#[derive(Debug, Clone)]
pub struct Rng {
    state: u64,
}

impl Rng {
    /// Creates a generator with an explicit seed (0 is remapped to a constant).
    pub fn seeded(seed: u64) -> Self {
        Self {
            state: if seed == 0 {
                0x9e37_79b9_7f4a_7c15
            } else {
                seed
            },
        }
    }

    /// Creates a generator seeded from the wall clock and the address of a fresh
    /// allocation, which is enough entropy for a desktop pet.
    pub fn from_entropy() -> Self {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_nanos() as u64)
            .unwrap_or(0x1234_5678);
        let local = 0u8;
        let address = std::ptr::from_ref(&local) as usize as u64;
        Self::seeded(nanos ^ address.rotate_left(17) ^ 0xa5a5_5a5a_dead_beef)
    }

    /// Next 64-bit value.
    pub fn next_u64(&mut self) -> u64 {
        let mut state = self.state;
        state ^= state >> 12;
        state ^= state << 25;
        state ^= state >> 27;
        self.state = state;
        state.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    /// Uniform value in `0.0..1.0`.
    pub fn next_f32(&mut self) -> f32 {
        (self.next_u64() >> 40) as f32 / (1u64 << 24) as f32
    }

    /// Uniform value in `low..=high` (inclusive). Returns `low` when the range is empty.
    pub fn range_i64(&mut self, low: i64, high: i64) -> i64 {
        if high <= low {
            return low;
        }
        let span = (high - low + 1) as u64;
        low + (self.next_u64() % span) as i64
    }

    /// Uniform float in `low..high`.
    pub fn range_f32(&mut self, low: f32, high: f32) -> f32 {
        if high <= low {
            return low;
        }
        low + (high - low) * self.next_f32()
    }

    /// `true` with probability `probability`.
    pub fn chance(&mut self, probability: f32) -> bool {
        self.next_f32() < probability.clamp(0.0, 1.0)
    }

    /// Picks one element, or `None` for an empty slice.
    pub fn pick<'a, T>(&mut self, items: &'a [T]) -> Option<&'a T> {
        if items.is_empty() {
            return None;
        }
        let index = (self.next_u64() % items.len() as u64) as usize;
        items.get(index)
    }

    /// Picks one element by weight (`(item, weight)` pairs); falls back to the
    /// first item when every weight is zero.
    pub fn pick_weighted<'a, T>(&mut self, items: &'a [(T, f32)]) -> Option<&'a T> {
        let total: f32 = items.iter().map(|(_, weight)| weight.max(0.0)).sum();
        if items.is_empty() || total <= f32::EPSILON {
            return items.first().map(|(item, _)| item);
        }
        let mut target = self.next_f32() * total;
        for (item, weight) in items {
            target -= weight.max(0.0);
            if target <= 0.0 {
                return Some(item);
            }
        }
        items.last().map(|(item, _)| item)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sequence_is_deterministic_for_a_seed() {
        let mut left = Rng::seeded(42);
        let mut right = Rng::seeded(42);
        for _ in 0..16 {
            assert_eq!(left.next_u64(), right.next_u64());
        }
    }

    #[test]
    fn floats_stay_in_unit_range() {
        let mut rng = Rng::seeded(7);
        for _ in 0..1000 {
            let value = rng.next_f32();
            assert!((0.0..1.0).contains(&value), "{value}");
        }
    }

    #[test]
    fn picks_cover_every_element() {
        let mut rng = Rng::seeded(99);
        let items = [1u8, 2, 3];
        let mut seen = [false; 3];
        for _ in 0..200 {
            let value = *rng.pick(&items).unwrap();
            seen[(value - 1) as usize] = true;
        }
        assert_eq!(seen, [true, true, true]);
    }

    #[test]
    fn weighted_pick_respects_zero_weights() {
        let mut rng = Rng::seeded(5);
        let items = [("never", 0.0f32), ("always", 1.0)];
        for _ in 0..50 {
            assert_eq!(*rng.pick_weighted(&items).unwrap(), "always");
        }
    }
}
