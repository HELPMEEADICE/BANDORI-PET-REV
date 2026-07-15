qt_add_executable(bandori-pet-rust
    main.cpp
)

qt_add_executable(bandori-pet-renderer-rust
    pet_main.cpp
    live2d_gl_widget.cpp
    live2d_gl_widget.h
    bandori_live2d_ffi.h
)

target_link_libraries(bandori-pet-rust PRIVATE
    bandori_qt_bridge
    qtfluentwidgets
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::Svg
)

target_link_libraries(bandori-pet-renderer-rust PRIVATE
    bandori_qt_bridge
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::OpenGLWidgets
)

set_target_properties(bandori-pet-rust PROPERTIES
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE TRUE
)

set_target_properties(bandori-pet-renderer-rust PROPERTIES
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE TRUE
)
