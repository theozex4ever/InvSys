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
evidence record. Everything here is shared by every platform; the platform
differences are the executable name, a few freeze arguments, the archive format
(``.tar.gz``, ``.zip`` on Windows) and how the offline smoke isolates the network
(an empty namespace on Linux, outbound firewall rules on Windows).
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
import zipfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
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
# Name of the temporary Windows Firewall rules of an isolated smoke (removed afterwards).
FIREWALL_RULE = "invsys-package-smoke"
# pywebview's Windows backends need the .NET runtime; the bundle uses its Qt backend only.
WINDOWS_EXCLUDED_MODULES = ("clr", "clr_loader", "pythonnet")


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


def executable_path(bundle: Path, platform_name: str = sys.platform) -> Path:
    return bundle / (f"{APP_NAME}.exe" if platform_name == "win32" else APP_NAME)


def archive_name(platform_name: str = sys.platform, machine: str | None = None) -> str:
    suffix = "zip" if platform_name == "win32" else "tar.gz"
    return f"{APP_NAME}-{platform_name}-{(machine or platform.machine()).lower()}.{suffix}"


def pyinstaller_args(
    root: Path, assets: Path, dist: Path, work: Path, platform_name: str = sys.platform
) -> list[str]:
    """Arguments of the one shared freeze; the data separator is the platform's.

    The Windows executable stays a console program on purpose: startup failures
    (missing ``--database``, unusable inventory folder) are reported on stderr, which
    a windowed executable would silently drop.
    """
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
    excluded = ["PyQt5", "PyQt6", "PySide2", "tkinter", "gi"]
    if platform_name == "win32":
        # UPX-packed executables trigger antivirus heuristics and add nothing offline.
        args.append("--noupx")
        excluded += WINDOWS_EXCLUDED_MODULES
    for module in excluded:
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
    """Archive the bundle (zip for ``.zip``, else gzipped tar), so only content differs."""
    if archive.suffix == ".zip":
        _make_zip(bundle, archive)
    else:
        _make_tar(bundle, archive)


def _make_zip(bundle: Path, archive: Path) -> None:
    """Zip with sorted entries, a fixed timestamp and fixed modes (Windows has no mode bits)."""
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(bundle.rglob("*")):
            name = (Path(bundle.name) / path.relative_to(bundle)).as_posix()
            directory = path.is_dir()
            info = zipfile.ZipInfo(name + "/" if directory else name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o40755 << 16 | 0x10) if directory else (0o100644 << 16)
            if directory:
                zipped.writestr(info, b"")
            else:
                with path.open("rb") as source, zipped.open(info, "w") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)


def _make_tar(bundle: Path, archive: Path) -> None:
    """Gzipped tar with sorted entries and neutral ownership."""

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
        target = dist / archive_name()
        make_archive(bundle, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        print(f"Archive: {target} ({target.stat().st_size} bytes, sha256 {digest})")
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
    if isolate_network and sys.platform.startswith("linux"):
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
    # Elsewhere the isolation is installed around the whole smoke by network_isolation().
    started = time.monotonic()
    try:
        # The command is the bundle under test plus fixed smoke arguments.
        result = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            env=env,
            # No operator: a failed launch must not wait for Enter at its console.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            # The launcher's own messages; Windows consoles would otherwise decode as cp1252.
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RUN_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # A hung bundle is a failed run with evidence, not a lost record.
        return {
            "arguments": arguments,
            "exit_code": -1,
            "seconds": RUN_TIMEOUT_SECONDS,
            "stdout": _text(exc.stdout),
            "stderr": _text(exc.stderr) + f"\nTimed out after {RUN_TIMEOUT_SECONDS} s.",
        }
    return {
        "arguments": arguments,
        "exit_code": result.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _text(output: str | bytes | None) -> str:
    return output.decode(errors="replace") if isinstance(output, bytes) else output or ""


def excerpt(text: str) -> list[str]:
    return text.strip().splitlines()[-EXCERPT_LINES:]


def run_netsh(command: list[str]) -> str:
    """Run one fixed ``netsh`` command and return its output; a refusal is readable."""
    try:
        # Fixed binary and arguments built from the bundle's own file names, no shell.
        result = subprocess.run(  # noqa: S603
            command, capture_output=True, text=True, timeout=60, check=False
        )
    except OSError as exc:
        raise PackagingError(f"Cannot run netsh: {exc}") from exc
    if result.returncode != 0:
        raise PackagingError(
            f"`{' '.join(command[:5])}` failed (status {result.returncode}): "
            f"{(result.stdout + result.stderr).strip()}. "
            "Blocking the network needs an elevated (administrator) prompt."
        )
    return result.stdout


def firewall_profiles(output: str) -> list[str]:
    """Profile states (Domain, Private, Public) from ``netsh advfirewall show ... state``."""
    return [line.split()[-1].upper() for line in output.splitlines() if line.startswith("State ")]


@contextmanager
def network_isolation(
    bundle: Path,
    enabled: bool,
    platform_name: str = sys.platform,
    netsh: Callable[[list[str]], str] = run_netsh,
) -> Iterator[dict[str, Any]]:
    """Make any network use by the bundle fail while the smoke runs.

    Linux isolates each launch in an empty network namespace (``run_bundle``); Windows
    blocks outbound traffic of every program in the bundle with Firewall rules that
    are removed afterwards. Windows exempts loopback from the firewall, so a local
    HTTP server is caught by the launcher's own "no HTTP server" check instead.
    """
    if not enabled:
        yield {"enabled": False}
        return
    if platform_name.startswith("linux"):
        yield {"enabled": True, "mechanism": "linux-empty-network-namespace"}
        return
    if platform_name != "win32":
        raise PackagingError(f"--isolate-network is not available on {platform_name}.")
    programs = sorted(str(path) for path in bundle.rglob("*.exe"))
    base = ["netsh", "advfirewall", "firewall"]
    profiles = firewall_profiles(netsh(["netsh", "advfirewall", "show", "allprofiles", "state"]))
    if not profiles:
        raise PackagingError(
            "Cannot read the Windows Firewall profile states from `netsh advfirewall show "
            "allprofiles state` (English output expected); the smoke would not be offline."
        )
    if any(state != "ON" for state in profiles):
        # Block rules on a disabled profile are ignored: the smoke would not be offline.
        raise PackagingError(
            f"Windows Firewall is off (profile states: {', '.join(profiles)}), "
            "so outbound block rules would not isolate the smoke. Enable it with "
            "`Set-NetFirewallProfile -All -Enabled True` from an elevated prompt."
        )
    try:
        for program in programs:
            netsh(
                [
                    *base,
                    "add",
                    "rule",
                    f"name={FIREWALL_RULE}",
                    "dir=out",
                    "action=block",
                    "enable=yes",
                    "profile=any",
                    f"program={program}",
                ]
            )
        shown = netsh([*base, "show", "rule", f"name={FIREWALL_RULE}"])
        if shown.count("Rule Name:") != len(programs):
            raise PackagingError(
                f"Expected {len(programs)} outbound block rules, Windows Firewall lists "
                f"{shown.count('Rule Name:')}."
            )
        yield {
            "enabled": True,
            "mechanism": "windows-firewall-outbound-block",
            "firewall_profiles": profiles,
            "blocked_programs": programs,
        }
    finally:
        try:
            netsh([*base, "delete", "rule", f"name={FIREWALL_RULE}"])
        except PackagingError as exc:
            print(f"package_bundle: could not remove the firewall rules: {exc}", file=sys.stderr)


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


def transaction_ids(database: Path) -> set[int]:
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        return {row[0] for row in connection.execute("SELECT id FROM inventory_transactions")}


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


def unused_drive(exists: Callable[[Path], bool] = Path.exists) -> Path | None:
    """Root of a Windows drive letter nothing is mapped to, searched from Z: down."""
    return next(
        (
            Path(f"{letter}:\\")
            for letter in "ZYXWVUTSRQPONMLKJIHGFED"
            if not exists(Path(f"{letter}:\\"))
        ),
        None,
    )


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
    directory = workdir / "directory" / "inventory.db"
    directory.mkdir(parents=True)
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
            "database-path-is-a-directory",
            1,
            "Cannot open the inventory database",
            ["--database", str(directory)],
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
    drive = unused_drive() if sys.platform == "win32" else None
    if drive is not None:
        # A drive letter that is not mapped, e.g. a removed USB stick or network share.
        checks.append(
            (
                "database-drive-does-not-exist",
                1,
                "Cannot open the inventory database",
                ["--database", str(drive / "invsys" / "inventory.db")],
                bundle,
            )
        )
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


def windows_machine_details() -> dict[str, Any]:
    """CPU name and installed memory from the Windows registry and kernel."""
    details: dict[str, Any] = {"os": f"Windows {platform.version()} ({platform.win32_edition()})"}
    if sys.platform == "win32":
        import ctypes
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            details["cpu"] = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()

        class MemoryStatus(ctypes.Structure):
            _fields_ = (
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            )

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        details["memory"] = f"{status.total_physical // 1024} kB"
    return details


def machine_record() -> dict[str, Any]:
    record: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "libc": " ".join(platform.libc_ver()),
        "logical_cpus": os.cpu_count(),
        "display": os.environ.get("XDG_SESSION_TYPE") or os.environ.get("DISPLAY") or "none",
    }
    if sys.platform == "win32":
        record["display"] = "windows-desktop-session"
        record.pop("libc")
        record.update(windows_machine_details())
        return record
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
    # Child launches use a separate cwd; keep every selected path anchored to this one.
    bundle, assets, workdir, evidence = (
        path.resolve() for path in (bundle, assets, workdir, evidence)
    )
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
        "runs": [],
    }
    with network_isolation(bundle, isolate_network) as isolation:
        record["network_isolation"] = isolation
        ok = run_checks(bundle, workdir, env, isolate_network, record)
    return finish_smoke(record, ok, evidence)


def run_checks(
    bundle: Path, workdir: Path, env: dict[str, str], isolate_network: bool, record: dict[str, Any]
) -> bool:
    """Failure checks, then two native runs of the bundle against one inventory."""
    record["failure_checks"] = failure_checks(bundle, workdir, env, isolate_network)
    database = workdir / "inventory" / "inventory.db"
    ok = all(check["passed"] for check in record["failure_checks"])
    first_ids: set[int] = set()
    ids: set[int] = set()
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
        counts = database_counts(database) if database.is_file() else {}
        ids = transaction_ids(database) if database.is_file() else set()
        backed_up: int | None = None
        if number == 1:
            # A fresh inventory has nothing to back up at startup.
            run_ok = run_ok and not backups
        else:
            run_ok = run_ok and bool(backups)
            if backups:
                # The startup backup must hold exactly what run 1 left behind.
                copy = database_counts(database.parent / "backups" / backups[-1])
                backed_up = int(copy["inventory_transactions"])
                run_ok = run_ok and copy["integrity_check"] == "ok"
                run_ok = run_ok and backed_up == len(first_ids)
        first_ids = first_ids or ids
        record["runs"].append(
            {
                "run": number,
                "exit_code": run["exit_code"],
                "seconds": run["seconds"],
                "stdout": excerpt(run["stdout"]),
                "stderr": excerpt(run["stderr"]),
                "startup_backups": backups,
                "startup_backup_transactions": backed_up,
                "database": counts,
                "passed": run_ok,
            }
        )
        ok = ok and run_ok
    # Every ledger row run 1 wrote must still be there after the restart.
    persisted = (
        bool(first_ids)
        and first_ids <= ids
        and record["runs"][1]["database"].get("integrity_check") == "ok"
    )
    unexpected = Path(env["INVSYS_HOME"])
    record["restart_persistence"] = {"passed": persisted}
    record["no_writes_outside_selected_inventory"] = {"passed": not unexpected.exists()}
    return ok and persisted and not unexpected.exists()


def finish_smoke(record: dict[str, Any], ok: bool, evidence: Path) -> bool:
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
    build_parser = commands.add_parser("build")
    smoke_parser = commands.add_parser("smoke")
    for sub in (build_parser, smoke_parser):
        sub.add_argument("--assets", type=Path, default=ROOT / "frontend" / "dist")
    build_parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    build_parser.add_argument("--work", type=Path, default=ROOT / "build")
    build_parser.add_argument("--no-archive", action="store_true")
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
