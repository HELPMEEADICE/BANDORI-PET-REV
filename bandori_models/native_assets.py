"""Versioned ctypes bridge to pet-assets; Rust owns archive IO and caches."""

import ctypes
import json
import os
from pathlib import Path
import struct
import sys
import threading


class _Buffer(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("length", ctypes.c_size_t)]


_library = None
_library_lock = threading.Lock()


def _load_library():
    global _library
    with _library_lock:
        if _library is not None:
            return _library
        name = (
            "pet_assets.dll" if sys.platform == "win32" else
            "libpet_assets.dylib" if sys.platform == "darwin" else
            "libpet_assets.so"
        )
        root = Path(__file__).resolve().parents[1]
        target = Path(os.environ.get("CARGO_TARGET_DIR", root / "native" / "pet_backend" / "target"))
        override = os.environ.get("BANDORI_PET_ASSETS")
        candidates = [Path(override)] if override else [
            Path(sys.executable).resolve().parent / name,
            Path(sys.executable).resolve().parent.parent / "Frameworks" / name,
            Path(sys.executable).resolve().parent.parent / "Resources" / name,
            root / name,
            target / "release" / name,
            target / "debug" / name,
        ]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            library = ctypes.CDLL(str(candidate.resolve()))
            library.pet_assets_abi_version.argtypes = []
            library.pet_assets_abi_version.restype = ctypes.c_uint32
            if library.pet_assets_abi_version() != 1:
                raise RuntimeError(f"Unsupported pet-assets ABI: {candidate}")
            library.pet_assets_request.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            library.pet_assets_request.restype = _Buffer
            library.pet_assets_free.argtypes = [_Buffer]
            library.pet_assets_free.restype = None
            _library = library
            return library
    raise RuntimeError(
        "pet-assets native library is missing. Run: cargo build --release "
        "--manifest-path native/pet_backend/Cargo.toml -p pet-assets --locked"
    )


def request(op: str, **arguments):
    library = _load_library()
    payload = json.dumps({"op": op, **arguments}, ensure_ascii=False).encode("utf-8")
    buffer = library.pet_assets_request(payload, len(payload))
    try:
        if not buffer.data or buffer.length < 4:
            raise RuntimeError("Invalid pet-assets response")
        meta_size = struct.unpack("<I", ctypes.string_at(buffer.data, 4))[0]
        offset = 4 + meta_size
        if offset > buffer.length:
            raise RuntimeError("Truncated pet-assets metadata")
        metadata = json.loads(ctypes.string_at(buffer.data + 4, meta_size))
        if not metadata["ok"]:
            error_type = {"value": ValueError, "missing": KeyError, "io": OSError}.get(metadata["kind"], RuntimeError)
            raise error_type(metadata["error"])
        value = metadata["value"]
        if op not in {"read", "read_batch"}:
            return value
        resources = {}
        for member in value:
            size = member["size"]
            if size < 0 or offset + size > buffer.length:
                raise RuntimeError("Truncated pet-assets resource")
            resources[member["member"]] = ctypes.string_at(buffer.data + offset, size)
            offset += size
        return resources
    finally:
        library.pet_assets_free(buffer)
