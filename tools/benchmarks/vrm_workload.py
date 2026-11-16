"""Generate an original synthetic VRM grid for repeatable CPU/heap benchmarks.

python tools/benchmarks/vrm_workload.py .runtime/performance/grid-48-morphs.vrm
"""
import argparse
import json
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[2]


def generate(side=100, morph_targets=48):
    if not 1 <= side <= 250 or not 1 <= morph_targets <= 256:
        raise ValueError("side must be 1..250 and morph_targets must be 1..256")
    source = (ROOT / "native/pet_backend/crates/pet-vrm/tests/fixtures/minimal-vrm1.vrm").read_bytes()
    length = struct.unpack_from("<I", source, 12)[0]
    manifest = json.loads(source[20:20 + length])
    blob = bytearray(source[28 + length:])

    def accessor(values, fmt, kind, component, bounds=None):
        blob.extend(b"\0" * (-len(blob) % 4))
        offset = len(blob)
        pack = struct.Struct("<" + fmt).pack
        for value in values:
            blob.extend(pack(*value))
        view = len(manifest["bufferViews"])
        manifest["bufferViews"].append({
            "buffer": 0, "byteOffset": offset, "byteLength": len(blob) - offset,
        })
        entry = {"bufferView": view, "componentType": component, "count": len(values), "type": kind}
        if bounds:
            entry.update(min=bounds[0], max=bounds[1])
        index = len(manifest["accessors"])
        manifest["accessors"].append(entry)
        return index

    count = (side + 1) ** 2
    positions = [
        ((x / side - .5) * .6, y / side * 1.6, 0.)
        for y in range(side + 1) for x in range(side + 1)
    ]
    indices = []
    for y in range(side):
        for x in range(side):
            a = y * (side + 1) + x
            indices.extend([(a,), (a + 1,), (a + side + 1,),
                            (a + 1,), (a + side + 2,), (a + side + 1,)])
    primitive = manifest["meshes"][0]["primitives"][0]
    primitive["attributes"] = {
        "POSITION": accessor(positions, "3f", "VEC3", 5126, ([-.3, 0., 0.], [.3, 1.6, 0.])),
        "NORMAL": accessor([(0., 0., 1.)] * count, "3f", "VEC3", 5126),
        "TEXCOORD_0": accessor([(x / side, y / side) for y in range(side + 1)
                                for x in range(side + 1)], "2f", "VEC2", 5126),
        "JOINTS_0": accessor([(0, 0, 0, 0)] * count, "4H", "VEC4", 5123),
        "WEIGHTS_0": accessor([(1., 0., 0., 0.)] * count, "4f", "VEC4", 5126),
    }
    primitive["indices"] = accessor(indices, "I", "SCALAR", 5125)
    target = accessor([(0., .01, 0.)] * count, "3f", "VEC3", 5126)
    primitive["targets"] = [{"POSITION": target} for _ in range(morph_targets)]
    manifest["meshes"][0]["weights"] = [0.] * morph_targets
    manifest["buffers"][0]["byteLength"] = len(blob)
    encoded = json.dumps(manifest, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    blob.extend(b"\0" * (-len(blob) % 4))
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(blob))
            + struct.pack("<I4s", len(encoded), b"JSON") + encoded
            + struct.pack("<I4s", len(blob), b"BIN\0") + blob)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--side", type=int, default=100)
    parser.add_argument("--morph-targets", type=int, default=48)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(generate(args.side, args.morph_targets))
    print(f"Synthetic VRM: {(args.side + 1) ** 2} vertices, "
          f"{args.side ** 2 * 2} triangles, {args.morph_targets} morph targets")
