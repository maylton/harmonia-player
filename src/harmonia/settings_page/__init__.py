"""The Preferences page, one module per group of settings."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from ..i18n import _  # noqa: E402
from .account import account_group  # noqa: E402
from .appearance import appearance_group  # noqa: E402
from .audio import audio_group  # noqa: E402
from .library import library_group  # noqa: E402
from .optional import cast_group, recognition_group, together_group  # noqa: E402
from .social import social_group  # noqa: E402
from .streaming import backup_group, streaming_group  # noqa: E402


def build_settings_page(window) -> Adw.PreferencesPage:
    page = Adw.PreferencesPage(title=_("Preferências"))
    page.add_css_class("app-preferences")
    groups = (
        account_group,
        appearance_group,
        streaming_group,
        library_group,
        backup_group,
        social_group,
        together_group,
        recognition_group,
        cast_group,
        audio_group,
    )
    for group in groups:
        page.add(group(window))
    return page
