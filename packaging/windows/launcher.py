"""Entry point of the frozen Windows build (PyInstaller)."""

import os
import sys
from pathlib import Path

bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Harmonia"
local.mkdir(parents=True, exist_ok=True)
# PyInstaller's GStreamer hook keeps the plugin registry inside the bundle,
# which is read-only under Program Files; a stale or unwritable registry makes
# every start rescan the plugins.
os.environ["GST_REGISTRY"] = str(local / "gstreamer-registry.bin")
os.environ.setdefault("HARMONIA_LOCALE_DIR", str(bundle / "share" / "locale"))

from harmonia.frontend import main  # noqa: E402

sys.exit(main())
