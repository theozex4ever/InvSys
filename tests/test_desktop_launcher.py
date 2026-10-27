"""Argument guards of the pywebview desktop launcher.

These run without a display or pywebview window: every case exits during
argument validation, before any database is opened or GUI is started, or
replaces the launch to check how a packaged failure stays readable.
"""

import sys

import pytest

from inventory_control import desktop

OWNS_CONSOLE = desktop._owns_console


@pytest.fixture(autouse=True)
def shared_console(monkeypatch):
    """The test process shares its console, as a bundle started from a terminal does."""
    monkeypatch.setattr(desktop, "_owns_console", lambda: False)


def run_launcher(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["inventory_desktop.py", *args])
    with pytest.raises(SystemExit) as exit_info:
        desktop.main()
    return exit_info.value.code


def test_smoke_check_requires_an_explicit_database(monkeypatch, capsys):
    assert run_launcher(monkeypatch, "--smoke-check") == 2
    assert "--smoke-check requires an explicit disposable --database" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ("--perf-check", "launch"),
        ("--perf-check", "launch", "--database", "inventory.db"),
        ("--perf-check", "launch", "--perf-output", "result.json"),
        (
            "--perf-check",
            "launch",
            "--database",
            "x.db",
            "--perf-output",
            "r.json",
            "--smoke-check",
        ),
    ],
)
def test_perf_check_needs_a_disposable_database_and_an_output_file(monkeypatch, capsys, arguments):
    assert run_launcher(monkeypatch, *arguments) == 2
    assert "--perf-check needs a disposable --database and --perf-output" in capsys.readouterr().err


def test_perf_check_only_accepts_the_two_probe_modes(monkeypatch, capsys):
    assert run_launcher(monkeypatch, "--perf-check", "everything") == 2
    assert "invalid choice" in capsys.readouterr().err


def test_packaged_launch_requires_an_explicit_database(monkeypatch, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert run_launcher(monkeypatch) == 2
    assert "Packaged launch requires --database" in capsys.readouterr().err


def test_missing_built_assets_are_reported_before_launch(monkeypatch, capsys, tmp_path):
    database = tmp_path / "inventory.db"
    code = run_launcher(monkeypatch, "--database", str(database), "--assets", str(tmp_path))
    assert code == 2
    assert "Built frontend assets are missing" in capsys.readouterr().err
    assert not database.exists()


def test_missing_assets_in_a_bundle_point_at_the_bundle_not_the_build(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    code = run_launcher(monkeypatch, "--database", str(tmp_path / "inventory.db"))
    error = capsys.readouterr().err
    assert code == 2
    assert "bundle is incomplete" in error
    assert str(tmp_path / "bundle" / "frontend" / "dist") in error
    assert "npm" not in error


def test_missing_pywebview_is_reported_before_launch(monkeypatch, capsys, tmp_path):
    for name in ("index.html", "app.js", "style.css"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    monkeypatch.setattr(desktop.importlib.util, "find_spec", lambda _name: None)
    database = tmp_path / "inventory.db"
    code = run_launcher(monkeypatch, "--database", str(database), "--assets", str(tmp_path))
    assert code == 2
    assert "Install requirements-desktop.txt" in capsys.readouterr().err
    assert not database.exists()


def write_assets(directory):
    for name in ("index.html", "app.js", "style.css"):
        (directory / name).write_text("x", encoding="utf-8")


def test_database_folder_that_is_not_a_directory_is_reported_readably(
    monkeypatch, capsys, tmp_path
):
    write_assets(tmp_path)
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("file", encoding="utf-8")
    code = run_launcher(
        monkeypatch, "--database", str(blocker / "inventory.db"), "--assets", str(tmp_path)
    )
    error = capsys.readouterr().err
    assert code == 1
    assert "Cannot open the inventory database" in error
    assert str(blocker / "inventory.db") in error
    assert "Traceback" not in error
    assert not (tmp_path / "inventory.db").exists()


def test_unreadable_database_file_is_reported_readably(monkeypatch, capsys, tmp_path):
    write_assets(tmp_path)
    database = tmp_path / "data" / "inventory.db"
    database.parent.mkdir()
    database.write_text("this is not an SQLite database", encoding="utf-8")
    code = run_launcher(monkeypatch, "--database", str(database), "--assets", str(tmp_path))
    error = capsys.readouterr().err
    assert code == 1
    assert "Cannot open the inventory database" in error
    assert "not a database" in error
    assert "Traceback" not in error
    assert database.read_text(encoding="utf-8") == "this is not an SQLite database"


def test_database_path_that_is_a_directory_is_reported_readably(monkeypatch, capsys, tmp_path):
    write_assets(tmp_path)
    database = tmp_path / "inventory.db"
    database.mkdir()
    code = run_launcher(monkeypatch, "--database", str(database), "--assets", str(tmp_path))
    assert code == 1
    assert "Cannot open the inventory database" in capsys.readouterr().err


def test_a_bundle_started_from_explorer_keeps_its_failure_on_screen(monkeypatch, capsys):
    # Double-clicked on Windows, the bundle owns its console, which closes on exit.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop, "_owns_console", lambda: True)
    prompts = []
    monkeypatch.setattr("builtins.input", prompts.append)
    assert run_launcher(monkeypatch) == 2
    assert "Packaged launch requires --database" in capsys.readouterr().err
    assert prompts == ["Press Enter to close this window."]


def test_a_bundle_without_an_operator_at_its_console_exits_at_once(monkeypatch, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop, "_owns_console", lambda: True)

    def no_input(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    assert run_launcher(monkeypatch) == 2
    assert "Packaged launch requires --database" in capsys.readouterr().err


@pytest.mark.parametrize("frozen, owns_console", [(True, False), (False, True)])
def test_failures_in_a_shared_terminal_or_from_source_do_not_wait(
    monkeypatch, capsys, frozen, owns_console
):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(desktop, "_owns_console", lambda: owns_console)
    monkeypatch.setattr("builtins.input", lambda _prompt: pytest.fail("waited for Enter"))
    assert run_launcher(monkeypatch, "--smoke-check") == 2
    capsys.readouterr()


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_only_a_windows_process_can_own_a_closing_console(platform):
    assert OWNS_CONSOLE(platform) is False


def test_an_unexpected_failure_is_shown_before_the_bundle_waits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop, "_owns_console", lambda: True)

    def broken():
        raise RuntimeError("Qt WebEngine could not start")

    monkeypatch.setattr(desktop, "_launch", broken)
    shown = []
    monkeypatch.setattr("builtins.input", lambda _prompt: shown.append(capsys.readouterr().err))
    with pytest.raises(SystemExit) as exit_info:
        desktop.main()
    assert exit_info.value.code == 1
    assert "RuntimeError: Qt WebEngine could not start" in shown[0]


def test_a_successful_launch_returns_its_status_without_waiting(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop, "_owns_console", lambda: True)
    monkeypatch.setattr(desktop, "_launch", lambda: 0)
    monkeypatch.setattr("builtins.input", lambda _prompt: pytest.fail("waited for Enter"))
    assert desktop.main() == 0
