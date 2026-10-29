//! Optional real-asset regression: pose changes must fade instead of snapping.
//!
//! Set `BANDORI_PET_TEST_MOC3` to an extracted `.model3.json` to run these.
//! Smoothness is measured on the drawable meshes, i.e. on what is on screen:
//! vertex positions are already in clip space, so one step of `1.0` would move a
//! point across the whole canvas in a single frame. A hard cut between two poses
//! used to measure ~0.54 here.
//!
//! The clips are picked from the Bandori motion groups this model ships
//! (`mtn_idle01_C`, `mtn_surprised01_C`, `mtn_nod01_C`).

use std::path::PathBuf;

use pet_live2d::Moc3Adapter;

const FRAME: f32 = 1.0 / 60.0;

/// Largest one-frame vertex move that still reads as animation rather than a cut.
const SNAP: f32 = 0.15;

fn model_path() -> Option<PathBuf> {
    std::env::var_os("BANDORI_PET_TEST_MOC3").map(PathBuf::from)
}

/// Per-vertex positions in drawable order.
fn vertices(model: &Moc3Adapter) -> Vec<[f32; 2]> {
    model
        .meshes()
        .iter()
        .flat_map(|mesh| mesh.vertices().iter().map(|vertex| vertex.position()))
        .collect()
}

/// Records the largest single-frame vertex displacement.
struct Tracker {
    previous: Vec<[f32; 2]>,
}

impl Tracker {
    fn new(model: &Moc3Adapter) -> Self {
        Self {
            previous: vertices(model),
        }
    }

    fn step(&mut self, model: &Moc3Adapter) -> f32 {
        let current = vertices(model);
        let mut largest = 0.0f32;
        for (now, before) in current.iter().zip(self.previous.iter()) {
            let dx = now[0] - before[0];
            let dy = now[1] - before[1];
            largest = largest.max((dx * dx + dy * dy).sqrt());
        }
        self.previous = current;
        largest
    }
}

fn load() -> Option<Moc3Adapter> {
    let path = model_path()?;
    let mut model = Moc3Adapter::load(&path).unwrap();
    // Blink and breath would add noise that has nothing to do with motion changes.
    model.set_auto_blink(false);
    model.set_auto_breath(false);
    let mut tracker = Tracker::new(&model);
    for _ in 0..30 {
        assert!(model.update(FRAME));
        tracker.step(&model);
    }
    Some(model)
}

#[test]
fn replacing_a_motion_cross_fades_instead_of_snapping() {
    let Some(mut model) = load() else {
        eprintln!("skipped: set BANDORI_PET_TEST_MOC3 to an extracted .model3.json");
        return;
    };
    let mut tracker = Tracker::new(&model);

    assert!(model.play_motion("mtn_idle01_C"));
    let mut steady = 0.0f32;
    for _ in 0..120 {
        assert!(model.update(FRAME));
        steady = steady.max(tracker.step(&model));
    }

    // What a click does while an idle clip is running.
    assert!(model.play_motion("mtn_surprised01_C"));
    assert!(model.update(FRAME));
    let first = tracker.step(&model);
    let mut peak = first;
    for _ in 0..30 {
        assert!(model.update(FRAME));
        peak = peak.max(tracker.step(&model));
    }

    eprintln!("switch: steady={steady:.4} first_frame={first:.4} peak={peak:.4}");
    // The frame the new clip starts on must still show the old pose.
    assert!(
        first < 0.03,
        "the new motion started at full weight: {first:.4} in its first frame"
    );
    assert!(peak < SNAP, "motion switch snapped: {peak:.4} in one frame");
}

#[test]
fn a_finished_motion_fades_back_to_the_default_pose() {
    let Some(mut model) = load() else {
        eprintln!("skipped: set BANDORI_PET_TEST_MOC3 to an extracted .model3.json");
        return;
    };
    let mut tracker = Tracker::new(&model);

    assert!(model.play_motion("mtn_nod01_C"));
    let mut peak = 0.0f32;
    let mut frames_until_end = None;
    for frame in 0..300 {
        assert!(model.update(FRAME));
        peak = peak.max(tracker.step(&model));
        if model.is_motion_finished() {
            frames_until_end = Some(frame);
            break;
        }
    }
    let frames_until_end = frames_until_end.expect("the clip must end");

    // Dropping the clip must start a cross-fade instead of writing the default
    // pose in the next frame, and the fade must finish on its own.
    assert!(
        model.is_transitioning(),
        "the end of the clip did not start a cross-fade"
    );
    let mut fade_frames = 0;
    while model.is_transitioning() {
        assert!(model.update(FRAME));
        peak = peak.max(tracker.step(&model));
        fade_frames += 1;
        assert!(fade_frames < 120, "the cross-fade never finished");
    }

    // After the cross-fade the model holds the neutral pose again.
    let mut settled = 0.0f32;
    for _ in 0..30 {
        assert!(model.update(FRAME));
        settled = settled.max(tracker.step(&model));
    }

    eprintln!("end: peak={peak:.4} settled={settled:.4} frames={frames_until_end}+{fade_frames}");
    assert!(
        peak < SNAP,
        "dropping the clip snapped: {peak:.4} in one frame"
    );
    assert!(settled < 0.01, "the pose never settled: {settled:.4}");
}

#[test]
fn clearing_an_expression_fades_it_out() {
    let Some(mut model) = load() else {
        eprintln!("skipped: set BANDORI_PET_TEST_MOC3 to an extracted .model3.json");
        return;
    };
    let expression = model
        .info()
        .expression_names
        .first()
        .cloned()
        .expect("the model must ship expressions");
    let mut tracker = Tracker::new(&model);

    assert!(model.play_expression(&expression));
    let mut peak = 0.0f32;
    for _ in 0..90 {
        assert!(model.update(FRAME));
        peak = peak.max(tracker.step(&model));
    }
    assert_eq!(model.active_expression_count(), 1);

    model.clear_expression();
    let mut fade_frames = 0;
    while model.active_expression_count() > 0 {
        assert!(model.update(FRAME));
        peak = peak.max(tracker.step(&model));
        fade_frames += 1;
        assert!(fade_frames < 300, "the expression never faded out");
    }

    eprintln!("expression: peak={peak:.4} fade_frames={fade_frames}");
    assert!(peak < SNAP, "the face snapped: {peak:.4} in one frame");
    assert!(fade_frames > 1, "the expression popped instead of fading");
}
