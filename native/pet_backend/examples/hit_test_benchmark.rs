//! CPU-only comparison of snapshot and borrowed hit testing on real models.
//! cargo run --release --example hit_test_benchmark -- MODEL [ITERATIONS]
//! Accepts archive::member paths, .webp, .moc/.moc3 manifests and .vrm.
use std::alloc::{GlobalAlloc, Layout, System};
use std::error::Error;
use std::hint::black_box;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Instant;

use pet_assets::ModelCache;
use pet_input::hit::{hit_test_meshes, AlphaTexture, FrameSnapshot};
use pet_live2d::ModelHandle;
use pet_window::sizing::{content_size, upper_body_bounds, ModelLayout};

struct CountingAllocator;
static ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);
static ALLOCATED_BYTES: AtomicUsize = AtomicUsize::new(0);

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        ALLOCATED_BYTES.fetch_add(layout.size(), Ordering::Relaxed);
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        ALLOCATED_BYTES.fetch_add(size, Ordering::Relaxed);
        unsafe { System.realloc(ptr, layout, size) }
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

fn measure(iterations: usize, mut run: impl FnMut(usize) -> bool) -> (f64, usize, usize, usize) {
    let allocations = ALLOCATIONS.load(Ordering::Relaxed);
    let bytes = ALLOCATED_BYTES.load(Ordering::Relaxed);
    let start = Instant::now();
    let mut hits = 0;
    for index in 0..iterations {
        hits += usize::from(black_box(run(black_box(index))));
    }
    (
        start.elapsed().as_secs_f64() * 1e6 / iterations as f64,
        ALLOCATIONS.load(Ordering::Relaxed) - allocations,
        ALLOCATED_BYTES.load(Ordering::Relaxed) - bytes,
        hits,
    )
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args().skip(1);
    let path = args
        .next()
        .ok_or("usage: hit_test_benchmark MODEL [ITERATIONS]")?;
    let iterations = args
        .next()
        .map(|n| n.parse::<usize>())
        .transpose()?
        .unwrap_or(10_000);
    if iterations == 0 {
        return Err("ITERATIONS must be positive".into());
    }
    let directory = tempfile::tempdir()?;
    let cache = ModelCache::new(directory.path(), std::path::Path::new("models"));
    let resolved = cache.resolve(&path)?;
    let mut model = ModelHandle::load(&resolved.model_path)?;
    let bounds = content_size(model.meshes()).ok_or("empty model")?;
    let upper =
        upper_body_bounds(model.meshes(), model.face_height(), model.flips_y()).unwrap_or(bounds);
    let layout = ModelLayout::from_upper_body(bounds, upper, model.format());
    let matrix = layout.matrix(model.flips_y());
    let textures = Arc::new(
        model
            .take_textures()
            .into_iter()
            .map(AlphaTexture::from)
            .collect::<Vec<_>>(),
    );
    let meshes = model.meshes();
    let surface = (512, 512);
    let cursor = |i: usize| ((i % 21) as f32 * 25.6, ((i / 21) % 21) as f32 * 25.6);
    // Verify complete results, including filtered drawable indices, before timing.
    let snapshot = FrameSnapshot::new(meshes, Arc::clone(&textures), matrix);
    for i in 0..441 {
        assert_eq!(
            snapshot.hit_test(cursor(i), surface, 8),
            hit_test_meshes(meshes, &textures, matrix, cursor(i), surface, 8),
        );
    }
    drop(snapshot);
    let old = measure(iterations, |i| {
        FrameSnapshot::new(meshes, Arc::clone(&textures), matrix)
            .hit_test(cursor(i), surface, 8)
            .hit
    });
    let new = measure(iterations, |i| {
        hit_test_meshes(meshes, &textures, matrix, cursor(i), surface, 8).hit
    });
    assert_eq!(old.3, new.3);
    assert_eq!(
        (new.1, new.2),
        (0, 0),
        "borrowed hit testing must not allocate"
    );
    println!(
        "{}",
        serde_json::json!({
            "model": path, "iterations": iterations, "drawables": meshes.len(),
            "snapshot_us_per_test": old.0, "borrowed_us_per_test": new.0,
            "snapshot_allocations_per_test": old.1 as f64 / iterations as f64,
            "snapshot_allocated_bytes_per_test": old.2 as f64 / iterations as f64,
            "borrowed_allocations": new.1, "borrowed_allocated_bytes": new.2,
            "hits": new.3,
        })
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use neocari::core::Matrix44;
    use neocari::moc3::{Moc3DrawableMesh, Moc3DrawableVertex};

    #[test]
    fn borrowed_hit_testing_has_no_heap_allocations() {
        let meshes = vec![Moc3DrawableMesh::from_parts(
            0,
            0,
            1.0,
            0.0,
            vec![
                Moc3DrawableVertex::new([-1.0, -1.0], [0.0, 1.0]),
                Moc3DrawableVertex::new([1.0, -1.0], [1.0, 1.0]),
                Moc3DrawableVertex::new([0.0, 1.0], [0.5, 0.0]),
            ],
            vec![0, 1, 2],
            vec![],
        )];
        let measured = measure(1_000, |_| {
            hit_test_meshes(
                &meshes,
                &[],
                Matrix44::identity(),
                (50.0, 50.0),
                (100, 100),
                8,
            )
            .hit
        });
        assert_eq!((measured.1, measured.2, measured.3), (0, 0, 1_000));
    }
}
