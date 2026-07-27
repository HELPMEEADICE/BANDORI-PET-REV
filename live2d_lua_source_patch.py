"""Compatibility patches for bundled Live2D Lua source modules."""

from __future__ import annotations


_GLSL_FRAGMENT_SHADER_MODULES = {
    "live2d.core.graphics.draw_param_opengl",
    "live2d.cubism3.opengl_renderer",
}
_GLES_PRECISION = b"precision mediump float;"
_PORTABLE_GLES_PRECISION = (
    b"#ifdef GL_ES\n"
    b"precision mediump float;\n"
    b"#endif"
)


def patch_live2d_lua_module(module_name: str, chunk: bytes) -> bytes:
    """Make GLES fragment precision declarations valid on desktop OpenGL."""
    if module_name not in _GLSL_FRAGMENT_SHADER_MODULES:
        return chunk
    if _PORTABLE_GLES_PRECISION in chunk:
        return chunk
    return chunk.replace(_GLES_PRECISION, _PORTABLE_GLES_PRECISION)
