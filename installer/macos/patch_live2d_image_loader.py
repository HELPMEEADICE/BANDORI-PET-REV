#!/usr/bin/env python3
"""Add BandoriPet's in-memory PNG loader to Live2D-v2-Lua."""

from __future__ import annotations

import argparse
from pathlib import Path


FUNCTION_MARKER = "function M.loadImageBytes"
LOAD_IMAGE_BLOCK = """    function M.loadImage(path)
        local ok, w, h, data = pcall(decodePNGFile, path)
        if not ok then
            print("PNG load failed for: " .. path .. " (" .. tostring(w) .. ")")
            return createDummyTexture(4, 4)
        end
        return w, h, data
    end

    return M
end
"""
LOAD_IMAGE_BYTES_BLOCK = """    function M.loadImage(path)
        local ok, w, h, data = pcall(decodePNGFile, path)
        if not ok then
            print("PNG load failed for: " .. path .. " (" .. tostring(w) .. ")")
            return createDummyTexture(4, 4)
        end
        return w, h, data
    end

    function M.loadImageBytes(bytes, path)
        local label = tostring(path or "<memory>")
        local ok, w, h, data = pcall(decodePNG, bytes, label)
        if not ok then
            print("PNG byte load failed for: " .. label .. " (" .. tostring(w) .. ")")
            return createDummyTexture(4, 4)
        end
        return w, h, data
    end

    return M
end
"""


def patch_image_loader(path: Path) -> bool:
    """Patch *path* and return True; return False when already patched."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Live2D image loader not found: {path}. "
            "Clone Live2D-v2-Lua into third_party first."
        )

    source = path.read_text(encoding="utf-8")
    if FUNCTION_MARKER in source:
        return False
    if source.count(LOAD_IMAGE_BLOCK) != 1:
        raise RuntimeError(
            f"{path} has an unexpected layout; refusing to apply an unsafe patch."
        )

    patched = source.replace(LOAD_IMAGE_BLOCK, LOAD_IMAGE_BYTES_BLOCK, 1)
    if patched.count(FUNCTION_MARKER) != 1:
        raise RuntimeError(f"Failed to add {FUNCTION_MARKER} to {path}.")
    path.write_text(patched, encoding="utf-8")
    return True


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    default_path = (
        repo_root
        / "third_party"
        / "Live2D-v2-Lua"
        / "live2d"
        / "image_loader.lua"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=default_path)
    args = parser.parse_args()

    changed = patch_image_loader(args.path.resolve())
    state = "patched" if changed else "already patched"
    print(f"Live2D loadImageBytes: {state} ({args.path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
