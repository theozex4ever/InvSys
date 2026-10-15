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
import sys
import tarfile
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
    bundle = tmp_path / "invsys-desktop"
    bundle.mkdir()
    launcher = bundle / "invsys-desktop"
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
    bundle = tmp_path / "invsys-desktop"
    bundle.mkdir()
    launcher = bundle / "invsys-desktop"
    launcher.write_text("#!/bin/sh\necho started\nexec sleep 30\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setattr(package_bundle, "RUN_TIMEOUT_SECONDS", 1)
    run = package_bundle.run_bundle(bundle, [], tmp_path, {})
    assert run["exit_code"] == -1
    assert "Timed out after 1 s" in run["stderr"]
    assert run["stdout"].strip() == "started"
