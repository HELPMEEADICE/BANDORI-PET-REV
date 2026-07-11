import hashlib
import io
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import app_update


def _asset(name: str) -> dict:
    return {
        "name": name,
        "size": 10,
        "browser_download_url": f"https://example.invalid/{name}",
    }


class AppUpdateTests(unittest.TestCase):
    def test_updater_stops_every_packaged_gui_process(self):
        self.assertIn("radial_menu_process", app_update._PROCESS_NAMES)
        self.assertIn("settings_process", app_update._PROCESS_NAMES)
        self.assertIn("chat_process", app_update._PROCESS_NAMES)

    def test_windows_portable_update_does_not_select_macos_zip(self):
        assets = [
            _asset("BandoriPet-3.1.0-mac.zip"),
            _asset("BandoriPet-3.1.0-win64.msi"),
        ]

        with patch.object(app_update.sys, "platform", "win32"):
            selected = app_update._select_release_asset(assets, "portable")

        self.assertEqual(selected["name"], "BandoriPet-3.1.0-win64.msi")

    def test_macos_update_selects_matching_arm64_dmg(self):
        assets = [
            _asset("BandoriPet-3.1.1-macos-x86_64.dmg"),
            _asset("BandoriPet-3.1.1-mac.zip"),
            _asset("BandoriPet-3.1.1-macos-arm64.dmg"),
        ]

        with (
            patch.object(app_update.sys, "platform", "darwin"),
            patch.object(app_update.platform, "machine", return_value="arm64"),
        ):
            selected = app_update._select_release_asset(assets, "macos_app")

        self.assertEqual(selected["name"], "BandoriPet-3.1.1-macos-arm64.dmg")
        self.assertEqual(
            app_update._asset_action(selected["name"], "macos_app"),
            "install_macos",
        )

    def test_macos_update_selects_matching_x86_64_dmg(self):
        assets = [
            _asset("BandoriPet-3.1.1-macos-arm64.dmg"),
            _asset("BandoriPet-3.1.1-macos-x86_64.dmg"),
        ]

        with (
            patch.object(app_update.sys, "platform", "darwin"),
            patch.object(app_update.platform, "machine", return_value="x86_64"),
        ):
            selected = app_update._select_release_asset(assets, "macos_app")

        self.assertEqual(selected["name"], "BandoriPet-3.1.1-macos-x86_64.dmg")

    def test_frozen_macos_uses_macos_app_channel(self):
        with (
            patch.object(app_update.sys, "frozen", True, create=True),
            patch.object(app_update.sys, "platform", "darwin"),
        ):
            self.assertEqual(app_update.detect_update_channel(), "macos_app")

    def test_macos_updater_stages_app_and_preserves_user_data(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(app_update.sys, "platform", "darwin"),
            patch.object(
                app_update.sys,
                "executable",
                "/Applications/BandoriPet.app/Contents/MacOS/BandoriPet",
            ),
            patch.object(app_update.tempfile, "gettempdir", return_value=temp_dir),
            patch.object(app_update.subprocess, "Popen") as popen,
        ):
            app_update._launch_macos_updater(Path(temp_dir) / "update.dmg")
            helpers = list(Path(temp_dir, "BandoriPetUpdate").glob("apply-macos-helper-*.sh"))
            helper = helpers[0].read_text(encoding="utf-8")

        self.assertIn("move_user_data", helper)
        self.assertIn("/models", helper)
        self.assertIn("/chat_attachments", helper)
        self.assertIn(".update-stage-", helper)
        self.assertIn("codesign --verify --deep --strict", helper)
        self.assertIn("target_existed=0", helper)
        self.assertIn('"$target_existed" -ne 1', helper)
        self.assertIn("required_kb=", helper)
        self.assertLess(helper.index("required_kb="), helper.index("/usr/bin/pkill"))
        popen.assert_called_once()

    def test_update_space_check_rejects_insufficient_capacity(self):
        usage = shutil._ntuple_diskusage(total=1024, used=900, free=124)
        with patch.object(app_update.shutil, "disk_usage", return_value=usage):
            with self.assertRaisesRegex(RuntimeError, "Insufficient disk space"):
                app_update._ensure_update_space(Path("."), 200, "testing")

    def test_macos_zip_checks_unpacked_temp_space(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package = Path(temp_dir) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("BandoriPet.app/Contents/MacOS/BandoriPet", b"x" * 1024)
            with patch.object(app_update, "_ensure_update_space") as ensure:
                app_update._check_macos_package_space(package)

        self.assertGreaterEqual(ensure.call_args.args[1], 1024 + app_update._UPDATE_DISK_MARGIN_BYTES)

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

    def test_git_check_blocks_diverged_branch(self):
        outputs = {
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/main",
            ("fetch", "--tags", "--prune", "origin"): "",
            ("rev-list", "--left-right", "--count", "HEAD...origin/main"): "2\t3",
            ("rev-parse", "--short", "HEAD"): "aaaaaaa",
            ("rev-parse", "--short", "origin/main"): "bbbbbbb",
            ("status", "--porcelain", "--untracked-files=no"): "",
        }

        def run_git(args, _cwd, timeout=60):
            return outputs[tuple(args)]

        with patch.object(app_update, "_run_git", side_effect=run_git):
            info = app_update._check_git_update(Path("/repo"))

        self.assertTrue(info.update_available)
        self.assertFalse(info.can_update)
        self.assertEqual(info.commits_ahead, 2)
        self.assertEqual(info.commits_behind, 3)
        self.assertIn("diverged", info.detail)

    def test_git_apply_skips_pip_when_requirements_did_not_change(self):
        run_git = MagicMock(
            side_effect=[
                "origin/main",
                "old",
                "",
                "",
                "new",
                "",
            ]
        )
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(app_update, "_run_git", run_git),
            patch.object(app_update.subprocess, "run") as run_process,
        ):
            Path(temp_dir, "requirements.txt").write_text("example\n", encoding="utf-8")
            app_update._apply_git_update(Path(temp_dir))

        run_process.assert_not_called()
        self.assertIn(
            call(
                ["diff", "--name-only", "old", "new", "--", "requirements.txt"],
                Path(temp_dir),
                timeout=30,
            ),
            run_git.call_args_list,
        )

    def test_git_apply_rolls_back_when_dependency_install_fails(self):
        def run_git(args, _cwd, timeout=60):
            outputs = {
                ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/main",
                ("rev-parse", "HEAD"): "old-commit",
                ("status", "--porcelain", "--untracked-files=no"): "",
                ("pull", "--ff-only", "origin", "main"): "",
                ("diff", "--name-only", "old-commit", "new-commit", "--", "requirements.txt"): "requirements.txt",
                ("reset", "--hard", "old-commit"): "",
            }
            if tuple(args) == ("rev-parse", "HEAD") and run_git.after_pull:
                return "new-commit"
            if tuple(args) == ("pull", "--ff-only", "origin", "main"):
                run_git.after_pull = True
            return outputs[tuple(args)]

        run_git.after_pull = False
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(app_update, "_run_git", side_effect=run_git) as git,
            patch.object(
                app_update.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, ["pip"]),
            ),
        ):
            Path(temp_dir, "requirements.txt").write_text("example\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "restored"):
                app_update._apply_git_update(Path(temp_dir))

        self.assertIn(call(["reset", "--hard", "old-commit"], Path(temp_dir), timeout=60), git.call_args_list)

    def test_git_apply_refuses_new_tracked_changes_before_pull(self):
        run_git = MagicMock(side_effect=["origin/main", "old", " M app.py"])

        with (
            patch.object(app_update, "_run_git", run_git),
            self.assertRaisesRegex(RuntimeError, "Tracked files changed"),
        ):
            app_update._apply_git_update(Path("/repo"))

        self.assertNotIn(
            call(["pull", "--ff-only", "origin", "main"], Path("/repo"), timeout=180),
            run_git.call_args_list,
        )

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
                    expected_sha256=hashlib.sha256(b"short").hexdigest(),
                )

            download_dir = temp_path / "BandoriPetUpdate"
            self.assertFalse((download_dir / "BandoriPet-update.msi").exists())
            self.assertFalse((download_dir / "BandoriPet-update.msi.part").exists())

    def test_portable_updater_script_backs_up_and_restores_replaced_entries(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(app_update.tempfile, "gettempdir", return_value=temp_dir),
            patch.object(app_update, "_check_portable_update_space"),
            patch.object(app_update, "_launch_powershell_script") as launch,
        ):
            app_update._launch_portable_zip_updater(Path(temp_dir) / "update.zip")
            script_path = launch.call_args.args[0]
            script = script_path.read_text(encoding="utf-8")
        self.assertIn("$backup", script)
        self.assertIn("$replacementStarted = $false", script)
        self.assertIn("$processesStopped = $false", script)
        self.assertIn("Copy-Item -LiteralPath $existing -Destination $backup", script)
        self.assertIn("if ($replacementStarted)", script)
        self.assertIn("BandoriPet update failed", script)
        self.assertIn("$rollbackFailed = $false", script)
        self.assertIn("Backup retained at: $backup", script)
        self.assertIn("if ($processesStopped -and (-not $rollbackFailed)", script)
        self.assertIn("Start-Process -FilePath $app", script)

    def test_download_rejects_sha256_mismatch_and_removes_partial_file(self):
        response = io.BytesIO(b"update")
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(app_update.tempfile, "gettempdir", return_value=temp_dir),
                patch.object(app_update, "_open_url", return_value=response),
                self.assertRaisesRegex(RuntimeError, "SHA-256 verification"),
            ):
                app_update._download_asset(
                    "https://example.invalid/update.msi",
                    "BandoriPet-update.msi",
                    expected_size=6,
                    expected_sha256="0" * 64,
                )

            download_dir = Path(temp_dir) / "BandoriPetUpdate"
            self.assertFalse((download_dir / "BandoriPet-update.msi").exists())
            self.assertFalse((download_dir / "BandoriPet-update.msi.part").exists())

    def test_release_digest_enables_verified_update(self):
        asset = _asset("BandoriPet-3.1.0-win64.zip")
        asset["digest"] = "sha256:" + "a" * 64
        release = {
            "tag_name": "99.0.0",
            "name": "99.0.0",
            "assets": [asset],
        }
        with (
            patch.object(app_update, "_fetch_latest_release", return_value=release),
            patch.object(app_update.sys, "platform", "win32"),
            patch.object(app_update.platform, "machine", return_value="amd64"),
        ):
            info = app_update._check_release_update("portable")

        self.assertTrue(info.can_update)
        self.assertEqual("a" * 64, info.asset_sha256)

    def test_checksum_manifest_matches_selected_asset(self):
        content = (
            f"{'b' * 64}  BandoriPet-3.1.0-win64.zip\n"
            f"{'c' * 64}  BandoriPet-3.1.0-macos.zip\n"
        )
        self.assertEqual(
            "b" * 64,
            app_update._parse_checksum_file(
                content,
                "BandoriPet-3.1.0-win64.zip",
            ),
        )

    def test_registry_display_icon_path_matches_install_directory(self):
        base = str(Path("C:/Program Files/BandoriPet").resolve()).lower()
        value = '"C:/Program Files/BandoriPet/BandoriPet.exe",0'
        self.assertTrue(app_update._path_matches_base(value, base))


if __name__ == "__main__":
    unittest.main()
