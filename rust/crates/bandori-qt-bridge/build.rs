use cxx_qt_build::CxxQtBuilder;

fn main() {
    CxxQtBuilder::new()
        .qt_module("Widgets")
        .file("src/backend.rs")
        .build();
}
