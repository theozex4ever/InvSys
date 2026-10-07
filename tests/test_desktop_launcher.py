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


def test_missing_pywebview_is_reported_before_launch(monkeypatch, capsys, tmp_path):
    for name in ("index.html", "app.js", "style.css"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    monkeypatch.setattr(desktop.importlib.util, "find_spec", lambda _name: None)
    database = tmp_path / "inventory.db"
    code = run_launcher(monkeypatch, "--database", str(database), "--assets", str(tmp_path))
    assert code == 2
    assert "Install requirements-desktop.txt" in capsys.readouterr().err
    assert not database.exists()
