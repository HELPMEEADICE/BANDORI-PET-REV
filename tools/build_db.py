"""Explicitly build the database extension; never invoked by application imports."""
import argparse

try:
    from tools.build_ipc import build as _build
except ModuleNotFoundError:
    from build_ipc import build as _build


def build(*, release=True, target=None):
    return _build(release=release, target=target, crate="pet-db-python",
                  module="_pet_db", backend="rust-pet-db")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--target")
    args = parser.parse_args()
    build(release=not args.debug, target=args.target)
