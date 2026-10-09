"""Preferences > Aparência: theme, colours, window material and icons."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from .. import host  # noqa: E402
from ..i18n import _  # noqa: E402
from ..theming import builtin_themes, get_theme  # noqa: E402
from .rows import combo_row, switch_row  # noqa: E402


def appearance_group(window) -> Adw.PreferencesGroup:
    preferences = window.preferences
    changed = window._appearance_changed
    group = Adw.PreferencesGroup(
        title=_("Aparência"),
        description=_("Personalize o ambiente visual sem alterar o conteúdo."),
    )
    group.add(
        combo_row(
            _("Tema"),
            [(theme.name, theme.id) for theme in builtin_themes().values()],
            preferences.theme,
            lambda value: changed("theme", value),
        )
    )
    group.add(
        combo_row(
            _("Modo de cor"),
            [
                (_("Padrão do tema"), "theme"),
                (_("Seguir o sistema"), "system"),
                (_("Claro"), "light"),
                (_("Escuro"), "dark"),
            ],
            preferences.theme_variant,
            lambda value: changed("theme_variant", value),
        )
    )
    group.add(
        combo_row(
            _("Cor de destaque"),
            [
                (_("Padrão do tema"), "theme"),
                (_("Vermelho"), "red"),
                (_("Laranja"), "orange"),
                (_("Amarelo"), "yellow"),
                (_("Verde"), "green"),
                (_("Menta"), "mint"),
                (_("Azul"), "blue"),
                (_("Roxo"), "purple"),
                (_("Rosa"), "pink"),
                (_("Marrom"), "brown"),
                (_("Ardósia"), "slate"),
            ],
            preferences.accent,
            lambda value: changed("accent", value),
        )
    )
    group.add(
        switch_row(
            _("Fundo ambiente desfocado"),
            _("Usa as cores da capa atual atrás da interface"),
            preferences.background_blur,
            lambda active: changed("background_blur", active),
        )
    )
    if host.WINDOW_BACKDROPS:
        _add_window_material_rows(window, group)
    icon_styles = [
        (
            _("Windows — ícones Fluent")
            if host.SYSTEM_ICON_THEME
            else _("GTK — padrão do sistema"),
            "gtk",
        ),
        (_("Material Expressive"), "material"),
    ]
    if not host.SYSTEM_ICON_THEME:
        # On Windows the system style already is Fluent.
        icon_styles.append((_("Fluent — ícones do Windows 11"), "fluent"))
    group.add(
        combo_row(
            _("Estilo dos ícones"),
            icon_styles,
            preferences.icon_style,
            lambda value: changed("icon_style", value),
        )
    )
    return group


def _add_window_material_rows(window, group: Adw.PreferencesGroup) -> None:
    """Mica or Acrylic behind the window, and whether the expanded player shows it."""
    preferences = window.preferences
    supported = get_theme(preferences.theme).backdrop
    window._backdrop_row = combo_row(
        _("Efeito de fundo"),
        [
            (_("Mica"), "mica"),
            (_("Acrílico (fosco)"), "acrylic"),
            (_("Nenhum"), "none"),
        ],
        preferences.backdrop,
        lambda value: window._appearance_changed("backdrop", value),
    )
    window._backdrop_row.set_subtitle(
        _("Transparência do Windows 11 por trás da janela, no tema Windows 11")
        if host.IS_WINDOWS
        else _(
            "No tema Windows 11. O Mica usa o papel de parede; o Acrílico desfoca o que está "
            "atrás da janela com Blur my Shell (GNOME) ou Force Blur (KDE)"
        )
    )
    window._backdrop_row.set_sensitive(supported)
    group.add(window._backdrop_row)
    window._expanded_cover_row = switch_row(
        _("Capa desfocada no player expandido"),
        _("Desligada, o player expandido mostra o efeito de fundo"),
        preferences.expanded_cover,
        lambda active: window._appearance_changed("expanded_cover", active),
    )
    window._expanded_cover_row.set_sensitive(supported and preferences.backdrop != "none")
    group.add(window._expanded_cover_row)
