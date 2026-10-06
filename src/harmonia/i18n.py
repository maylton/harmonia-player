from __future__ import annotations

import gettext
import os

from . import host

_translation = gettext.translation(
    "harmonia",
    localedir=os.environ.get("HARMONIA_LOCALE_DIR"),
    languages=host.translation_languages(),
    fallback=True,
)
_ = _translation.gettext
ngettext = _translation.ngettext
