"""Generate original, deterministic VRM fixtures (no third-party model data)."""
import json
import struct
from pathlib import Path


def generate(legacy):
    blob = bytearray()
    views, accessors = [], []

    def accessor(values, fmt, kind, component, count, **extra):
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        blob.extend(struct.pack("<" + fmt * len(values), *values))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(blob) - offset})
        accessors.append({"bufferView": len(views) - 1, "componentType": component,
                          "count": count, "type": kind, **extra})
        return len(accessors) - 1

    positions = accessor([-.1, 1., 0., .1, 1., 0., 0., 1.4, 0.], "f", "VEC3", 5126, 3,
                         min=[-.1, 1., 0.], max=[.1, 1.4, 0.])
    normals = accessor([0., 0., -1.] * 3, "f", "VEC3", 5126, 3)
    joints = accessor([0, 0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0], "H", "VEC4", 5123, 3)
    weights = accessor([1., 0., 0., 0.] * 3, "f", "VEC4", 5126, 3)
    indices = accessor([0, 2, 1], "H", "SCALAR", 5123, 3)
    inverse = []
    for x, y in [(0., 1.6), (.1, .9), (-.2, 1.2)]:
        inverse.extend([1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., -x, -y, 0., 1.])
    inverse_bind = accessor(inverse, "f", "MAT4", 5126, 3)
    morph = accessor([0., 0., .05] * 3, "f", "VEC3", 5126, 3)
    bones = {"hips": {"node": 0}, "head": {"node": 1}, "rightUpperArm": {"node": 2}}
    material = {"pbrMetallicRoughness": {"baseColorFactor": [.8, .2, .2, 1.]}, "doubleSided": True}
    if legacy:
        extension = {"VRM": {
            "humanoid": {"humanBones": [{"bone": name, **value} for name, value in bones.items()]},
            "materialProperties": [{"shader": "VRM/MToon", "floatProperties": {
                "_OutlineWidth": .3, "_OutlineWidthMode": 1, "_CullMode": 0, "_ShadeToony": .8},
                "vectorProperties": {"_Color": [.8, .2, .2, 1.], "_ShadeColor": [.4, .1, .1, 1.]}}],
            "secondaryAnimation": {"boneGroups": [{"bones": [3, 4], "stiffiness": 1., "dragForce": .4,
                "gravityDir": {"x": 0, "y": -1, "z": 0}, "gravityPower": .01,
                "colliderGroups": [0]}], "colliderGroups": [{"node": 0, "colliders": [
                    {"offset": {"x": -.05, "y": .25, "z": .1}, "radius": .03}]}]},
            "blendShapeMaster": {"blendShapeGroups": [{"presetName": "joy", "binds": [
                {"mesh": 0, "index": 0, "weight": 100}]}]},
        }}
    else:
        extension = {"VRMC_vrm": {"specVersion": "1.0", "humanoid": {"humanBones": bones},
            "expressions": {"preset": {"happy": {"morphTargetBinds": [{"node": 8, "index": 0, "weight": 1.}]}}}},
            "VRMC_springBone": {"specVersion": "1.0", "springs": [
                {"joints": [{"node": root, "stiffness": 1., "dragForce": .4}, {"node": tail}],
                 "colliderGroups": [0]} for root, tail in [(3, 6), (4, 7)]],
                "colliders": [{"node": 0, "shape": {"capsule": {"offset": [-.05, .25, .1],
                    "tail": [-.05, .3, .1], "radius": .03}}}], "colliderGroups": [{"colliders": [0]}]}}
        material["extensions"] = {"VRMC_materials_mtoon": {"specVersion": "1.0",
            "shadeColorFactor": [.4, .1, .1], "outlineWidthMode": "worldCoordinates",
            "outlineWidthFactor": .003, "outlineColorFactor": [.1, .1, .1]}}
    data = {"asset": {"version": "2.0", "generator": "BandoriPet original test fixture"},
        "scene": 0, "scenes": [{"nodes": [0, 8]}], "nodes": [
            {"name": "Hips", "translation": [0, 1., 0], "children": [1, 2, 4]},
            {"name": "Head", "translation": [0, .4, 0], "children": [3]},
            {"name": "RightUpperArm", "translation": [-.2, .2, 0], "children": [5]},
            {"name": "Hair", "translation": [0, .2, 0], "children": [6]},
            {"name": "Skirt", "translation": [.1, -.1, 0], "children": [7]},
            {"name": "RightLowerArm", "translation": [-.2, 0, 0]},
            {"name": "HairTip", "translation": [0, -.15, 0]},
            {"name": "SkirtTip", "translation": [0, -.2, 0]}, {"mesh": 0, "skin": 0}],
        "skins": [{"joints": [3, 4, 2], "inverseBindMatrices": inverse_bind}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": positions, "NORMAL": normals,
            "JOINTS_0": joints, "WEIGHTS_0": weights}, "indices": indices, "material": 0,
            "targets": [{"POSITION": morph}]}]}], "materials": [material],
        "extensionsUsed": list(extension), "extensions": extension,
        "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors}
    encoded = json.dumps(data, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    blob += b"\0" * (-len(blob) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(blob))
            + struct.pack("<I4s", len(encoded), b"JSON") + encoded
            + struct.pack("<I4s", len(blob), b"BIN\0") + blob)


if __name__ == "__main__":
    for legacy in (True, False):
        Path(__file__).with_name(f"minimal-vrm{0 if legacy else 1}.vrm").write_bytes(generate(legacy))
