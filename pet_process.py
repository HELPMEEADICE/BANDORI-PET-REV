"""Compatibility CLI for the native Neocari pet executable.

The application launches Rust directly. This entry point is retained for tools
that invoke pet_process.py; it never imports QApplication, OpenGL or Lua.
"""
import argparse
import os
import subprocess
import sys

MODEL_FORMAT_MOC = "moc"
MODEL_FORMAT_MOC3 = "moc3"

from bandori_core.native_pet import native_program_and_args
from bandori_core.process_utils import app_base_dir


def ModelManager(*args, **kwargs):
    from bandori_models.model_manager import ModelManager as Manager
    return Manager(*args, **kwargs)


class SingleModelManager:
    def __init__(self, character: str, costume: str, model_path: str, model_format: str = ""):
        self._character = character
        self._costume = costume
        self._model_path = model_path
        self._model_format = model_format if model_format in {MODEL_FORMAT_MOC, MODEL_FORMAT_MOC3} else ""
        self._metadata_manager = None
        self._fallback_manager = None

    def _get_metadata_manager(self):
        if self._metadata_manager is None:
            self._metadata_manager = ModelManager(scan_models=False, discover_models=False)
        return self._metadata_manager

    @property
    def characters(self) -> list[str]:
        return [self._character] if self._character else []

    def get_default_costume(self, character: str) -> str:
        return self._costume if character == self._character else ""

    def get_model_json_path(self, character: str, costume: str) -> str:
        if character == self._character and costume == self._costume:
            return self._model_path
        if self._fallback_manager is None:
            self._fallback_manager = ModelManager()
        return self._fallback_manager.get_model_json_path(character, costume)

    def get_model_format(self, character: str, costume: str) -> str:
        path = self.get_model_json_path(character, costume)
        if not path:
            return ""
        if character == self._character and costume == self._costume and self._model_format:
            return self._model_format
        return self._get_metadata_manager()._model_format_from_path(path)

    def get_display_name(self, character: str) -> str:
        return self._get_metadata_manager().get_display_name(character)

    def get_costume_display_name(self, character: str, costume_id: str) -> str:
        return self._get_metadata_manager().get_costume_display_name(character, costume_id)


def main():
    parser = argparse.ArgumentParser(description="Run an isolated Neocari pet")
    parser.add_argument("--character", required=True)
    parser.add_argument("--costume", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-format", default="")
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--group-characters", default="")
    args = parser.parse_args()
    program, arguments = native_program_and_args(
        app_base_dir(), args.character, args.costume, args.model_path,
    )
    if os.name != "nt":
        os.execv(program, [program, *arguments])
    return subprocess.call([program, *arguments])


if __name__ == "__main__":
    sys.exit(main())
