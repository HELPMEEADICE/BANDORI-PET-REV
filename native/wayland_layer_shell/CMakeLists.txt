cmake_minimum_required(VERSION 3.20)
project(BandoriPetLayerShellBridge LANGUAGES CXX)

if(NOT DEFINED BANDORIPET_QT_VERSION OR BANDORIPET_QT_VERSION STREQUAL "")
    message(FATAL_ERROR "BANDORIPET_QT_VERSION must match the PySide6 runtime")
endif()

find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(Qt6 ${BANDORIPET_QT_VERSION} EXACT REQUIRED COMPONENTS Core Gui)
find_package(Shiboken6 REQUIRED)
find_package(PySide6 REQUIRED)
find_package(LayerShellQt REQUIRED)

Python3_add_library(_layer_shell MODULE WITH_SOABI bridge.cpp)
target_compile_features(_layer_shell PRIVATE cxx_std_17)
target_link_libraries(
    _layer_shell
    PRIVATE
        Qt6::Core
        Qt6::Gui
        LayerShellQt::Interface
        Shiboken6::libshiboken
        PySide6::pyside6
)
set_target_properties(
    _layer_shell
    PROPERTIES
        PREFIX ""
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python"
)
