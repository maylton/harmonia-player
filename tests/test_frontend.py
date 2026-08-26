import sys
from pathlib import Path
from types import ModuleType

from harmonia import frontend


def test_kde_selects_qt_when_pyside_is_available(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.delenv("HARMONIA_FRONTEND", raising=False)
    monkeypatch.setattr(frontend, "qt_frontend_available", lambda: True)

    assert frontend.selected_frontend([]) == "qt"


def test_kde_falls_back_to_gtk_without_pyside(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.delenv("HARMONIA_FRONTEND", raising=False)
    monkeypatch.setattr(frontend, "qt_frontend_available", lambda: False)

    assert frontend.selected_frontend([]) == "gtk"


def test_non_kde_defaults_to_gtk(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.delenv("HARMONIA_FRONTEND", raising=False)
    monkeypatch.setattr(frontend, "qt_frontend_available", lambda: True)

    assert frontend.selected_frontend([]) == "gtk"


def test_cli_can_force_frontend(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.delenv("HARMONIA_FRONTEND", raising=False)
    monkeypatch.setattr(frontend, "qt_frontend_available", lambda: True)

    assert frontend.selected_frontend(["--gtk"]) == "gtk"
    assert frontend.selected_frontend(["--qt"]) == "qt"


def test_environment_can_force_frontend(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setenv("HARMONIA_FRONTEND", "qt")

    assert frontend.selected_frontend([]) == "qt"


def test_python_module_entrypoint_uses_frontend_selector():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "harmonia" / "__main__.py").read_text(encoding="utf-8")

    assert "from .frontend import main" in source
    assert "from .app import main" not in source


def test_qt_startup_failure_falls_back_to_gtk_when_not_forced(monkeypatch):
    qt_module = ModuleType("harmonia.qt_app")

    def fail_qt() -> int:
        raise RuntimeError("QML failed")

    qt_module.main = fail_qt
    gtk_module = ModuleType("harmonia.app")
    gtk_module.main = lambda: 17

    monkeypatch.setitem(sys.modules, "harmonia.qt_app", qt_module)
    monkeypatch.setitem(sys.modules, "harmonia.app", gtk_module)
    monkeypatch.setattr(frontend, "selected_frontend", lambda: "qt")
    monkeypatch.setattr(sys, "argv", ["harmonia"])
    monkeypatch.delenv("HARMONIA_FRONTEND", raising=False)

    assert frontend.main() == 17


def test_forced_qt_startup_failure_is_not_hidden(monkeypatch):
    qt_module = ModuleType("harmonia.qt_app")

    def fail_qt() -> int:
        raise RuntimeError("QML failed")

    qt_module.main = fail_qt
    monkeypatch.setitem(sys.modules, "harmonia.qt_app", qt_module)
    monkeypatch.setattr(frontend, "selected_frontend", lambda: "qt")
    monkeypatch.setattr(sys, "argv", ["harmonia", "--qt"])
    monkeypatch.delenv("HARMONIA_FRONTEND", raising=False)

    try:
        frontend.main()
    except RuntimeError as exc:
        assert str(exc) == "QML failed"
    else:
        raise AssertionError("forced Qt startup failure must be visible")
