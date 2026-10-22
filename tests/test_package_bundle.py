"""The standalone-bundle tool: asset exactness, build arguments, archive and evidence reads.

The real freeze and the native package smoke run in the package CI job (and locally
with ``scripts/package_bundle.py``); these cover the decisions that do not need a
display or a PyInstaller run.
"""

import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from inventory_control import desktop
from inventory_control.backup import backup_database
from inventory_control.store import InventoryStore

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "package_bundle.py"
spec = importlib.util.spec_from_file_location("package_bundle", SCRIPT)
assert spec is not None
assert spec.loader is not None
package_bundle = importlib.util.module_from_spec(spec)
sys.modules["package_bundle"] = package_bundle
spec.loader.exec_module(package_bundle)

PackagingError = package_bundle.PackagingError
ASSETS = {"index.html": "<html>", "app.js": "console.log(1)", "style.css": "body{}"}


def write_assets(directory: Path, assets: dict[str, str] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in (assets or ASSETS).items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def make_bundle(root: Path, assets: dict[str, str] | None = None) -> Path:
    bundle = root / "invsys-desktop"
    write_assets(bundle / "_internal" / "frontend" / "dist", assets)
    package_bundle.executable_path(bundle).parent.mkdir(parents=True, exist_ok=True)
    # Unrelated web content inside bundled packages must not be mistaken for the assets.
    other = bundle / "_internal" / "webview" / "js"
    other.mkdir(parents=True)
    (other / "index.html").write_text("library page", encoding="utf-8")
    return bundle


def test_required_assets_match_the_launcher():
    assert package_bundle.REQUIRED_ASSETS == desktop.REQUIRED_ASSETS


def test_build_refuses_to_start_without_built_assets(tmp_path):
    write_assets(tmp_path / "dist", {"index.html": "x"})
    with pytest.raises(PackagingError, match=r"app\.js, style\.css"):
        package_bundle.require_built_assets(tmp_path / "dist")


def test_bundle_whose_assets_match_the_build_verifies(tmp_path):
    assets = write_assets(tmp_path / "dist")
    bundle = make_bundle(tmp_path)
    assert package_bundle.verify_assets(bundle, assets) == package_bundle.asset_hashes(assets)


@pytest.mark.parametrize(
    "tamper, problem",
    [
        (lambda bundled: (bundled / "app.js").write_text("other"), "app.js differs"),
        (lambda bundled: (bundled / "app.js").unlink(), "app.js is missing"),
        (lambda bundled: (bundled / "extra.map").write_text("x"), "extra.map is not part"),
    ],
)
def test_bundle_with_other_assets_than_the_build_is_rejected(tmp_path, tamper, problem):
    assets = write_assets(tmp_path / "dist")
    bundle = make_bundle(tmp_path)
    tamper(bundle / "_internal" / "frontend" / "dist")
    with pytest.raises(PackagingError, match=problem):
        package_bundle.verify_assets(bundle, assets)


def test_a_bundle_must_hold_exactly_one_asset_directory(tmp_path):
    empty = tmp_path / "invsys-desktop"
    empty.mkdir()
    with pytest.raises(PackagingError, match="found 0"):
        package_bundle.find_bundled_assets(empty)
    bundle = make_bundle(tmp_path / "twice")
    write_assets(bundle / "other" / "frontend" / "dist")
    with pytest.raises(PackagingError, match="found 2"):
        package_bundle.find_bundled_assets(bundle)


def test_freeze_arguments_bundle_the_exact_assets_and_the_qt_webengine_runtime(tmp_path):
    assets, dist, work = tmp_path / "assets", tmp_path / "dist", tmp_path / "work"
    args = package_bundle.pyinstaller_args(Path("/repo"), assets, dist, work)
    pairs = list(itertools.pairwise(args))
    assert ("--add-data", f"{assets}{os.pathsep}frontend/dist") in pairs
    for module in ("webview.platforms.qt", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore"):
        assert ("--hidden-import", module) in pairs
    for module in ("PyQt5", "PyQt6", "PySide2", "tkinter", "gi"):
        assert ("--exclude-module", module) in pairs
    assert "--onedir" in args
    assert args[-1] == str(Path("/repo") / "inventory_desktop.py")
    # The spec file and scratch files stay out of the checkout.
    assert ("--specpath", str(work)) in pairs
    assert ("--workpath", str(work)) in pairs
    assert ("--distpath", str(dist)) in pairs


def test_macos_freeze_makes_an_identified_application_and_other_platforms_do_not(tmp_path):
    for system, expected in (("darwin", True), ("linux", False), ("win32", False)):
        args = package_bundle.pyinstaller_args(Path("/repo"), tmp_path, tmp_path, tmp_path, system)
        pairs = list(itertools.pairwise(args))
        assert ("--windowed" in args) is expected
        assert (("--osx-bundle-identifier", package_bundle.BUNDLE_IDENTIFIER) in pairs) is expected
        assert args[-1] == str(Path("/repo") / "inventory_desktop.py")


def test_macos_bundle_is_an_application_with_executable_and_manifest_inside(tmp_path):
    app = package_bundle.bundle_path(tmp_path, "darwin")
    assert app == tmp_path / "invsys-desktop.app"
    assert package_bundle.executable_path(app, "darwin") == (
        app / "Contents" / "MacOS" / "invsys-desktop"
    )
    assert package_bundle.manifest_path(app, "darwin") == (
        app / "Contents" / "Resources" / "bundle-manifest.json"
    )
    folder = package_bundle.bundle_path(tmp_path, "linux")
    assert folder == tmp_path / "invsys-desktop"
    assert package_bundle.executable_path(folder, "linux") == folder / "invsys-desktop"
    assert package_bundle.executable_path(folder, "win32") == folder / "invsys-desktop.exe"
    assert package_bundle.manifest_path(folder, "linux") == folder / "bundle-manifest.json"


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_application_assets_are_verified_once_through_the_frameworks_link(tmp_path):
    assets = write_assets(tmp_path / "dist")
    app = tmp_path / "invsys-desktop.app"
    write_assets(app / "Contents" / "Resources" / "frontend" / "dist")
    # PyInstaller links data from Contents/Frameworks (sys._MEIPASS) to Contents/Resources.
    (app / "Contents" / "Frameworks").mkdir()
    (app / "Contents" / "Frameworks" / "frontend").symlink_to(Path("..") / "Resources" / "frontend")
    found = package_bundle.find_bundled_assets(app)
    assert found == app / "Contents" / "Resources" / "frontend" / "dist"
    assert package_bundle.verify_assets(app, assets) == package_bundle.asset_hashes(assets)
    # The incomplete-bundle check removes the real folder; the link is left dangling.
    copy = tmp_path / "copy.app"
    package_bundle.hardlinked_copy(app, copy)
    shutil.rmtree(package_bundle.find_bundled_assets(copy))
    assert not (copy / "Contents" / "Frameworks" / "frontend" / "dist" / "index.html").exists()
    assert (found / "index.html").is_file()


class FakeTools:
    """Stands in for codesign/spctl/sysctl and records each call."""

    def __init__(self, results: dict[str, tuple[int, str, str]] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.results = results or {}

    def __call__(self, *command: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        key = " ".join(command[:2])
        code, stdout, stderr = self.results.get(key, (0, "", ""))
        return subprocess.CompletedProcess(list(command), code, stdout, stderr)


def test_sealing_resigns_the_application_ad_hoc_and_verifies_it(tmp_path, monkeypatch):
    tools = FakeTools()
    monkeypatch.setattr(package_bundle, "_tool", tools)
    package_bundle.seal_application(tmp_path / "invsys-desktop.app")
    app = str(tmp_path / "invsys-desktop.app")
    assert tools.calls == [
        ("codesign", "--force", "--sign", "-", app),
        ("codesign", "--verify", "--deep", "--strict", app),
    ]


def test_a_broken_seal_or_missing_codesign_is_a_readable_build_failure(tmp_path, monkeypatch):
    broken = FakeTools({"codesign --verify": (1, "", "a sealed resource is missing or invalid")})
    monkeypatch.setattr(package_bundle, "_tool", broken)
    with pytest.raises(PackagingError, match=r"--strict` failed .*sealed resource is missing"):
        package_bundle.seal_application(tmp_path / "invsys-desktop.app")

    def missing(*command, check=False):
        raise FileNotFoundError(2, "No such file or directory", command[0])

    monkeypatch.setattr(package_bundle, "_tool", missing)
    with pytest.raises(PackagingError, match="Cannot run codesign"):
        package_bundle.seal_application(tmp_path / "invsys-desktop.app")


def test_application_evidence_records_seal_signature_and_gatekeeper(tmp_path, monkeypatch):
    details = "Executable=/x\nIdentifier=io.github.theozex4ever.invsys\nSignature=adhoc\nHash=1\n"
    tools = FakeTools(
        {
            "codesign --verify": (0, "", "valid on disk\nsatisfies its Designated Requirement\n"),
            "codesign --display": (0, "", details),
            "spctl --assess": (3, "", "invsys-desktop.app: rejected\n"),
        }
    )
    monkeypatch.setattr(package_bundle, "_tool", tools)
    record = package_bundle.signature_record(tmp_path / "invsys-desktop.app")
    assert record["passed"] is True
    assert record["signature"] == ["Identifier=io.github.theozex4ever.invsys", "Signature=adhoc"]
    # Gatekeeper rejecting an unsigned application is recorded, not a smoke failure.
    assert record["gatekeeper"] == ["invsys-desktop.app: rejected"]
    tools.results["codesign --verify"] = (1, "", "invalid signature\n")
    assert package_bundle.signature_record(tmp_path / "x.app")["passed"] is False

    def missing(*command, check=False):
        raise FileNotFoundError(2, "No such file or directory", command[0])

    monkeypatch.setattr(package_bundle, "_tool", missing)
    assert package_bundle.signature_record(tmp_path / "x.app")["passed"] is False


def test_macos_machine_record_reads_hardware_from_sysctl(monkeypatch):
    tools = FakeTools(
        {
            "sysctl -n": (0, "Apple M1 (Virtual)\n", ""),
        }
    )
    monkeypatch.setattr(package_bundle, "_tool", tools)
    record = package_bundle.machine_record("darwin")
    assert record["cpu"] == "Apple M1 (Virtual)"
    assert record["os"].startswith("macOS")
    assert "libc" not in record
    assert ("sysctl", "-n", "hw.memsize") in tools.calls
    tools.results["sysctl -n"] = (1, "", "unknown oid")
    assert package_bundle.machine_record("darwin")["cpu"] == "unknown"


def test_machine_record_names_the_ci_runner_image(monkeypatch):
    monkeypatch.setenv("ImageOS", "win25")
    monkeypatch.setenv("ImageVersion", "20261012.1")
    assert package_bundle.machine_record()["ci_image"] == "win25 20261012.1"
    monkeypatch.delenv("ImageOS")
    assert "ci_image" not in package_bundle.machine_record()


def test_machine_record_describes_the_reference_machine():
    record = package_bundle.machine_record()
    for key in ("os", "cpu", "memory"):
        assert record[key], key


def test_windows_folder_evidence_requires_visible_navigation_to_both_inventory_folders(tmp_path):
    database = tmp_path / "inventory.db"
    evidence = tmp_path / "smoke-captures" / "windows-folders.json"
    evidence.parent.mkdir()
    assert package_bundle.native_folder_evidence(database)["passed"] is False
    observations = [
        {
            "requested": str(tmp_path / kind),
            "path": str(tmp_path / kind),
            "hwnd": hwnd,
            "visible": True,
            "closed_after_probe": True,
        }
        for kind, hwnd in (("backups", 101), ("exports", 102))
    ]
    evidence.write_text(json.dumps(observations[:1]))
    assert package_bundle.native_folder_evidence(database)["passed"] is False
    evidence.write_text(json.dumps(observations))
    assert package_bundle.native_folder_evidence(database)["passed"] is True
    observations[1]["path"] = str(tmp_path / "wrong-inventory" / "exports")
    evidence.write_text(json.dumps(observations))
    assert package_bundle.native_folder_evidence(database)["passed"] is False
    observations[1]["path"] = str(tmp_path / "exports")
    observations[1]["visible"] = False
    evidence.write_text(json.dumps(observations))
    assert package_bundle.native_folder_evidence(database)["passed"] is False


def test_manifest_records_assets_toolchain_and_source(tmp_path):
    manifest = package_bundle.build_manifest({"app.js": "abc"}, tmp_path)
    assert manifest["assets"] == {"app.js": "abc"}
    assert manifest["python"].count(".") == 2
    assert set(manifest["packages"]) == set(package_bundle.RECORDED_PACKAGES)
    # Not a repository: recorded as unknown rather than guessed.
    assert manifest["source"] == {"commit": "unknown", "uncommitted_changes": None}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_archive_keeps_the_layout_executable_bit_and_is_reproducible(tmp_path):
    bundle = make_bundle(tmp_path)
    launcher = bundle / "invsys-desktop"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    (bundle / "link").symlink_to("invsys-desktop")
    first, second = tmp_path / "a.tar.gz", tmp_path / "b.tar.gz"
    package_bundle.make_archive(bundle, first)
    package_bundle.make_archive(bundle, second)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        members = {member.name: member for member in archive.getmembers()}
        assert members["invsys-desktop"].isdir()
        assert members["invsys-desktop/invsys-desktop"].mode & 0o111
        assert members["invsys-desktop/link"].issym()
        assert {m.uid for m in members.values()} == {0}
        names = list(members)
        extracted = archive.extractfile("invsys-desktop/_internal/frontend/dist/app.js")
        assert extracted is not None
        assert io.TextIOWrapper(extracted, encoding="utf-8").read() == ASSETS["app.js"]
    assert names == sorted(names)


def test_a_hardlinked_copy_can_lose_assets_without_touching_the_bundle(tmp_path):
    bundle = make_bundle(tmp_path / "original")
    copy = tmp_path / "copy"
    package_bundle.hardlinked_copy(bundle, copy)
    assert package_bundle.asset_hashes(package_bundle.find_bundled_assets(copy)) == (
        package_bundle.asset_hashes(package_bundle.find_bundled_assets(bundle))
    )
    shutil.rmtree(package_bundle.find_bundled_assets(copy))
    assert (bundle / "_internal" / "frontend" / "dist" / "app.js").read_text() == ASSETS["app.js"]


def test_database_evidence_reports_integrity_counts_and_startup_backups(tmp_path):
    database = tmp_path / "inventory" / "inventory.db"
    store = InventoryStore(database, seed=False)
    try:
        store.add_part("EVIDENCE-1", "Evidence part", 1)
    finally:
        store.engine.dispose()
    assert package_bundle.startup_backups(database) == []
    backup_database(database, database.parent / "backups", reason="startup")
    backup_database(database, database.parent / "backups", reason="manual")
    counts = package_bundle.database_counts(database)
    assert counts["integrity_check"] == "ok"
    assert counts["parts"] == 1
    assert counts["inventory_transactions"] == 0
    assert package_bundle.transaction_ids(database) == set()
    assert len(package_bundle.startup_backups(database)) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in launcher is a POSIX script")
def test_run_bundle_reports_exit_code_and_output_of_the_launcher(tmp_path):
    bundle = make_bundle(tmp_path)
    launcher = package_bundle.executable_path(bundle)
    launcher.write_text(
        f'#!{sys.executable}\nimport os, sys\nprint("home", os.environ["INVSYS_HOME"])\n'
        'print("args", *sys.argv[1:], file=sys.stderr)\nsys.exit(3)\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    run = package_bundle.run_bundle(
        bundle, ["--database", "x"], tmp_path, {"INVSYS_HOME": "/nowhere"}
    )
    assert run["exit_code"] == 3
    assert run["stdout"].strip() == "home /nowhere"
    assert run["stderr"].strip() == "args --database x"


def test_the_smoke_refuses_a_missing_executable_or_a_used_workdir(tmp_path):
    assets = write_assets(tmp_path / "dist")
    with pytest.raises(PackagingError, match="No bundle executable"):
        package_bundle.smoke(tmp_path / "none", assets, tmp_path / "w", tmp_path / "e.json", False)
    bundle = make_bundle(tmp_path)
    executable = package_bundle.executable_path(bundle)
    executable.write_text("", encoding="utf-8")
    used = tmp_path / "used"
    used.mkdir()
    (used / "old").write_text("x", encoding="utf-8")
    with pytest.raises(PackagingError, match="must be empty"):
        package_bundle.smoke(bundle, assets, used, tmp_path / "e.json", False)


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in launcher is a POSIX script")
def test_relative_smoke_paths_launch_from_another_cwd_and_retain_failure_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(package_bundle, "require_display", lambda: None)
    write_assets(Path("assets"))
    bundle = make_bundle(Path("dist"))
    launcher = package_bundle.executable_path(bundle)
    # A failed native run must still record the selected paths and its evidence.
    launcher.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        "print(json.dumps([os.getcwd(), os.environ['INVSYS_HOME'], sys.argv[1:]]))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    assert (
        package_bundle.main(
            [
                "smoke",
                "--bundle",
                str(bundle),
                "--assets",
                "assets",
                "--workdir",
                "smoke",
                "--evidence",
                "records/evidence.json",
            ]
        )
        == 1
    )
    evidence = json.loads((tmp_path / "records" / "evidence.json").read_text())
    assert evidence["result"] == "failed"
    for run in evidence["runs"]:
        cwd, home, arguments = json.loads("\n".join(run["stdout"]))
        assert cwd == str(tmp_path / "smoke" / "cwd")
        assert home == str(tmp_path / "smoke" / "unexpected-home")
        assert arguments == [
            "--database",
            str(tmp_path / "smoke" / "inventory" / "inventory.db"),
            "--smoke-check",
        ]


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in launcher is a POSIX script")
def test_a_hung_launcher_is_a_failed_run_with_a_record(tmp_path, monkeypatch):
    bundle = make_bundle(tmp_path)
    launcher = package_bundle.executable_path(bundle)
    launcher.write_text("#!/bin/sh\necho started\nexec sleep 30\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setattr(package_bundle, "RUN_TIMEOUT_SECONDS", 1)
    run = package_bundle.run_bundle(bundle, [], tmp_path, {})
    assert run["exit_code"] == -1
    assert "Timed out after 1 s" in run["stderr"]
    assert run["stdout"].strip() == "started"


# ---------------------------------------------------------------- Windows bundle


def test_the_launcher_is_an_exe_on_windows_only():
    assert package_bundle.executable_path(Path("b"), "win32") == Path("b") / "invsys-desktop.exe"
    assert package_bundle.executable_path(Path("b"), "linux") == Path("b") / "invsys-desktop"
    assert package_bundle.executable_path(Path("b.app"), "darwin") == (
        Path("b.app") / "Contents" / "MacOS" / "invsys-desktop"
    )


def test_windows_bundles_are_zip_archives_and_others_gzipped_tar():
    assert package_bundle.archive_name("win32", "AMD64") == "invsys-desktop-win32-amd64.zip"
    assert package_bundle.archive_name("linux", "x86_64") == "invsys-desktop-linux-x86_64.tar.gz"


def test_the_windows_freeze_keeps_the_shared_arguments_and_drops_the_dotnet_backends(tmp_path):
    assets, dist, work = tmp_path / "assets", tmp_path / "dist", tmp_path / "work"
    shared = package_bundle.pyinstaller_args(Path("/repo"), assets, dist, work, "linux")
    windows = package_bundle.pyinstaller_args(Path("/repo"), assets, dist, work, "win32")
    pairs = list(itertools.pairwise(windows))
    # Everything the Linux freeze does is still done: one build path, not a fork.
    assert set(shared) <= set(windows)
    for module in ("clr", "clr_loader", "pythonnet"):
        assert ("--exclude-module", module) in pairs
        assert ("--exclude-module", module) not in list(itertools.pairwise(shared))
    # A console executable keeps the readable startup failures visible.
    assert "--console" in windows
    assert "--noupx" in windows
    assert "--windowed" not in windows
    assert "--noconsole" not in windows
    assert windows[-1] == str(Path("/repo") / "inventory_desktop.py")


def test_a_zip_archive_keeps_the_layout_and_is_reproducible(tmp_path):
    bundle = make_bundle(tmp_path)
    (bundle / "invsys-desktop.exe").write_bytes(b"MZ")
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    package_bundle.make_archive(bundle, first)
    # Changing modification times must not change the archive.
    os.utime(bundle / "_internal" / "frontend" / "dist" / "app.js", (86400 * 400, 86400 * 400))
    package_bundle.make_archive(bundle, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "invsys-desktop/invsys-desktop.exe" in names
        assert "invsys-desktop/_internal/frontend/dist/app.js" in names
        assert archive.read("invsys-desktop/_internal/frontend/dist/app.js") == b"console.log(1)"
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert archive.testzip() is None


def test_network_isolation_is_native_to_the_platform_or_refused(tmp_path):
    bundle = make_bundle(tmp_path)
    with package_bundle.network_isolation(bundle, False, "darwin") as record:
        assert record == {"enabled": False}
    with package_bundle.network_isolation(bundle, True, "linux") as record:
        assert record["mechanism"] == "linux-empty-network-namespace"
    with (
        pytest.raises(PackagingError, match="not available on darwin"),
        package_bundle.network_isolation(bundle, True, "darwin"),
    ):
        pytest.fail("macOS has no isolation yet; the smoke must refuse to start")


def windows_bundle(root: Path) -> tuple[Path, Path, Path]:
    bundle = make_bundle(root)
    launcher = bundle / "invsys-desktop.exe"
    helper = bundle / "_internal" / "PySide6" / "QtWebEngineProcess.exe"
    helper.parent.mkdir(parents=True)
    for program in (launcher, helper):
        program.write_bytes(b"MZ")
    return bundle, launcher, helper


def firewall_profiles(*states: str) -> str:
    """Output of `netsh advfirewall show allprofiles state` (Domain, Private, Public)."""
    return "".join(
        f"{profile} Profile Settings:\n{'-' * 70}\nState                                 {state}\n\n"
        for profile, state in zip(("Domain", "Private", "Public"), states, strict=True)
    )


def firewall_state(command: list[str]) -> str | None:
    """The state query answered for an enabled firewall; None for other commands."""
    return firewall_profiles("ON", "ON", "ON") if command[2:4] == ["show", "allprofiles"] else None


def test_windows_isolation_blocks_outbound_traffic_of_every_bundled_program(tmp_path):
    bundle, launcher, helper = windows_bundle(tmp_path)
    commands: list[list[str]] = []

    def fake_netsh(command: list[str]) -> str:
        commands.append(command)
        return firewall_state(command) or "Rule Name: invsys-package-smoke\n" * 2

    with package_bundle.network_isolation(bundle, True, "win32", fake_netsh) as record:
        assert record["mechanism"] == "windows-firewall-outbound-block"
        assert record["firewall_profiles"] == ["ON", "ON", "ON"]
        assert record["blocked_programs"] == sorted([str(launcher), str(helper)])
        added = [command for command in commands if "add" in command]
        assert sorted(command[-1] for command in added) == [
            f"program={program}" for program in sorted([launcher, helper])
        ]
        for command in added:
            assert {"dir=out", "action=block", "enable=yes"} <= set(command)
        assert "delete" not in commands[-1]
    # The rules never outlive the smoke.
    assert commands[-1][:6] == [
        "netsh",
        "advfirewall",
        "firewall",
        "delete",
        "rule",
        f"name={package_bundle.FIREWALL_RULE}",
    ]


def test_windows_isolation_removes_its_rules_when_the_smoke_fails(tmp_path):
    bundle, _, _ = windows_bundle(tmp_path)
    commands: list[list[str]] = []

    def fake_netsh(command: list[str]) -> str:
        commands.append(command)
        return firewall_state(command) or "Rule Name: x\n" * 2

    def failed_smoke():
        with package_bundle.network_isolation(bundle, True, "win32", fake_netsh):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        failed_smoke()
    assert "delete" in commands[-1]


def test_a_rule_that_windows_does_not_list_fails_the_isolation(tmp_path, capsys):
    bundle, _, _ = windows_bundle(tmp_path)

    def one_rule_listed(command: list[str]) -> str:
        return firewall_state(command) or "Rule Name: x\n"

    with (
        pytest.raises(PackagingError, match="Expected 2 outbound block rules"),
        package_bundle.network_isolation(bundle, True, "win32", one_rule_listed),
    ):
        pytest.fail("the isolation was not verified")
    assert capsys.readouterr().err == ""


def test_a_disabled_firewall_profile_cannot_isolate_the_smoke(tmp_path):
    bundle, _, _ = windows_bundle(tmp_path)
    commands: list[list[str]] = []

    def public_off(command: list[str]) -> str:
        commands.append(command)
        if command[2:4] == ["show", "allprofiles"]:
            return firewall_profiles("ON", "ON", "OFF")
        return ""

    with (
        pytest.raises(PackagingError, match=r"Windows Firewall is off.*Set-NetFirewallProfile"),
        package_bundle.network_isolation(bundle, True, "win32", public_off),
    ):
        pytest.fail("block rules on a disabled firewall would prove nothing")
    assert not any("add" in command for command in commands)


def test_a_refused_firewall_change_is_a_readable_packaging_error(tmp_path, capsys):
    bundle, _, _ = windows_bundle(tmp_path)

    def refused(command: list[str]) -> str:
        state = firewall_state(command)
        if state is None:
            raise PackagingError("netsh refused: run from an elevated prompt")
        return state

    with (
        pytest.raises(PackagingError, match="elevated"),
        package_bundle.network_isolation(bundle, True, "win32", refused),
    ):
        pytest.fail("the isolation was not installed")
    # The failed clean-up is reported instead of raised over the original error.
    assert "could not remove the firewall rules" in capsys.readouterr().err


def test_netsh_failures_name_the_command_and_the_elevation_requirement(monkeypatch):
    class Result:
        returncode = 1
        stdout = "Access is denied."
        stderr = ""

    monkeypatch.setattr(package_bundle.subprocess, "run", lambda *_args, **_kwargs: Result())
    with pytest.raises(PackagingError, match=r"Access is denied.*administrator"):
        package_bundle.run_netsh(["netsh", "advfirewall", "firewall", "add", "rule"])


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in launcher is a POSIX script")
def test_a_launched_bundle_never_waits_for_an_operator_at_its_console(tmp_path):
    bundle = make_bundle(tmp_path)
    launcher = package_bundle.executable_path(bundle)
    launcher.write_text(
        f"#!{sys.executable}\nimport sys\nprint(repr(sys.stdin.read()))\n", encoding="utf-8"
    )
    launcher.chmod(0o755)
    run = package_bundle.run_bundle(bundle, [], tmp_path, {})
    assert run["exit_code"] == 0
    assert run["stdout"].strip() == "''"


def test_the_unmapped_drive_check_picks_a_letter_nothing_is_mapped_to():
    mapped = {"Z:\\", "Y:\\"}
    assert str(package_bundle.unused_drive(lambda root: str(root) in mapped)) == str(Path("X:\\"))
    assert package_bundle.unused_drive(lambda _root: True) is None


def test_unreadable_firewall_states_refuse_the_isolation(tmp_path):
    bundle, _, _ = windows_bundle(tmp_path)
    with (
        pytest.raises(PackagingError, match="Cannot read the Windows Firewall profile states"),
        package_bundle.network_isolation(bundle, True, "win32", lambda _command: "Zustand EIN\n"),
    ):
        pytest.fail("unknown firewall state must not count as offline")
