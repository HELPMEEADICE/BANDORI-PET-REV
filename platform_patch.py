import os

import OpenGL.GL as gl
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")


def _bleed_transparent_edges(image: Image.Image, passes: int = 2) -> Image.Image:
    pixels = image.load()
    width, height = image.size

    for _ in range(passes):
        updates = []
        for y in range(height):
            for x in range(width):
                alpha = pixels[x, y][3]
                if alpha >= 255:
                    continue

                red = green = blue = count = 0
                for nx, ny in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                ):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    nr, ng, nb, na = pixels[nx, ny]
                    if na <= alpha:
                        continue
                    red += nr
                    green += ng
                    blue += nb
                    count += 1

                if count:
                    updates.append((x, y, red // count, green // count, blue // count, alpha))

        if not updates:
            break
        for x, y, red, green, blue, alpha in updates:
            pixels[x, y] = (red, green, blue, alpha)

    return image


class PatchedPlatformManager:
    """Wraps PlatformManager to fix motion/expression file paths.

    The model.json files reference motion files with paths like
    ``../_mtn_emp/{char}/motion.mtn`` but ``_mtn_emp`` is at the models
    root, not inside each character directory.
    """

    def __init__(self, original_pm):
        self._original = original_pm

    def loadBytes(self, path) -> bytes:
        if not os.path.exists(path):
            fixed = self._fix_mtn_path(path)
            if fixed:
                path = fixed
        return self._original.loadBytes(path)

    def loadLive2DModel(self, path, version, disable_precision):
        return self._original.loadLive2DModel(path, version, disable_precision)

    def loadTexture(self, live2DModel, no, path):
        image = Image.open(path)
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        image = _bleed_transparent_edges(image)

        width, height = image.size
        texture = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D,
            0,
            gl.GL_RGBA,
            width,
            height,
            0,
            gl.GL_RGBA,
            gl.GL_UNSIGNED_BYTE,
            image.tobytes(),
        )
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        live2DModel.setTexture(no, texture)

    def jsonParseFromBytes(self, path):
        return self._original.jsonParseFromBytes(path)

    @staticmethod
    def _fix_mtn_path(path: str) -> str:
        norm = os.path.normpath(os.path.abspath(path))
        if os.path.exists(norm):
            return norm

        basename = os.path.basename(path)
        mtn_emp_dir = os.path.join(MODELS_DIR, "_mtn_emp")
        if not os.path.isdir(mtn_emp_dir):
            return ""

        for root, _dirs, files in os.walk(mtn_emp_dir):
            if basename in files:
                return os.path.join(root, basename)

        return ""
