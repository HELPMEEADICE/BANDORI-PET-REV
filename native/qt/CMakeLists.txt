qt_add_executable(bandori-pet-rust
    main.cpp
    native_main_window.cpp
    native_main_window.h
    pet_process_supervisor.cpp
    pet_process_supervisor.h
    shared_memory_line_queue.cpp
    shared_memory_line_queue.h
    bandori_config_ffi.h
    bandori_ipc_ffi.h
)

qt_add_executable(bandori-pet-renderer-rust
    pet_main.cpp
    live2d_gl_widget.cpp
    live2d_gl_widget.h
    native_radial_menu.cpp
    native_radial_menu.h
    bandori_live2d_ffi.h
    pet_ipc_client.cpp
    pet_ipc_client.h
    shared_memory_line_queue.cpp
    shared_memory_line_queue.h
    bandori_ipc_ffi.h
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
