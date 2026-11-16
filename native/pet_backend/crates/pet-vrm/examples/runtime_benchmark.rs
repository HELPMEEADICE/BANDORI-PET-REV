//! CPU-only VRM update benchmark, including allocator traffic and retained heap.
//! cargo run --release -p pet-vrm --example runtime_benchmark -- MODEL.vrm [FRAMES]
use pet_vrm::VrmModel;
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering::Relaxed};
use std::time::Instant;

struct CountingAllocator;
static LIVE: AtomicUsize = AtomicUsize::new(0);
static PEAK: AtomicUsize = AtomicUsize::new(0);
static ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);

fn allocated(bytes: usize) {
    let live = LIVE.fetch_add(bytes, Relaxed) + bytes;
    PEAK.fetch_max(live, Relaxed);
    ALLOCATIONS.fetch_add(1, Relaxed);
}

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let ptr = unsafe { System.alloc(layout) };
        if !ptr.is_null() {
            allocated(layout.size());
        }
        ptr
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        LIVE.fetch_sub(layout.size(), Relaxed);
        unsafe { System.dealloc(ptr, layout) };
    }

    unsafe fn realloc(&self, ptr: *mut u8, old: Layout, size: usize) -> *mut u8 {
        let result = unsafe { System.realloc(ptr, old, size) };
        if !result.is_null() {
            LIVE.fetch_sub(old.size(), Relaxed);
            allocated(size);
        }
        result
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let path = args
        .next()
        .ok_or("usage: runtime_benchmark MODEL.vrm [FRAMES]")?;
    let frames: usize = args.next().map(|s| s.parse()).transpose()?.unwrap_or(600);
    if frames == 0 {
        return Err("FRAMES must be positive".into());
    }
    let mut model = VrmModel::load(std::path::Path::new(&path))?;
    // Production releases decoded RGBA after upload. This benchmark excludes
    // GPU resources and alpha textures and measures the animation model only.
    model.textures.clear();
    for _ in 0..120 {
        assert!(model.update(1. / 60.));
    }
    let mut timings = Vec::with_capacity(frames);
    let retained = LIVE.load(Relaxed);
    PEAK.store(retained, Relaxed);
    let allocations = ALLOCATIONS.load(Relaxed);
    for frame in 0..frames {
        model.set_drag((frame as f32 * 0.03).sin() * 0.5, 0.);
        let start = Instant::now();
        assert!(model.update(1. / 60.));
        timings.push(start.elapsed().as_secs_f64() * 1000.);
    }
    let allocations = ALLOCATIONS.load(Relaxed) - allocations;
    let peak = PEAK.load(Relaxed);
    timings.sort_by(f64::total_cmp);
    println!(
        "{}",
        serde_json::json!({
            "model": path,
            "frames": frames,
            "vertices": model.primitives.iter().map(|p| p.vertices.len()).sum::<usize>(),
            "hit_vertices": model.projected.iter().map(|p| p.vertices().len()).sum::<usize>(),
            "update_median_ms": timings[frames / 2],
            "update_p95_ms": timings[(frames - 1) * 95 / 100],
            "allocations_per_frame": allocations as f64 / frames as f64,
            "retained_model_heap_bytes": retained,
            "peak_update_heap_bytes": peak,
            "scope": "CPU animation model only; excludes GPU, alpha textures and process RSS",
        })
    );
    Ok(())
}
