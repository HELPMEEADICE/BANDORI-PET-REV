-- Project-local PlatformManager override.
-- Keeps file/zstd resource I/O in Python but performs image decode, resize,
-- transparent-edge fill, premultiply and GL upload inside LuaJIT.

local Live2DModelOpenGL = require("live2d.core.live2d_model_opengl")
local Live2DGLWrapper = require("live2d.core.live2d_gl_wrapper")
local imageLoader = require("live2d.image_loader")
local dkjson = require("live2d.dkjson")
local ffi = require("ffi")

local PlatformManager = {}
PlatformManager.__index = PlatformManager

local function normalizePath(path)
    path = tostring(path):gsub("\\", "/")
    path = path:gsub("^%./", "")
    return path
end

local function streamData(stream, path)
    if type(stream) == "function" or type(stream) == "userdata" then
        local ok, result = pcall(stream, path)
        if ok then stream = result end
    end
    if type(stream) == "table" then
        stream = stream.data or stream.bytes or stream[1]
    end
    if stream == nil then
        error("resource stream data is required: " .. tostring(path), 3)
    end
    return stream
end

local function premultiplyAlpha(w, h, data)
    local pixelCount = w * h
    local out = ffi.new("uint8_t[?]", pixelCount * 4)
    local src = ffi.cast("const uint8_t*", data)
    for i = 0, pixelCount - 1 do
        local base = i * 4
        local a = src[base + 3]
        out[base] = math.floor((src[base] * a + 127) / 255)
        out[base + 1] = math.floor((src[base + 1] * a + 127) / 255)
        out[base + 2] = math.floor((src[base + 2] * a + 127) / 255)
        out[base + 3] = a
    end
    return out
end

local function premultiplyAlphaInPlace(w, h, data)
    local pixelCount = w * h
    local src = ffi.cast("uint8_t*", data)
    for i = 0, pixelCount - 1 do
        local base = i * 4
        local a = src[base + 3]
        src[base] = math.floor((src[base] * a + 127) / 255)
        src[base + 1] = math.floor((src[base + 1] * a + 127) / 255)
        src[base + 2] = math.floor((src[base + 2] * a + 127) / 255)
    end
    return src
end

local function fillTransparentEdges(w, h, data, passes)
    passes = tonumber(passes) or 0
    if passes <= 0 then return data end
    local pixels = ffi.cast("uint8_t*", data)
    local pixelCount = w * h
    local scratch = ffi.new("uint8_t[?]", pixelCount * 4)

    for _ = 1, passes do
        ffi.copy(scratch, pixels, pixelCount * 4)
        local changed = false
        for y = 0, h - 1 do
            for x = 0, w - 1 do
                local base = (y * w + x) * 4
                if pixels[base + 3] == 0 then
                    local r, g, b, count = 0, 0, 0, 0
                    if x > 0 then
                        local nbase = (y * w + x - 1) * 4
                        if pixels[nbase + 3] > 0 then
                            r = r + pixels[nbase]; g = g + pixels[nbase + 1]; b = b + pixels[nbase + 2]; count = count + 1
                        end
                    end
                    if x + 1 < w then
                        local nbase = (y * w + x + 1) * 4
                        if pixels[nbase + 3] > 0 then
                            r = r + pixels[nbase]; g = g + pixels[nbase + 1]; b = b + pixels[nbase + 2]; count = count + 1
                        end
                    end
                    if y > 0 then
                        local nbase = ((y - 1) * w + x) * 4
                        if pixels[nbase + 3] > 0 then
                            r = r + pixels[nbase]; g = g + pixels[nbase + 1]; b = b + pixels[nbase + 2]; count = count + 1
                        end
                    end
                    if y + 1 < h then
                        local nbase = ((y + 1) * w + x) * 4
                        if pixels[nbase + 3] > 0 then
                            r = r + pixels[nbase]; g = g + pixels[nbase + 1]; b = b + pixels[nbase + 2]; count = count + 1
                        end
                    end
                    if count > 0 then
                        scratch[base] = math.floor(r / count)
                        scratch[base + 1] = math.floor(g / count)
                        scratch[base + 2] = math.floor(b / count)
                        scratch[base + 3] = 0
                        changed = true
                    end
                end
            end
        end
        if not changed then break end
        pixels, scratch = scratch, pixels
    end

    return pixels
end

local function uploadTexture(live2DModel, no, w, h, data, useMipmap, isPremultiplied, allowInPlace)
    Live2DGLWrapper.enable(Live2DGLWrapper.TEXTURE_2D)
    local texture = Live2DGLWrapper.createTexture()
    Live2DGLWrapper.bindTexture(Live2DGLWrapper.TEXTURE_2D, texture)
    if not isPremultiplied then
        if allowInPlace then
            data = premultiplyAlphaInPlace(w, h, data)
        else
            data = premultiplyAlpha(w, h, data)
        end
    end
    Live2DGLWrapper.texImage2D(Live2DGLWrapper.TEXTURE_2D, 0, Live2DGLWrapper.RGBA, w, h, 0, Live2DGLWrapper.RGBA, Live2DGLWrapper.UNSIGNED_BYTE, data)
    if useMipmap then
        Live2DGLWrapper.texParameteri(Live2DGLWrapper.TEXTURE_2D, Live2DGLWrapper.TEXTURE_MIN_FILTER, Live2DGLWrapper.LINEAR_MIPMAP_LINEAR)
    else
        Live2DGLWrapper.texParameteri(Live2DGLWrapper.TEXTURE_2D, Live2DGLWrapper.TEXTURE_MIN_FILTER, Live2DGLWrapper.LINEAR)
    end
    Live2DGLWrapper.texParameteri(Live2DGLWrapper.TEXTURE_2D, Live2DGLWrapper.TEXTURE_MAG_FILTER, Live2DGLWrapper.LINEAR)
    Live2DGLWrapper.texParameteri(Live2DGLWrapper.TEXTURE_2D, Live2DGLWrapper.TEXTURE_WRAP_S, Live2DGLWrapper.CLAMP_TO_EDGE)
    Live2DGLWrapper.texParameteri(Live2DGLWrapper.TEXTURE_2D, Live2DGLWrapper.TEXTURE_WRAP_T, Live2DGLWrapper.CLAMP_TO_EDGE)
    if useMipmap then
        Live2DGLWrapper.generateMipmap(Live2DGLWrapper.TEXTURE_2D)
    end
    Live2DGLWrapper.bindTexture(Live2DGLWrapper.TEXTURE_2D, 0)
    live2DModel:setTexture(no, texture)
end

local decodeTextureStream

if ffi.os == "Windows" then
    ffi.cdef[[
        typedef void* GpImage;
        typedef void* GpBitmap;
        typedef void* GpGraphics;
        typedef const unsigned char BYTE;
        typedef unsigned int UINT;
        typedef unsigned long ULONG;
        typedef unsigned long ULONG_PTR;
        typedef struct { int X, Y, Width, Height; } GpRect;
        typedef struct {
            unsigned int Width;
            unsigned int Height;
            int Stride;
            int PixelFormat;
            void* Scan0;
            uintptr_t Reserved;
        } BitmapData;
        typedef struct {
            unsigned int GdiplusVersion;
            void* DebugEventCallback;
            int SuppressBackgroundThread;
            int SuppressExternalCodecs;
        } GdiplusStartupInput;
        typedef struct IStream IStream;
        typedef struct IStreamVtbl {
            void* QueryInterface;
            void* AddRef;
            ULONG (__stdcall *Release)(IStream* self);
        } IStreamVtbl;
        struct IStream { IStreamVtbl* lpVtbl; };

        int GdiplusStartup(ULONG_PTR* token, const GdiplusStartupInput* input, void* output);
        int GdipLoadImageFromFile(const wchar_t* filename, GpImage** image);
        int GdipLoadImageFromStream(IStream* stream, GpImage** image);
        int GdipGetImageWidth(GpImage* image, unsigned int* width);
        int GdipGetImageHeight(GpImage* image, unsigned int* height);
        int GdipCreateBitmapFromScan0(int width, int height, int stride, int format, void* scan0, GpBitmap** bitmap);
        int GdipGetImageGraphicsContext(GpImage* image, GpGraphics** graphics);
        int GdipSetInterpolationMode(GpGraphics* graphics, int interpolationMode);
        int GdipDrawImageRectI(GpGraphics* graphics, GpImage* image, int x, int y, int width, int height);
        int GdipDeleteGraphics(GpGraphics* graphics);
        int GdipBitmapLockBits(GpBitmap* bitmap, const GpRect* rect, unsigned int flags, int format, void* lockedBitmapData);
        int GdipBitmapUnlockBits(GpBitmap* bitmap, void* lockedBitmapData);
        int GdipDisposeImage(GpImage* image);
        int MultiByteToWideChar(unsigned int CodePage, unsigned long dwFlags, const char* lpMultiByteStr, int cbMultiByte, wchar_t* lpWideCharStr, int cchWideChar);
        IStream* SHCreateMemStream(const BYTE* pInit, UINT cbInit);
    ]]

    local gdi = ffi.load("gdiplus")
    local shlwapi = ffi.load("shlwapi")
    local kernel32 = ffi.load("kernel32")
    local gdiToken = nil

    local function initGDI()
        if gdiToken then return end
        local input = ffi.new("GdiplusStartupInput")
        input.GdiplusVersion = 1
        local token = ffi.new("ULONG_PTR[1]")
        local status = gdi.GdiplusStartup(token, input, nil)
        if status ~= 0 then error("GdiplusStartup failed: " .. status) end
        gdiToken = token[0]
    end

    local function utf8ToWide(path)
        local len = kernel32.MultiByteToWideChar(65001, 0, path, #path, nil, 0)
        if len <= 0 then error("MultiByteToWideChar failed for " .. tostring(path)) end
        local wide = ffi.new("wchar_t[?]", len + 1)
        kernel32.MultiByteToWideChar(65001, 0, path, #path, wide, len)
        wide[len] = 0
        return wide
    end

    local function loadGpImage(stream)
        initGDI()
        local imgPtr = ffi.new("GpImage*[1]")
        local status
        if stream.bytes ~= nil then
            local bytes = stream.bytes
            local ptr = ffi.cast("const BYTE*", bytes)
            local istream = shlwapi.SHCreateMemStream(ptr, #bytes)
            if istream == nil then error("SHCreateMemStream failed for " .. tostring(stream.path)) end
            status = gdi.GdipLoadImageFromStream(istream, imgPtr)
            istream.lpVtbl.Release(istream)
        else
            status = gdi.GdipLoadImageFromFile(utf8ToWide(stream.path), imgPtr)
        end
        if status ~= 0 then error("GDI+ image load failed: " .. status .. " for " .. tostring(stream.path)) end
        return imgPtr[0]
    end

    function decodeTextureStream(stream)
        local img = loadGpImage(stream)
        local w = ffi.new("unsigned int[1]")
        local h = ffi.new("unsigned int[1]")
        gdi.GdipGetImageWidth(img, w)
        gdi.GdipGetImageHeight(img, h)
        local srcWidth = tonumber(w[0])
        local srcHeight = tonumber(h[0])
        local scale = tonumber(stream.scale or stream.texture_scale) or 1.0
        local width = math.max(1, math.floor(srcWidth * scale))
        local height = math.max(1, math.floor(srcHeight * scale))
        local PixelFormat32bppARGB = 2498570
        local bitmapPtr = ffi.new("GpBitmap*[1]")
        local status = gdi.GdipCreateBitmapFromScan0(width, height, 0, PixelFormat32bppARGB, nil, bitmapPtr)
        if status ~= 0 then
            gdi.GdipDisposeImage(img)
            error("GdipCreateBitmapFromScan0 failed: " .. status)
        end
        local bmp = bitmapPtr[0]
        local gfxPtr = ffi.new("GpGraphics*[1]")
        gdi.GdipGetImageGraphicsContext(bmp, gfxPtr)
        local gfx = gfxPtr[0]
        gdi.GdipSetInterpolationMode(gfx, 7)
        gdi.GdipDrawImageRectI(gfx, img, 0, 0, width, height)
        gdi.GdipDeleteGraphics(gfx)
        gdi.GdipDisposeImage(img)

        local rect = ffi.new("GpRect")
        rect.X = 0; rect.Y = 0; rect.Width = width; rect.Height = height
        local bmpData = ffi.new("BitmapData")
        gdi.GdipBitmapLockBits(bmp, rect, 3, PixelFormat32bppARGB, bmpData)
        local data = ffi.new("uint8_t[?]", width * height * 4)
        local src = ffi.cast("uint8_t*", bmpData.Scan0)
        local stride = math.abs(tonumber(bmpData.Stride))
        for y = 0, height - 1 do
            local row = src + y * stride
            for x = 0, width - 1 do
                local si = x * 4
                local di = (y * width + x) * 4
                data[di] = row[si + 2]
                data[di + 1] = row[si + 1]
                data[di + 2] = row[si]
                data[di + 3] = row[si + 3]
            end
        end
        gdi.GdipBitmapUnlockBits(bmp, bmpData)
        gdi.GdipDisposeImage(bmp)
        data = fillTransparentEdges(width, height, data, stream.bleed_passes or stream.edge_bleed_passes)
        return width, height, data
    end
else
    function decodeTextureStream(stream)
        if stream.bytes ~= nil then
            local label = stream.path and tostring(stream.path) or "<memory>"
            local w, h, data = imageLoader.loadImageBytes(stream.bytes, label)
            data = fillTransparentEdges(w, h, data, stream.bleed_passes or stream.edge_bleed_passes)
            return w, h, data
        end
        local w, h, data = imageLoader.loadImage(stream.path)
        data = fillTransparentEdges(w, h, data, stream.bleed_passes or stream.edge_bleed_passes)
        return w, h, data
    end
end

local function normalizeTextureStream(stream, no, path)
    if type(stream) == "function" then
        stream = stream(no, path)
    end
    if type(stream) ~= "table" then
        error("texture stream must be a table or function result for texture " .. tostring(no), 3)
    end

    local useMipmap = stream.mipmap == true or stream.use_mipmap == true or stream.useMipmap == true
    local isPremultiplied = stream.premultiplied == true or stream.premultiplied_alpha == true or stream.premultipliedAlpha == true
    local allowInPlace = stream.in_place == true or stream.inPlace == true
    local width = tonumber(stream.width or stream.w)
    local height = tonumber(stream.height or stream.h)
    local data = stream.data or stream.pixels or stream[1]

    if data == nil and (stream.path ~= nil or stream.bytes ~= nil) then
        width, height, data = decodeTextureStream(stream)
        allowInPlace = true
    end
    if width == nil or height == nil or width <= 0 or height <= 0 then
        error("texture stream width/height must be positive for texture " .. tostring(no), 3)
    end
    if data == nil then
        error("texture stream data is required for texture " .. tostring(no), 3)
    end
    if type(data) == "string" then
        data = ffi.cast("const uint8_t*", data)
        allowInPlace = false
    else
        data = ffi.cast("uint8_t*", data)
    end
    return width, height, data, useMipmap, isPremultiplied, allowInPlace
end

function PlatformManager.new(opts)
    opts = opts or {}
    local self = setmetatable({ resourceStreams = {}, textureStreams = {} }, PlatformManager)
    self:setResourceStreams(opts.resource_streams or opts.resourceStreams)
    self:setTextureStreams(opts.texture_streams or opts.textureStreams)
    return self
end

function PlatformManager:setResourceStream(path, data)
    self.resourceStreams[normalizePath(path)] = data
end

function PlatformManager:setResourceStreams(resourceStreams)
    if resourceStreams == nil then return end
    for k, v in pairs(resourceStreams) do
        self.resourceStreams[normalizePath(k)] = v
    end
end

function PlatformManager:clearResourceStreams()
    self.resourceStreams = {}
end

function PlatformManager:setTextureStream(no, width, height, data)
    self.textureStreams[tonumber(no)] = { width = width, height = height, data = data }
end

function PlatformManager:setTextureStreams(textureStreams)
    if textureStreams == nil then return end
    for k, v in pairs(textureStreams) do
        self.textureStreams[k] = v
    end
end

function PlatformManager:clearTextureStreams()
    self.textureStreams = {}
end

function PlatformManager:clearStreams()
    self:clearResourceStreams()
    self:clearTextureStreams()
end

function PlatformManager:loadBytes(path)
    local normalized = normalizePath(path)
    local stream = self.resourceStreams[normalized]
    if stream == nil and self.resourceStreams.__loader ~= nil then
        stream = self.resourceStreams.__loader
    end
    if stream ~= nil then
        return streamData(stream, normalized)
    end
    error("No resource stream registered for: " .. tostring(path))
end

function PlatformManager:loadLive2DModel(path)
    return Live2DModelOpenGL.loadModel(self:loadBytes(path))
end

function PlatformManager:loadTexture(live2DModel, no, path)
    local normalized = normalizePath(path)
    local stream = self.textureStreams[no] or self.textureStreams[no + 1] or self.textureStreams[path] or self.textureStreams[normalized]
    if stream == nil and self.textureStreams.__loader ~= nil then
        stream = function(texture_no, texture_path)
            return self.textureStreams.__loader(texture_no, texture_path)
        end
    end
    if stream ~= nil then
        local w, h, data, useMipmap, isPremultiplied, allowInPlace = normalizeTextureStream(stream, no, path)
        uploadTexture(live2DModel, no, w, h, data, useMipmap, isPremultiplied, allowInPlace)
        return
    end
    error("No texture stream registered for: " .. tostring(path))
end

function PlatformManager:jsonParseFromBytes(data)
    return dkjson.decode(data)
end

function PlatformManager:log(msg)
    print(msg)
end

return PlatformManager
