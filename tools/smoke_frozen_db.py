"""Run the frozen helper's isolated native database self-test."""
import os
from pathlib import Path
import subprocess
import sys


def smoke(directory, verify_missing=False):
    helper = Path(directory).resolve() / ("bandori-ai-event.exe" if os.name == "nt" else "bandori-ai-event")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    def run():
        return subprocess.run([str(helper), "--database-self-test"], cwd=helper.parent, env=env,
                              capture_output=True, timeout=30,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    result = run()
    if result.returncode or b"Frozen database smoke passed: rust-pet-db" not in result.stdout:
        raise RuntimeError(f"Frozen database failed: {result.stdout!r} {result.stderr!r}")
    print(result.stdout.decode(errors="replace").strip())
    if verify_missing:
        suffix = ".pyd" if os.name == "nt" else ".so"
        extensions = list(helper.parent.rglob("_pet_db*" + suffix))
        if len(extensions) != 1:
            raise RuntimeError(f"Expected one frozen database extension: {extensions}")
        extension = extensions[0]
        disabled = extension.with_suffix(extension.suffix + ".disabled")
        if disabled.exists():
            raise RuntimeError(f"Refusing to overwrite {disabled}")
        extension.rename(disabled)
        try:
            result = run()
            if not result.returncode or b"Rust database extension is missing or incompatible" not in result.stderr:
                raise RuntimeError(f"Frozen missing-extension failure was unclear: {result.stdout!r} {result.stderr!r}")
        finally:
            disabled.rename(extension)
        print("Frozen missing-extension failure passed")


if __name__ == "__main__":
    smoke(sys.argv[1], verify_missing="--verify-missing" in sys.argv[2:])
