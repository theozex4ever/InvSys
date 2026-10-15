"""Argument guards of the pywebview desktop launcher.

These run without a display or pywebview window: every case exits during
argument validation, before any database is opened or GUI is started.
"""

import sys

import pytest

from inventory_control import desktop


def run_launcher(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["inventory_desktop.py", *args])
    with pytest.raises(SystemExit) as exit_info:
        desktop.main()
    return exit_info.value.code


def test_smoke_check_requires_an_explicit_database(monkeypatch, capsys):
    assert run_launcher(monkeypatch, "--smoke-check") == 2
    assert "--smoke-check requires an explicit disposable --database" in capsys.readouterr().err


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
