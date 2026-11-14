//! Non-graphical service entry point. COM never leaves this sampling thread.
use std::io::{self, Read, Write};
use std::path::Path;
use std::sync::mpsc;
use std::time::{Duration, Instant};

use pet_ipc::level::{timestamp_ms, LevelPublisher};

/// Owns recovery cadence independently of audio API and sampling cadence.
struct RecoveringMeter<M> {
    meter: Option<M>,
    retry_at: Instant,
    reported: bool,
}

impl<M> RecoveringMeter<M> {
    fn new() -> Self {
        Self {
            meter: None,
            retry_at: Instant::now(),
            reported: false,
        }
    }

    fn sample<E: std::fmt::Display>(
        &mut self,
        now: Instant,
        create: impl FnOnce() -> Result<M, E>,
        read: impl FnOnce(&mut M) -> Result<f32, E>,
    ) -> f32 {
        if self.meter.is_none() && now < self.retry_at {
            return 0.0;
        }
        let result = (|| {
            if self.meter.is_none() {
                self.meter = Some(create()?);
            }
            read(self.meter.as_mut().expect("created meter"))
        })();
        match result {
            Ok(peak) => {
                self.reported = false;
                if peak.is_finite() {
                    peak.clamp(0.0, 1.0)
                } else {
                    0.0
                }
            }
            Err(error) => {
                // Drop interfaces and COM apartment on their owning thread.
                self.meter = None;
                self.retry_at = now + Duration::from_secs(1);
                if !self.reported {
                    eprintln!("Music bounce output meter unavailable; retrying: {error}");
                    self.reported = true;
                }
                0.0
            }
        }
    }
}

pub fn run(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    // Only the read-only endpoint peak is queried. No WASAPI stream is opened.
    let mut publisher = LevelPublisher::create(path)?;
    let (stop, stopped) = mpsc::channel();
    std::thread::Builder::new()
        .name("music-lifetime".into())
        .spawn(move || {
            let mut byte = [0];
            // A stop byte or parent pipe EOF both revoke this service's lifetime.
            let _ = io::stdin().read(&mut byte);
            let _ = stop.send(());
        })?;
    println!("READY");
    io::stdout().flush()?;
    let mut meter = RecoveringMeter::new();
    let interval = Duration::from_secs_f64(1.0 / 60.0);
    loop {
        let start = Instant::now();
        if stopped.try_recv().is_ok() {
            break;
        }
        let peak = meter.sample(start, platform::Meter::new, platform::Meter::read);
        publisher.publish(peak, timestamp_ms())?;
        match stopped.recv_timeout(interval.saturating_sub(start.elapsed())) {
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            _ => break,
        }
    }
    publisher.publish(0.0, timestamp_ms())?;
    Ok(())
}

#[cfg(windows)]
mod platform {
    use std::marker::PhantomData;
    use std::rc::Rc;
    use std::time::{Duration, Instant};
    use windows::Win32::Media::Audio::Endpoints::IAudioMeterInformation;
    use windows::Win32::Media::Audio::{
        eMultimedia, eRender, IMMDeviceEnumerator, MMDeviceEnumerator,
    };
    use windows::Win32::System::Com::{
        CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_ALL, CLSCTX_INPROC_SERVER,
        COINIT_MULTITHREADED,
    };

    struct Apartment(PhantomData<Rc<()>>);
    impl Drop for Apartment {
        fn drop(&mut self) {
            unsafe {
                CoUninitialize();
            }
        }
    }

    pub struct Meter {
        // Fields drop in declaration order: interfaces before apartment.
        meter: IAudioMeterInformation,
        enumerator: IMMDeviceEnumerator,
        refresh_at: Instant,
        _apartment: Apartment,
    }

    impl Meter {
        pub fn new() -> windows::core::Result<Self> {
            unsafe {
                CoInitializeEx(None, COINIT_MULTITHREADED).ok()?;
                let apartment = Apartment(PhantomData);
                let enumerator: IMMDeviceEnumerator =
                    CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_INPROC_SERVER)?;
                let meter = Self::bind(&enumerator)?;
                Ok(Self {
                    meter,
                    enumerator,
                    refresh_at: Instant::now() + Duration::from_secs(2),
                    _apartment: apartment,
                })
            }
        }

        fn bind(enumerator: &IMMDeviceEnumerator) -> windows::core::Result<IAudioMeterInformation> {
            unsafe {
                let device = enumerator.GetDefaultAudioEndpoint(eRender, eMultimedia)?;
                device.Activate(CLSCTX_ALL, None)
            }
        }

        pub fn read(&mut self) -> windows::core::Result<f32> {
            // Same 2 s rebind policy as the Python baseline, including switches
            // where the previous default endpoint remains connected.
            if Instant::now() >= self.refresh_at {
                self.meter = Self::bind(&self.enumerator)?;
                self.refresh_at = Instant::now() + Duration::from_secs(2);
            }
            unsafe { self.meter.GetPeakValue() }
        }
    }
}

#[cfg(not(windows))]
mod platform {
    pub struct Meter;
    impl Meter {
        pub fn new() -> std::io::Result<Self> {
            Err(std::io::Error::new(
                std::io::ErrorKind::Unsupported,
                "system output metering is supported only on Windows",
            ))
        }
        pub fn read(&mut self) -> std::io::Result<f32> {
            Ok(0.0)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;
    #[test]
    fn device_failure_releases_retries_then_recovers() {
        struct Meter<'a>(&'a Cell<usize>);
        impl Drop for Meter<'_> {
            fn drop(&mut self) {
                self.0.set(self.0.get() + 1);
            }
        }
        let dropped = Cell::new(0);
        let mut meter = RecoveringMeter::new();
        let now = Instant::now();
        assert_eq!(
            meter.sample(now, || Ok(Meter(&dropped)), |_| Err("disconnected")),
            0.0
        );
        assert_eq!(dropped.get(), 1);
        assert_eq!(
            meter.sample(
                now,
                || -> Result<_, &str> { panic!("retry too soon") },
                |_| Ok(0.8)
            ),
            0.0
        );
        assert_eq!(
            meter.sample(
                now + Duration::from_secs(1),
                || Ok(Meter(&dropped)),
                |_| Ok::<_, &str>(0.8)
            ),
            0.8
        );
        drop(meter);
        assert_eq!(dropped.get(), 2);
    }
}
