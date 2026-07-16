# Runs inside CPack after the install tree is assembled and before an archive or
# installer is created. Tag-release workflows set BANDORI_SIGNING_REQUIRED=1.

set(BANDORI_SIGNING_REQUIRED FALSE)
if("$ENV{BANDORI_SIGNING_REQUIRED}" STREQUAL "1")
    set(BANDORI_SIGNING_REQUIRED TRUE)
endif()

if(WIN32)
    set(BANDORI_CERTIFICATE "$ENV{BANDORI_WINDOWS_CERTIFICATE_PATH}")
    set(BANDORI_CERTIFICATE_PASSWORD "$ENV{BANDORI_WINDOWS_CERTIFICATE_PASSWORD}")
    if(BANDORI_CERTIFICATE STREQUAL "" OR BANDORI_CERTIFICATE_PASSWORD STREQUAL "")
        if(BANDORI_SIGNING_REQUIRED)
            message(FATAL_ERROR "Windows release signing certificate or password is missing")
        endif()
        message(STATUS "Creating an explicitly unsigned Windows validation package")
        return()
    endif()
    if(NOT EXISTS "${BANDORI_CERTIFICATE}")
        message(FATAL_ERROR "Windows release signing certificate file does not exist")
    endif()
    find_program(BANDORI_SIGNTOOL_EXECUTABLE signtool REQUIRED)
    file(
        GLOB_RECURSE BANDORI_WINDOWS_PAYLOADS
        LIST_DIRECTORIES FALSE
        "${CPACK_TEMPORARY_DIRECTORY}/*.exe"
    )
    foreach(BANDORI_PAYLOAD IN LISTS BANDORI_WINDOWS_PAYLOADS)
        get_filename_component(BANDORI_PAYLOAD_NAME "${BANDORI_PAYLOAD}" NAME)
        if(NOT BANDORI_PAYLOAD_NAME STREQUAL "BandoriPet.exe"
           AND NOT BANDORI_PAYLOAD_NAME STREQUAL "bandori-pet-renderer-rust.exe")
            continue()
        endif()
        execute_process(
            COMMAND
                "${BANDORI_SIGNTOOL_EXECUTABLE}" sign
                /fd SHA256
                /td SHA256
                /tr http://timestamp.digicert.com
                /f "${BANDORI_CERTIFICATE}"
                /p "${BANDORI_CERTIFICATE_PASSWORD}"
                "${BANDORI_PAYLOAD}"
            COMMAND_ERROR_IS_FATAL ANY
        )
        list(APPEND BANDORI_SIGNED_WINDOWS_PAYLOADS "${BANDORI_PAYLOAD}")
    endforeach()
    list(LENGTH BANDORI_SIGNED_WINDOWS_PAYLOADS BANDORI_SIGNED_WINDOWS_PAYLOAD_COUNT)
    if(NOT BANDORI_SIGNED_WINDOWS_PAYLOAD_COUNT EQUAL 2)
        message(FATAL_ERROR "Expected to sign exactly two BandoriPet Windows executables")
    endif()
elseif(APPLE)
    set(BANDORI_SIGNING_IDENTITY "$ENV{BANDORI_MACOS_SIGNING_IDENTITY}")
    if(BANDORI_SIGNING_IDENTITY STREQUAL "")
        if(BANDORI_SIGNING_REQUIRED)
            message(FATAL_ERROR "macOS release signing identity is missing")
        endif()
        message(STATUS "Creating an explicitly unsigned macOS validation package")
        return()
    endif()
    find_program(BANDORI_CODESIGN_EXECUTABLE codesign REQUIRED)
    file(GLOB BANDORI_MACOS_APPS LIST_DIRECTORIES TRUE "${CPACK_TEMPORARY_DIRECTORY}/*.app")
    list(LENGTH BANDORI_MACOS_APPS BANDORI_MACOS_APP_COUNT)
    if(NOT BANDORI_MACOS_APP_COUNT EQUAL 1)
        message(FATAL_ERROR "Expected exactly one macOS application in the CPack staging tree")
    endif()
    list(GET BANDORI_MACOS_APPS 0 BANDORI_MACOS_APP)
    execute_process(
        COMMAND
            "${BANDORI_CODESIGN_EXECUTABLE}"
            --force
            --deep
            --options runtime
            --timestamp
            --sign "${BANDORI_SIGNING_IDENTITY}"
            "${BANDORI_MACOS_APP}"
        COMMAND_ERROR_IS_FATAL ANY
    )
    execute_process(
        COMMAND "${BANDORI_CODESIGN_EXECUTABLE}" --verify --deep --strict --verbose=2
                "${BANDORI_MACOS_APP}"
        COMMAND_ERROR_IS_FATAL ANY
    )
endif()
