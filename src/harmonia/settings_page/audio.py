"""Preferences > Áudio: GStreamer processing and the sleep timer."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, GObject  # noqa: E402

from ..crossfade import CHOICES as CROSSFADE_CHOICES  # noqa: E402
from ..i18n import _  # noqa: E402
from .rows import combo_row, scale_row, switch_row  # noqa: E402


def audio_group(window) -> Adw.PreferencesGroup:
    preferences = window.preferences

    def changed(name: str):
        return lambda value: window._preference_changed(name, value, audio=True)

    group = Adw.PreferencesGroup(
        title=_("Áudio"),
        description=_("Processamento nativo em tempo real pelo GStreamer."),
    )
    group.add(
        combo_row(
            _("Equalizador"),
            [
                (_("Plano"), "flat"),
                (_("Graves"), "bass"),
                (_("Voz"), "vocal"),
                (_("Agudos"), "treble"),
            ],
            preferences.equalizer,
            changed("equalizer"),
        )
    )
    normalization = switch_row(
        _("Normalização de volume"),
        _("Iguala o volume das faixas com a medição do YouTube Music"),
        preferences.normalization,
        changed("normalization"),
    )
    group.add(normalization)
    level = combo_row(
        _("Nível do volume"),
        [(_("Suave"), "soft"), (_("Padrão"), "standard"), (_("Alto"), "loud")],
        preferences.normalization_level,
        changed("normalization_level"),
    )
    normalization.bind_property("active", level, "sensitive", GObject.BindingFlags.SYNC_CREATE)
    group.add(level)
    group.add(
        switch_row(
            _("Pular silêncio"),
            _("Remove trechos silenciosos longos"),
            preferences.skip_silence,
            changed("skip_silence"),
        )
    )
    group.add(
        combo_row(
            _("Transição entre faixas"),
            [
                (_("Desligada"), 0),
                *((_("{seconds} segundos").format(seconds=s), s) for s in CROSSFADE_CHOICES[1:]),
            ],
            preferences.crossfade,
            changed("crossfade"),
        )
    )
    group.add(scale_row(_("Velocidade"), (0.5, 2.0, 0.05), preferences.speed, changed("speed"), 2))
    group.add(scale_row(_("Tom (semitons)"), (-12, 12, 1), preferences.pitch, changed("pitch"), 0))
    timer = combo_row(
        _("Temporizador"),
        [
            (_("Desligado"), 0),
            (_("15 minutos"), 15),
            (_("30 minutos"), 30),
            (_("1 hora"), 60),
            (_("1 hora e 30"), 90),
        ],
        0,
        window._set_sleep_timer,
    )
    group.add(timer)
    return group
