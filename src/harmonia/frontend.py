from __future__ import annotations

import importlib.util
import logging
import os
import sys

LOGGER = logging.getLogger(__name__)


def _desktop_tokens() -> set[str]:
    values = (
        os.environ.get("XDG_CURRENT_DESKTOP", ""),
        os.environ.get("XDG_SESSION_DESKTOP", ""),
        os.environ.get("DESKTOP_SESSION", ""),
    )
    tokens: set[str] = set()
    for value in values:
        normalized = value.replace(";", ":").replace("-", ":")
        tokens.update(part.strip().lower() for part in normalized.split(":") if part.strip())
    return tokens


def running_on_plasma() -> bool:
    tokens = _desktop_tokens()
    return bool(tokens.intersection({"kde", "plasma", "plasmawayland", "plasmax11"}))


def qt_frontend_available() -> bool:
    return importlib.util.find_spec("PySide6") is not None


def selected_frontend(argv: list[str] | None = None) -> str:
    args = argv if argv is not None else sys.argv[1:]
    if "--gtk" in args:
        return "gtk"
    if "--qt" in args:
        return "qt"
    if os.environ.get("HARMONIA_FRONTEND", "").lower() in {"gtk", "qt"}:
        return os.environ["HARMONIA_FRONTEND"].lower()
    return "qt" if running_on_plasma() and qt_frontend_available() else "gtk"


def main() -> int:
    frontend = selected_frontend()
    forced_qt = "--qt" in sys.argv[1:] or os.environ.get("HARMONIA_FRONTEND", "").lower() == "qt"
    sys.argv[:] = [arg for arg in sys.argv if arg not in {"--gtk", "--qt"}]

    if frontend == "qt":
        try:
            from .qt_app import main as qt_main

            return qt_main()
        except Exception:
            if forced_qt:
                raise
            LOGGER.exception("Qt/Kirigami frontend failed to start; falling back to GTK")

    from . import app as gtk_app

    window_class = getattr(gtk_app, "HarmoniaWindow", None)
    if window_class is not None:
        from .gtk_video import install_gtk_video

        install_gtk_video(window_class)
    return gtk_app.main()
