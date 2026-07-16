qt_add_executable(bandori-pet-rust
    main.cpp
    native_main_window.cpp
    native_main_window.h
    native_autostart.cpp
    native_autostart.h
    native_computer_input.cpp
    native_computer_input.h
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
    Qt6::Multimedia
    Qt6::Widgets
    Qt6::OpenGLWidgets
    Qt6::Svg
    Qt6::WebSockets
)

if(WIN32)
    target_link_libraries(bandori-pet-rust PRIVATE advapi32 dwmapi user32)
elseif(APPLE)
    target_link_libraries(bandori-pet-rust PRIVATE "-framework ApplicationServices")
elseif(UNIX)
    find_package(X11 REQUIRED COMPONENTS Xtst)
    target_link_libraries(bandori-pet-rust PRIVATE X11::X11 X11::Xtst)
endif()

target_link_libraries(bandori-pet-renderer-rust PRIVATE
    bandori_qt_bridge
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::OpenGLWidgets
)

set_target_properties(bandori-pet-rust PROPERTIES
    OUTPUT_NAME BandoriPet
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE TRUE
    MACOSX_BUNDLE_BUNDLE_NAME BandoriPet
    MACOSX_BUNDLE_GUI_IDENTIFIER io.github.helpeadice.bandoripet
    MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION}"
    MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"
)

set_target_properties(bandori-pet-renderer-rust PROPERTIES
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE FALSE
)

if(WIN32)
    file(TO_CMAKE_PATH "${CMAKE_SOURCE_DIR}/logo.ico" BANDORI_PET_WINDOWS_ICON)
    configure_file(
        "${CMAKE_CURRENT_SOURCE_DIR}/bandoripet.rc.in"
        "${CMAKE_CURRENT_BINARY_DIR}/bandoripet.rc"
        @ONLY
    )
    target_sources(bandori-pet-rust PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/bandoripet.rc")
endif()

if(UNIX AND NOT APPLE)
    set_target_properties(
        bandori-pet-rust
        bandori-pet-renderer-rust
        PROPERTIES INSTALL_RPATH "$ORIGIN/../${CMAKE_INSTALL_LIBDIR}"
    )
endif()

if(APPLE)
    install(
        TARGETS bandori-pet-rust
        BUNDLE DESTINATION .
        COMPONENT Runtime
    )
    install(
        TARGETS bandori-pet-renderer-rust
        RUNTIME DESTINATION "BandoriPet.app/Contents/MacOS"
        COMPONENT Runtime
    )
elseif(WIN32)
    install(
        TARGETS bandori-pet-rust bandori-pet-renderer-rust
        RUNTIME DESTINATION .
        COMPONENT Runtime
    )
else()
    install(
        TARGETS bandori-pet-rust bandori-pet-renderer-rust
        RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
        COMPONENT Runtime
    )
endif()

qt_generate_deploy_app_script(
    TARGET bandori-pet-rust
    OUTPUT_SCRIPT BANDORI_PET_QT_DEPLOY_SCRIPT
    NO_UNSUPPORTED_PLATFORM_ERROR
)
install(SCRIPT "${BANDORI_PET_QT_DEPLOY_SCRIPT}" COMPONENT Runtime)

# The renderer is a separate executable and links Qt OpenGL modules that the
# main settings process does not necessarily retain after linker dead stripping.
# Scan it independently so packaged installs include its complete Qt runtime.
qt_generate_deploy_app_script(
    TARGET bandori-pet-renderer-rust
    OUTPUT_SCRIPT BANDORI_PET_RENDERER_QT_DEPLOY_SCRIPT
    NO_UNSUPPORTED_PLATFORM_ERROR
)
install(SCRIPT "${BANDORI_PET_RENDERER_QT_DEPLOY_SCRIPT}" COMPONENT Runtime)
