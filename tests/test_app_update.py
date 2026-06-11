import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import app_update


def _asset(name: str) -> dict:
    return {
        "name": name,
        "size": 10,
        "browser_download_url": f"https://example.invalid/{name}",
    }


class AppUpdateTests(unittest.TestCase):
    def test_windows_portable_update_does_not_select_macos_zip(self):
        assets = [
            _asset("BandoriPet-3.1.0-mac.zip"),
            _asset("BandoriPet-3.1.0-win64.msi"),
        ]

        with patch.object(app_update.sys, "platform", "win32"):
            selected = app_update._select_release_asset(assets, "portable")

        self.assertEqual(selected["name"], "BandoriPet-3.1.0-win64.msi")

    def test_open_url_falls_back_to_direct_connection_when_proxy_fails(self):
        request = app_update.urllib.request.Request("https://example.invalid/update")
        response = io.BytesIO(b"update")

        with (
            patch.object(
                app_update.urllib.request,
                "getproxies",
                return_value={"https": "http://127.0.0.1:7897"},
            ),
            patch.object(
                app_update.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError(TimeoutError("proxy timed out")),
            ),
            patch.object(
                app_update,
                "_direct_url_opener",
                return_value=lambda *_args, **_kwargs: response,
            ),
        ):
            opened = app_update._open_url(request, timeout=1, purpose="testing")

        self.assertEqual(opened.read(), b"update")

    def test_incomplete_download_removes_partial_file(self):
        response = io.BytesIO(b"short")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(app_update.tempfile, "gettempdir", return_value=temp_dir),
                patch.object(app_update, "_open_url", return_value=response),
                self.assertRaisesRegex(RuntimeError, "incomplete"),
            ):
                app_update._download_asset(
                    "https://example.invalid/update.msi",
                    "BandoriPet-update.msi",
                    expected_size=10,
                )

            download_dir = temp_path / "BandoriPetUpdate"
            self.assertFalse((download_dir / "BandoriPet-update.msi").exists())
            self.assertFalse((download_dir / "BandoriPet-update.msi.part").exists())


if __name__ == "__main__":
    unittest.main()
