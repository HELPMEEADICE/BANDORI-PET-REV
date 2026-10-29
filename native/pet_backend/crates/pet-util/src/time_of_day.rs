//! Local time-of-day buckets used to pick idle/random motion tags, plus the
//! idle-escalation durations from spec §2.7 (daze after 7 min, sleep after 18 min).

use std::time::{SystemTime, UNIX_EPOCH};

/// Coarse local day phase.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum DayPhase {
    /// 05:00–10:59 — morning greetings.
    Morning,
    /// 11:00–17:59 — daytime.
    Day,
    /// 18:00–22:59 — evening.
    Evening,
    /// 23:00–04:59 — night.
    Night,
}

impl DayPhase {
    /// Bucket for a local hour (0–23).
    pub fn from_hour(hour: u32) -> Self {
        match hour {
            5..=10 => DayPhase::Morning,
            11..=17 => DayPhase::Day,
            18..=22 => DayPhase::Evening,
            _ => DayPhase::Night,
        }
    }

    /// Motion-tag pool used by random/idle actions for this phase.
    ///
    /// These are base tags, not file names: the tag matcher (spec §2.6) expands
    /// `smile` to `smile01..smile03` for `.moc` packs and to `mtn_smile01_C/L/R`
    /// for `.moc3` packs, exactly like the original client.
    pub fn motion_tags(self) -> &'static [&'static str] {
        match self {
            DayPhase::Morning => &["stretch", "akubi", "sigh", "smile", "kime"],
            DayPhase::Day => &["smile", "wink", "nod", "kime"],
            DayPhase::Evening => &["smile", "nod", "sad", "nf"],
            DayPhase::Night => &["sleep", "akubi", "sad", "nod"],
        }
    }

    /// Config-independent display name for logs.
    pub fn key(self) -> &'static str {
        match self {
            DayPhase::Morning => "morning",
            DayPhase::Day => "day",
            DayPhase::Evening => "evening",
            DayPhase::Night => "night",
        }
    }
}

/// How long the role has been without user interaction.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IdleTier {
    /// Normal idle loops.
    Awake,
    /// After 7 minutes: slower, spaced-out motions.
    Daze,
    /// After 18 minutes: sleep motions only.
    Sleep,
}

impl IdleTier {
    /// Seconds of inactivity before this tier starts.
    pub const DAZE_AFTER_SECS: f64 = 7.0 * 60.0;
    /// Seconds of inactivity before the sleep tier.
    pub const SLEEP_AFTER_SECS: f64 = 18.0 * 60.0;

    /// Classifies an inactivity duration.
    pub fn from_idle_secs(idle_secs: f64) -> Self {
        if idle_secs >= Self::SLEEP_AFTER_SECS {
            IdleTier::Sleep
        } else if idle_secs >= Self::DAZE_AFTER_SECS {
            IdleTier::Daze
        } else {
            IdleTier::Awake
        }
    }

    /// Random-motion interval multiplier for this tier.
    pub fn motion_interval_scale(self) -> f64 {
        match self {
            IdleTier::Awake => 1.0,
            IdleTier::Daze => 2.5,
            IdleTier::Sleep => 4.0,
        }
    }
}

/// Current local hour, derived without pulling in a date/time crate.
pub fn local_hour() -> u32 {
    if let Ok(hour) = std::env::var("BANDORI_PET_HOUR") {
        if let Ok(hour) = hour.parse::<u32>() {
            return hour % 24;
        }
    }
    #[cfg(unix)]
    if std::env::var_os("BANDORI_PET_UTC_OFFSET").is_none() {
        let timestamp = unsafe { libc::time(std::ptr::null_mut()) };
        let mut local = std::mem::MaybeUninit::<libc::tm>::uninit();
        // localtime_r reads the system timezone, including DST and fractional
        // offsets, without sharing libc's global `tm` buffer across threads.
        if !unsafe { libc::localtime_r(&timestamp, local.as_mut_ptr()) }.is_null() {
            return unsafe { local.assume_init() }.tm_hour as u32;
        }
    }
    let utc_secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    local_hour_from_utc_secs(utc_secs, utc_offset_hours())
}

/// Current local phase.
pub fn current_phase() -> DayPhase {
    DayPhase::from_hour(local_hour())
}

/// Converts UTC seconds to a local hour with an explicit offset.
pub fn local_hour_from_utc_secs(utc_secs: u64, offset_hours: i64) -> u32 {
    let seconds = utc_secs as i64 + offset_hours * 3600;
    let day_position = seconds.rem_euclid(86_400);
    (day_position / 3600) as u32
}

/// Local UTC offset in whole hours.
///
/// Windows stores the offset in the `TimeZoneKeyName`; asking the OS from a
/// library crate keeps this dependency-free. `BANDORI_PET_UTC_OFFSET` wins so the
/// tests can pin a value.
fn utc_offset_hours() -> i64 {
    if let Ok(offset) = std::env::var("BANDORI_PET_UTC_OFFSET") {
        if let Ok(offset) = offset.parse::<i64>() {
            return offset;
        }
    }
    #[cfg(windows)]
    {
        if let Some(offset) = windows_offset_hours() {
            return offset;
        }
    }
    8
}

#[cfg(windows)]
fn windows_offset_hours() -> Option<i64> {
    // `GetTimeZoneInformation` reports the bias in minutes; `windows` is a
    // pet-window dependency, so this crate keeps the simple fallback instead of
    // pulling the crate in. BANDORI_PET_UTC_OFFSET covers unusual zones.
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn phases_partition_the_day() {
        assert_eq!(DayPhase::from_hour(6), DayPhase::Morning);
        assert_eq!(DayPhase::from_hour(12), DayPhase::Day);
        assert_eq!(DayPhase::from_hour(20), DayPhase::Evening);
        assert_eq!(DayPhase::from_hour(2), DayPhase::Night);
        for hour in 0..24 {
            assert!(!DayPhase::from_hour(hour).motion_tags().is_empty());
        }
    }

    #[test]
    fn idle_tiers_follow_spec_thresholds() {
        assert_eq!(IdleTier::from_idle_secs(60.0), IdleTier::Awake);
        assert_eq!(IdleTier::from_idle_secs(7.0 * 60.0), IdleTier::Daze);
        assert_eq!(IdleTier::from_idle_secs(18.0 * 60.0), IdleTier::Sleep);
    }

    #[test]
    fn utc_conversion_handles_offsets() {
        // 1970-01-01T00:00:00Z with +8 → 08:00 local.
        assert_eq!(local_hour_from_utc_secs(0, 8), 8);
        // 1970-01-01T23:00:00Z with +8 → next day 07:00 local.
        assert_eq!(local_hour_from_utc_secs(23 * 3600, 8), 7);
        // Negative offsets wrap backwards.
        assert_eq!(local_hour_from_utc_secs(3600, -2), 23);
    }
}
