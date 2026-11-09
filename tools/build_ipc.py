"""Build and install pet-ipc for this interpreter, explicitly, before launch.

Native builds use the running Python's architecture (including a Python run
under Rosetta). Importing any application module never invokes this script.
"""
import argparse
import importlib.machinery
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "native/pet_backend/Cargo.toml"


def build(*, release=True, target=None):
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        raise RuntimeError("Use the supported GIL-enabled CPython 3.10+ build")
    if sys.version_info < (3, 10):
        raise RuntimeError("pet-ipc requires CPython 3.10+")
    if target is None and sys.platform == "darwin":
        machine = platform.machine().lower()
        target = ("aarch64" if machine in {"arm64", "aarch64"} else "x86_64") + "-apple-darwin"
    args = ["cargo", "build", "--manifest-path", str(MANIFEST),
            "-p", "pet-ipc-python", "--locked", "--message-format=json-render-diagnostics"]
    if release:
        args.append("--release")
    if target:
        args.extend(["--target", target])
    env = os.environ.copy()
    env["PYO3_PYTHON"] = sys.executable
    env["PYO3_BUILD_EXTENSION_MODULE"] = "1"
    # Cargo's JSON artifacts resolve custom target directories and target triples.
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, check=True)
    libraries = []
    for line in result.stdout.splitlines():
        message = json.loads(line)
        if message.get("reason") == "compiler-artifact" and message["target"]["name"] == "_pet_ipc":
            libraries.extend(Path(name) for name in message["filenames"] if Path(name).suffix in {".dll", ".so", ".dylib"})
    if len(libraries) != 1:
        raise RuntimeError(f"Expected one pet-ipc extension artifact, got {libraries}")
    suffix = ".pyd" if sys.platform == "win32" else ".abi3.so"
    destination = ROOT / "bandori_core" / ("_pet_ipc" + suffix)
    # Do not let an older interpreter-specific extension mask the fresh build.
    for extension in importlib.machinery.EXTENSION_SUFFIXES:
        stale = destination.parent / ("_pet_ipc" + extension)
        if stale != destination and stale.exists():
            stale.unlink()
    shutil.copy2(libraries[0], destination)
    subprocess.run([sys.executable, "-c", (
        "from bandori_core import _pet_ipc; "
        "assert _pet_ipc.BACKEND == 'rust-pet-ipc'; print(_pet_ipc.__file__)"
    )], cwd=ROOT, check=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--target", help="Cargo target; must match this Python interpreter")
    options = parser.parse_args()
    build(release=not options.debug, target=options.target)
