#!/usr/bin/env python3
"""Build, verify and smoke-test the standalone offline desktop bundle.

    python scripts/package_bundle.py build  --assets frontend/dist --dist dist
    python scripts/package_bundle.py smoke  --bundle dist/invsys-desktop \
        --assets frontend/dist --workdir /tmp/invsys-package --evidence evidence.json

``build`` freezes ``inventory_desktop.py`` with PyInstaller (one directory, Qt
WebEngine included), writes ``bundle-manifest.json`` beside the executable and
archives the directory. ``smoke`` proves the *frozen* bundle: its assets are
byte-identical to the build output, startup failures are readable, and the
native workflow smoke passes twice against one disposable inventory with
restart persistence and a startup backup on the second launch. It writes a JSON
evidence record. Everything here is platform-neutral; Windows and macOS only
need to extend ``pyinstaller_args``, ``executable_path`` and ``make_archive``.
"""

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_NAME = "invsys-desktop"
MANIFEST_NAME = "bundle-manifest.json"
# Keep in step with inventory_control.desktop.REQUIRED_ASSETS (a test enforces it).
REQUIRED_ASSETS = ("index.html", "app.js", "style.css")
BUNDLED_ASSETS = Path("frontend") / "dist"
ROOT = Path(__file__).resolve().parent.parent
# Distributions whose exact versions are recorded in the manifest.
RECORDED_PACKAGES = ("pyinstaller", "pyinstaller-hooks-contrib", "PySide6", "pywebview", "QtPy")
RUN_TIMEOUT_SECONDS = 300
EXCERPT_LINES = 12


class PackagingError(Exception):
    """A readable reason the bundle cannot be built, trusted or run."""


# ---------------------------------------------------------------- assets


def asset_hashes(directory: Path) -> dict[str, str]:
    """SHA-256 of every file under ``directory``, keyed by posix-style relative path."""
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def require_built_assets(directory: Path) -> dict[str, str]:
    missing = [name for name in REQUIRED_ASSETS if not (directory / name).is_file()]
    if missing:
        raise PackagingError(
            f"Built frontend assets are missing from {directory}: {', '.join(missing)}. "
            "Run `npm ci && npm run build:assets && npm run check:dist` in frontend/ first."
        )
    return asset_hashes(directory)


def find_bundled_assets(bundle: Path) -> Path:
    found = sorted(path.parent for path in bundle.rglob("index.html") if _is_asset_dir(path.parent))
    if len(found) != 1:
        raise PackagingError(
            f"Expected exactly one bundled frontend/dist in {bundle}; found {len(found)}."
        )
    return found[0]


def _is_asset_dir(directory: Path) -> bool:
    return directory.parts[-2:] == BUNDLED_ASSETS.parts


def compare_assets(expected: dict[str, str], bundled: dict[str, str]) -> list[str]:
    problems = [f"{name} is missing from the bundle" for name in sorted(expected.keys() - bundled)]
    problems += [f"{name} is not part of the build" for name in sorted(bundled.keys() - expected)]
    problems += [
        f"{name} differs from the build output"
        for name in sorted(expected.keys() & bundled.keys())
        if expected[name] != bundled[name]
    ]
    return problems


def verify_assets(bundle: Path, assets: Path) -> dict[str, str]:
    expected = require_built_assets(assets)
    problems = compare_assets(expected, asset_hashes(find_bundled_assets(bundle)))
    if problems:
        raise PackagingError("Bundled assets are not the built assets: " + "; ".join(problems))
    return expected


# ---------------------------------------------------------------- build


def executable_path(bundle: Path) -> Path:
    return bundle / (f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME)


def pyinstaller_args(root: Path, assets: Path, dist: Path, work: Path) -> list[str]:
    """Arguments of the one shared freeze; the data separator is the platform's."""
    args = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        APP_NAME,
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        "--add-data",
        f"{assets}{os.pathsep}{BUNDLED_ASSETS.as_posix()}",
        "--hidden-import",
        "webview.platforms.qt",
        "--hidden-import",
        "PySide6.QtWebEngineWidgets",
        "--hidden-import",
        "PySide6.QtWebEngineCore",
    ]
    for module in ("PyQt5", "PyQt6", "PySide2", "tkinter", "gi"):
        args += ["--exclude-module", module]
    return [*args, str(root / "inventory_desktop.py")]


def recorded_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in RECORDED_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def source_revision(root: Path) -> dict[str, Any]:
    try:
        commit = _git(root, "rev-parse", "HEAD")
        dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "unknown", "uncommitted_changes": None}
    return {"commit": commit, "uncommitted_changes": dirty}


def _git(root: Path, *args: str) -> str:
    # Fixed git binary lookup and fixed arguments; no operator input reaches the command.
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def build_manifest(assets: dict[str, str], root: Path) -> dict[str, Any]:
    return {
        "app": APP_NAME,
        "source": source_revision(root),
        "python": platform.python_version(),
        "platform": f"{sys.platform}-{platform.machine()}",
        "packages": recorded_versions(),
        "assets": assets,
    }


def make_archive(bundle: Path, archive: Path) -> None:
    """Gzipped tar with sorted entries and neutral ownership, so only content differs."""

    def neutral(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with (
        archive.open("wb") as raw,
        # The gzip header would otherwise embed the build time and the archive name.
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for path in [bundle, *sorted(bundle.rglob("*"))]:
            tar.add(
                path,
                arcname=(Path(bundle.name) / path.relative_to(bundle)).as_posix(),
                recursive=False,
                filter=neutral,
            )


def build(assets: Path, dist: Path, work: Path, archive: bool) -> Path:
    built_assets = require_built_assets(assets)
    bundle = dist / APP_NAME
    if bundle.exists():
        shutil.rmtree(bundle)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        *pyinstaller_args(ROOT, assets.resolve(), dist.resolve(), work.resolve()),
    ]
    # The interpreter running this script plus fixed, build-derived arguments.
    if subprocess.run(command, check=False).returncode != 0:  # noqa: S603
        raise PackagingError(
            "PyInstaller failed. Install the locked toolchain with "
            "`pip install --require-hashes -r requirements-package.lock.txt`."
        )
    if not executable_path(bundle).is_file():
        raise PackagingError(f"PyInstaller finished without producing {executable_path(bundle)}.")
    verify_assets(bundle, assets)
    manifest = build_manifest(built_assets, ROOT)
    (bundle / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Bundle: {bundle}")
    if archive:
        target = dist / f"{APP_NAME}-{sys.platform}-{platform.machine().lower()}.tar.gz"
        make_archive(bundle, target)
        print(f"Archive: {target} ({target.stat().st_size} bytes)")
    return bundle


# ---------------------------------------------------------------- smoke


def run_bundle(
    bundle: Path,
    args: Iterable[str],
    cwd: Path,
    env: dict[str, str],
    isolate_network: bool = False,
) -> dict[str, Any]:
    arguments = list(args)
    command = [str(executable_path(bundle)), *arguments]
    if isolate_network:
        # A fresh network namespace has no interface at all, not even loopback: any
        # attempt to reach a server, CDN or inventory service fails outright.
        # The current user stays mapped to itself: Chromium refuses to run as root.
        command = [
            "unshare",
            "--net",
            f"--map-user={os.getuid()}",
            f"--map-group={os.getgid()}",
            *command,
        ]
    started = time.monotonic()
    try:
        # The command is the bundle under test plus fixed smoke arguments.
        result = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PackagingError(
            f"{' '.join(command)} did not finish within {RUN_TIMEOUT_SECONDS} s."
        ) from exc
    return {
        "arguments": arguments,
        "exit_code": result.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def excerpt(text: str) -> list[str]:
    return text.strip().splitlines()[-EXCERPT_LINES:]


def database_counts(database: Path) -> dict[str, int | str]:
    """Read-only view of what the runs left behind, independent of the application."""
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        counts: dict[str, int | str] = {
            "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0]
        }
        for table in ("parts", "inventory_transactions", "shipments"):
            # Fixed table names, never operator input.
            row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
            counts[table] = row[0]
    return counts


def startup_backups(database: Path) -> list[str]:
    return sorted(
        path.name for path in (database.parent / "backups").glob("inventory-*-startup.db")
    )


def hardlinked_copy(bundle: Path, target: Path) -> None:
    """Copy a bundle cheaply; deleting files from the copy never touches the original."""

    def link(source: str, destination: str) -> object:
        try:
            os.link(source, destination)
        except OSError:
            return shutil.copy2(source, destination)
        return destination

    shutil.copytree(bundle, target, symlinks=True, copy_function=link)


def failure_checks(
    bundle: Path, workdir: Path, env: dict[str, str], isolate_network: bool
) -> list[dict[str, Any]]:
    """Launches that must fail before any window opens, with a readable explanation."""
    cwd = workdir / "cwd"
    cwd.mkdir()
    blocker = workdir / "not-a-folder"
    blocker.write_text("a file where a folder is needed", encoding="utf-8")
    garbage = workdir / "garbage" / "inventory.db"
    garbage.parent.mkdir()
    garbage.write_text("not an SQLite database", encoding="utf-8")
    missing_db = workdir / "missing-assets" / "inventory.db"
    incomplete = workdir / "incomplete-bundle"
    hardlinked_copy(bundle, incomplete)
    shutil.rmtree(find_bundled_assets(incomplete))

    checks = [
        ("no-database-argument", 2, "Packaged launch requires --database", [], bundle),
        (
            "missing-bundled-assets",
            2,
            "bundle is incomplete",
            ["--database", str(missing_db)],
            incomplete,
        ),
        (
            "database-folder-is-a-file",
            1,
            "Cannot open the inventory database",
            ["--database", str(blocker / "inventory.db")],
            bundle,
        ),
        (
            "database-is-not-sqlite",
            1,
            "Cannot open the inventory database",
            ["--database", str(garbage)],
            bundle,
        ),
    ]
    results = []
    for name, code, message, args, target in checks:
        run = run_bundle(target, args, cwd, env, isolate_network)
        passed = (
            run["exit_code"] == code
            and message in run["stderr"]
            and "Traceback" not in run["stderr"]
        )
        results.append(
            {
                "name": name,
                "expected_exit_code": code,
                "exit_code": run["exit_code"],
                "stderr": excerpt(run["stderr"]),
                "passed": passed,
            }
        )
    untouched = (
        not missing_db.exists()
        and garbage.read_text(encoding="utf-8") == "not an SQLite database"
        and blocker.read_text(encoding="utf-8") == "a file where a folder is needed"
    )
    results.append({"name": "failed-launches-wrote-no-inventory", "passed": untouched})
    shutil.rmtree(incomplete)
    return results


def require_display() -> None:
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise PackagingError(
            "The native smoke needs a display. On a headless host run it under "
            "`xvfb-run -a -s '-screen 0 1920x1080x24'`."
        )


def machine_record() -> dict[str, Any]:
    record: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "libc": " ".join(platform.libc_ver()),
        "logical_cpus": os.cpu_count(),
        "display": os.environ.get("XDG_SESSION_TYPE") or os.environ.get("DISPLAY") or "none",
    }
    release = Path("/etc/os-release")
    cpuinfo = Path("/proc/cpuinfo")
    meminfo = Path("/proc/meminfo")
    for key, path, prefix in (
        ("os", release, "PRETTY_NAME="),
        ("cpu", cpuinfo, "model name"),
        ("memory", meminfo, "MemTotal:"),
    ):
        if path.is_file():
            line = next(
                (x for x in path.read_text(encoding="utf-8").splitlines() if x.startswith(prefix)),
                "",
            )
            record[key] = line.split("=" if key == "os" else ":", 1)[-1].strip().strip('"')
    return record


def bundle_record(bundle: Path) -> dict[str, Any]:
    files = [path for path in bundle.rglob("*") if path.is_file() and not path.is_symlink()]
    executable = executable_path(bundle)
    manifest_file = bundle / MANIFEST_NAME
    return {
        "directory": bundle.name,
        "file_count": len(files),
        "size_bytes": sum(path.stat().st_size for path in files),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "manifest": json.loads(manifest_file.read_text(encoding="utf-8"))
        if manifest_file.is_file()
        else None,
    }


def smoke(bundle: Path, assets: Path, workdir: Path, evidence: Path, isolate_network: bool) -> bool:
    if not executable_path(bundle).is_file():
        raise PackagingError(f"No bundle executable at {executable_path(bundle)}.")
    if workdir.exists() and any(workdir.iterdir()):
        raise PackagingError(f"--workdir {workdir} must be empty: the smoke writes real data.")
    require_display()
    workdir.mkdir(parents=True, exist_ok=True)
    verified = verify_assets(bundle, assets)
    # Any write to a default data location would land here, where it is detected.
    unexpected = workdir / "unexpected-home"
    env = {**os.environ, "INVSYS_HOME": str(unexpected)}
    record: dict[str, Any] = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": machine_record(),
        "bundle": bundle_record(bundle),
        "assets_verified": verified,
        "network_isolated": isolate_network,
        "failure_checks": failure_checks(bundle, workdir, env, isolate_network),
        "runs": [],
    }
    database = workdir / "inventory" / "inventory.db"
    ok = all(check["passed"] for check in record["failure_checks"])
    for number in (1, 2):
        run = run_bundle(
            bundle,
            ["--database", str(database), "--smoke-check"],
            workdir / "cwd",
            env,
            isolate_network,
        )
        backups = startup_backups(database) if database.is_file() else []
        run_ok = run["exit_code"] == 0 and "no HTTP server" in run["stdout"]
        if number == 2:
            run_ok = run_ok and bool(backups)
        counts = database_counts(database) if database.is_file() else {}
        record["runs"].append(
            {
                "run": number,
                "exit_code": run["exit_code"],
                "seconds": run["seconds"],
                "stdout": excerpt(run["stdout"]),
                "stderr": excerpt(run["stderr"]),
                "startup_backups": backups,
                "database": counts,
                "passed": run_ok,
            }
        )
        ok = ok and run_ok
    first, second = (run["database"] for run in record["runs"])
    persisted = (
        bool(first)
        and bool(second)
        and second["inventory_transactions"] >= first["inventory_transactions"] > 0
        and second["integrity_check"] == "ok"
    )
    record["restart_persistence"] = {"passed": persisted}
    record["no_writes_outside_selected_inventory"] = {"passed": not unexpected.exists()}
    ok = ok and persisted and not unexpected.exists()
    record["result"] = "passed" if ok else "failed"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Package smoke {record['result']}; evidence written to {evidence}")
    if not ok:
        print(json.dumps(record["failure_checks"] + record["runs"], indent=2), file=sys.stderr)
    return ok


# ---------------------------------------------------------------- command line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "smoke"):
        sub = commands.add_parser(name)
        sub.add_argument("--assets", type=Path, default=ROOT / "frontend" / "dist")
    build_parser = commands.choices["build"]
    build_parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    build_parser.add_argument("--work", type=Path, default=ROOT / "build")
    build_parser.add_argument("--no-archive", action="store_true")
    smoke_parser = commands.choices["smoke"]
    smoke_parser.add_argument("--bundle", type=Path, default=ROOT / "dist" / APP_NAME)
    smoke_parser.add_argument("--workdir", type=Path, required=True)
    smoke_parser.add_argument("--evidence", type=Path, required=True)
    smoke_parser.add_argument(
        "--isolate-network",
        action="store_true",
        help="Run the bundle in an empty Linux network namespace (util-linux unshare).",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build(args.assets, args.dist, args.work, archive=not args.no_archive)
            return 0
        return (
            0
            if smoke(args.bundle, args.assets, args.workdir, args.evidence, args.isolate_network)
            else 1
        )
    except PackagingError as exc:
        print(f"package_bundle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
