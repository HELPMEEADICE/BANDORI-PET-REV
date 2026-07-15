#pragma once

#include <cstddef>
#include <cstdint>

extern "C" {

struct BandoriLive2dHost;
using BandoriGlProcResolver = std::uintptr_t (*)(const char* name, void* userData);

const char* bandori_live2d_last_error();

BandoriLive2dHost* bandori_live2d_create(
    const char* projectRoot,
    const char* userModelsRoot,
    std::uint32_t format,
    std::uint32_t width,
    std::uint32_t height,
    BandoriGlProcResolver resolver,
    void* resolverUserData);

bool bandori_live2d_load_model(
    BandoriLive2dHost* host,
    const char* modelPath,
    std::uint32_t width,
    std::uint32_t height,
    std::uint32_t quality);
bool bandori_live2d_resize(BandoriLive2dHost* host, std::uint32_t width, std::uint32_t height);
bool bandori_live2d_resize_renderer(
    BandoriLive2dHost* host,
    std::uint32_t width,
    std::uint32_t height);
bool bandori_live2d_draw(BandoriLive2dHost* host, double timeMsec, double deltaSeconds);
bool bandori_live2d_drag(BandoriLive2dHost* host, double x, double y);
bool bandori_live2d_set_scale(BandoriLive2dHost* host, double scale);
void bandori_live2d_destroy(BandoriLive2dHost* host);

}
