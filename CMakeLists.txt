cmake_minimum_required(VERSION 3.24)

file(READ "${CMAKE_CURRENT_SOURCE_DIR}/app_info.py" BANDORI_PET_APP_INFO)
string(
    REGEX MATCH
    "APP_VERSION[ \t]*=[ \t]*\"([0-9]+\\.[0-9]+\\.[0-9]+)\""
    BANDORI_PET_VERSION_MATCH
    "${BANDORI_PET_APP_INFO}"
)
if(NOT CMAKE_MATCH_1)
    message(FATAL_ERROR "Could not read APP_VERSION from app_info.py")
endif()

project(BandoriPetRust VERSION "${CMAKE_MATCH_1}" LANGUAGES CXX)

include(GNUInstallDirs)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

# Rust and release Qt use the non-debug MSVC runtime.  Keeping this consistent
# also makes Debug hybrid builds link correctly on Windows.
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
    add_compile_options(/utf-8)
endif()

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets Multimedia Svg OpenGLWidgets WebSockets)

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

if(APPLE)
    set(BANDORI_PET_RESOURCE_DESTINATION "BandoriPet.app/Contents/Resources")
elseif(WIN32)
    set(BANDORI_PET_RESOURCE_DESTINATION ".")
else()
    set(BANDORI_PET_RESOURCE_DESTINATION "${CMAKE_INSTALL_DATADIR}/bandoripet")
endif()

install(
    FILES
        packaging/.bandoripet-native-package
        band.json
        outfit.json
        logo.ico
        live2d_platform_manager_override.lua
        LICENSE
    DESTINATION "${BANDORI_PET_RESOURCE_DESTINATION}"
    COMPONENT Runtime
)
install(
    FILES third_party/Qt-Fluent-Widgets/LICENSE
    DESTINATION "${BANDORI_PET_RESOURCE_DESTINATION}/licenses/Qt-Fluent-Widgets"
    COMPONENT Runtime
)

foreach(BANDORI_PET_RESOURCE_DIRECTORY IN ITEMS
    audio_reference
    band_logo
    characters
    events
    lang
    pixels
)
    install(
        DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/${BANDORI_PET_RESOURCE_DIRECTORY}/"
        DESTINATION "${BANDORI_PET_RESOURCE_DESTINATION}/${BANDORI_PET_RESOURCE_DIRECTORY}"
        COMPONENT Runtime
    )
endforeach()

option(
    BANDORI_PET_PACKAGE_BUNDLED_MODELS
    "Include the large source models directory in native packages"
    OFF
)
if(BANDORI_PET_PACKAGE_BUNDLED_MODELS)
    install(
        DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/models/"
        DESTINATION "${BANDORI_PET_RESOURCE_DESTINATION}/models"
        COMPONENT Runtime
    )
endif()
# Packages built without the option intentionally omit the repository's large
# model tree. Downloaded/custom models live below the writable Qt AppData root
# instead of Program Files, the macOS application bundle, or /usr.
install(
    DIRECTORY third_party/Live2D-v2-Lua/live2d
    DESTINATION "${BANDORI_PET_RESOURCE_DESTINATION}/third_party/Live2D-v2-Lua"
    COMPONENT Runtime
)
install(
    FILES
        third_party/Live2D-v2-Lua/live2d_embed.lua
        third_party/Live2D-v2-Lua/live2d_moc3_embed.lua
        third_party/Live2D-v2-Lua/live2d_moc3_pet_embed.lua
        third_party/Live2D-v2-Lua/LICENSE
    DESTINATION "${BANDORI_PET_RESOURCE_DESTINATION}/third_party/Live2D-v2-Lua"
    COMPONENT Runtime
)

if(UNIX AND NOT APPLE)
    install(
        FILES packaging/linux/bandoripet.desktop
        DESTINATION "${CMAKE_INSTALL_DATADIR}/applications"
        COMPONENT Runtime
    )
    install(
        FILES logo.ico
        DESTINATION "${CMAKE_INSTALL_DATADIR}/pixmaps"
        RENAME bandoripet.ico
        COMPONENT Runtime
    )
endif()

set(CPACK_PACKAGE_NAME "BandoriPet")
set(CPACK_PACKAGE_VENDOR "BandoriPet")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "Bandori desktop pet powered by Rust, LuaJIT and Qt")
set(CPACK_PACKAGE_VERSION "${PROJECT_VERSION}")
set(CPACK_PACKAGE_INSTALL_DIRECTORY "BandoriPet")
set(CPACK_PACKAGE_EXECUTABLES "BandoriPet" "BandoriPet")
set(CPACK_RESOURCE_FILE_LICENSE "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")
set(CPACK_PACKAGE_CHECKSUM SHA256)
set(CPACK_VERBATIM_VARIABLES YES)
set(
    CPACK_PACKAGE_FILE_NAME
    "BandoriPet-${PROJECT_VERSION}-${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}"
)

if(WIN32)
    set(CPACK_GENERATOR "ZIP;NSIS")
    set(CPACK_NSIS_DISPLAY_NAME "BandoriPet")
    set(CPACK_NSIS_PACKAGE_NAME "BandoriPet")
    set(CPACK_NSIS_MUI_ICON "${CMAKE_CURRENT_SOURCE_DIR}/logo.ico")
    set(CPACK_NSIS_ENABLE_UNINSTALL_BEFORE_INSTALL ON)
    set(CPACK_NSIS_MODIFY_PATH OFF)
    set(CPACK_NSIS_CREATE_ICONS_EXTRA
        "CreateShortCut '$DESKTOP\\BandoriPet.lnk' '$INSTDIR\\BandoriPet.exe'"
    )
    set(CPACK_NSIS_DELETE_ICONS_EXTRA
        "Delete '$DESKTOP\\BandoriPet.lnk'"
    )
elseif(APPLE)
    set(CPACK_GENERATOR "DragNDrop")
else()
    set(CPACK_GENERATOR "TGZ;DEB")
    set(CPACK_DEBIAN_PACKAGE_MAINTAINER "BandoriPet")
    set(CPACK_DEBIAN_PACKAGE_SHLIBDEPS ON)
endif()

include(CPack)
