from __future__ import annotations

import gettext
import os

_translation = gettext.translation(
    "harmonia",
    localedir=os.environ.get("HARMONIA_LOCALE_DIR"),
    fallback=True,
)
_ = _translation.gettext
ngettext = _translation.ngettext
