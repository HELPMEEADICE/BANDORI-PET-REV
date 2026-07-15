cmake_minimum_required(VERSION 3.24)

project(BandoriPetRust VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

# Rust and release Qt use the non-debug MSVC runtime.  Keeping this consistent
# also makes Debug hybrid builds link correctly on Windows.
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
endif()

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets Svg)

find_package(CxxQt 0.9 QUIET)
if(NOT CxxQt_FOUND)
    include(FetchContent)
    FetchContent_Declare(
        CxxQt
        GIT_REPOSITORY https://github.com/KDAB/cxx-qt-cmake.git
        GIT_TAG 0.9.0
        GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(CxxQt)
endif()

cxx_qt_import_crate(
    MANIFEST_PATH "${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml"
    CRATES bandori_qt_bridge
    LOCKED
    QT_MODULES Qt6::Core Qt6::Gui Qt6::Widgets
)

# Add the library itself, not its gallery application.
add_subdirectory(third_party/Qt-Fluent-Widgets/qtfluentwidgets)
add_subdirectory(native/qt)
