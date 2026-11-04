"""Read the small JSON chunk of a self-contained VRM without loading textures."""
import json
import struct
from pathlib import Path


def read_vrm_manifest(path: Path) -> dict:
    size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(20)
        if len(header) != 20:
            raise ValueError("Truncated VRM header")
        magic, version, length, json_length, chunk_type = struct.unpack("<4sIIII", header)
        if (magic != b"glTF" or version != 2 or length != size
                or chunk_type != 0x4E4F534A or not 0 < json_length <= min(size - 20, 16 * 1024 * 1024)):
            raise ValueError("Invalid VRM GLB header")
        data = json.loads(stream.read(json_length))
        binary_header = stream.read(8)
        if len(binary_header) != 8:
            raise ValueError("Missing VRM binary chunk")
        binary_length, binary_type = struct.unpack("<II", binary_header)
        if binary_type != 0x004E4942 or 28 + json_length + binary_length != size:
            raise ValueError("Invalid VRM binary chunk")
    if not isinstance(data, dict):
        raise ValueError("VRM JSON must be an object")
    extensions = data.get("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("Invalid VRM extensions")
    vrm = extensions.get("VRM") or extensions.get("VRMC_vrm")
    if not isinstance(vrm, dict) or not data.get("meshes") or not data.get("nodes"):
        raise ValueError("Missing VRM humanoid or meshes")
    buffers = data.get("buffers", [])
    if (not isinstance(buffers, list) or len(buffers) != 1 or not isinstance(buffers[0], dict)
            or not isinstance(buffers[0].get("byteLength"), int)
            or not 0 <= binary_length - buffers[0]["byteLength"] <= 3):
        raise ValueError("Invalid embedded VRM buffer")
    if any("uri" in buffer for buffer in buffers):
        raise ValueError("VRM buffers must be embedded")
    if any(not isinstance(image, dict) or "bufferView" not in image for image in data.get("images", [])):
        raise ValueError("VRM images must be embedded")
    return data


def read_vrm_settings(path: Path) -> dict:
    sidecar = path.with_suffix(".pet.json")
    settings = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("motions", {}), dict):
        raise ValueError("VRM settings/motions must be objects")
    if any(not isinstance(file, str) for file in settings.get("motions", {}).values()):
        raise ValueError("VRM motion paths must be strings")
    return settings


def vrm_capabilities(path: Path) -> dict:
    data = read_vrm_manifest(path)
    extensions = data["extensions"]
    vrm = extensions.get("VRM")
    if vrm:
        expressions = [
            {"name": group.get("presetName") if group.get("presetName") not in (None, "unknown") else group.get("name")}
            for group in vrm.get("blendShapeMaster", {}).get("blendShapeGroups", [])
        ]
    else:
        groups = extensions["VRMC_vrm"].get("expressions", {})
        expressions = [{"name": name} for kind in ("preset", "custom") for name in groups.get(kind, {})]
    settings = read_vrm_settings(path)
    motions = {name: [] for name in ("Idle", "Wave", "LookAround", "Thinking", "Relax", "Blush")}
    motions.update(settings.get("motions", {}))
    return {"motions": motions, "expressions": expressions, "extensions": extensions}
