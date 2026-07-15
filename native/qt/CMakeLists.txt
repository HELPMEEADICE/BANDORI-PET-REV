qt_add_executable(bandori-pet-rust
    main.cpp
)

target_link_libraries(bandori-pet-rust PRIVATE
    bandori_qt_bridge
    qtfluentwidgets
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::Svg
)

set_target_properties(bandori-pet-rust PROPERTIES
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE TRUE
)
