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
