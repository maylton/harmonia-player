"""Preferences > Aparência: theme, colours, compositor blur and icons."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import host  # noqa: E402
from ..i18n import _  # noqa: E402
from ..theming import builtin_themes  # noqa: E402
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
    if host.IS_LINUX:
        _add_compositor_blur_rows(window, group)
    # Named after the icon pack alone; on Windows the system style is Fluent.
    icon_styles = [
        (_("Fluent") if host.SYSTEM_ICON_THEME else _("Padrão do sistema"), "gtk"),
        (_("Material Expressive"), "material"),
    ]
    if not host.SYSTEM_ICON_THEME:
        icon_styles.append((_("Fluent"), "fluent"))
    icon_styles += [
        (_("Framework7"), "framework7"),
        (_("Breeze"), "breeze"),
        (_("Papirus"), "papirus"),
    ]
    group.add(
        combo_row(
            _("Estilo dos ícones"),
            icon_styles,
            preferences.icon_style,
            lambda value: changed("icon_style", value),
        )
    )
    return group


def backdrop_subtitle(window) -> str:
    """Who makes the Harmonia theme's Mica, or why it is not shown."""
    backdrops = getattr(window, "_window_backdrops", None)
    reason = getattr(backdrops, "reason", "")
    if reason:
        return reason
    blur = getattr(backdrops, "blur", "")
    if blur == "kwin":
        return _("O KWin borra o que está atrás da janela")
    if blur == "background-effect":
        return _("O compositor borra o que está atrás da janela")
    if blur == "blur-my-shell":
        return _("O Blur my Shell borra o que está atrás da janela")
    wallpaper = getattr(backdrops, "wallpaper", None)
    if wallpaper is not None and getattr(backdrops, "kind", "") in ("mica", "blur"):
        # Which image it took, to tell at a glance whether it is the desktop's.
        return _("Desfoque feito do papel de parede {name}").format(name=wallpaper.name)
    return _(
        "Borra o que está atrás da janela com o KWin, o Hyprland ou o Blur my Shell (GNOME); "
        "sem eles, o próprio Harmonia desfoca o papel de parede"
    )


def _blur_my_shell_row(window) -> Adw.ActionRow:
    """Blur my Shell is on but leaves Harmonia out: offer to add it."""
    row = Adw.ActionRow(
        title=_("Borrar com o Blur my Shell"),
        subtitle=_("Inclui o Harmonia no borrado de aplicativos da extensão"),
    )
    button = Gtk.Button(label=_("Ativar"), valign=Gtk.Align.CENTER)
    button.add_css_class("pill")
    button.add_css_class("suggested-action")

    def include(*_args) -> None:
        if window._window_backdrops.include_in_blur_my_shell():
            row.set_visible(False)
            window._backdrop_row.set_subtitle(backdrop_subtitle(window))
        else:
            row.set_subtitle(_("Não foi possível alterar as configurações do Blur my Shell"))

    button.connect("clicked", include)
    row.add_suffix(button)
    return row


def _add_compositor_blur_rows(window, group: Adw.PreferencesGroup) -> None:
    """The Harmonia theme's Mica is automatic; the compositor's blur, in every theme, a choice."""
    preferences = window.preferences
    window._backdrop_row = switch_row(
        _("Desfoque do compositor"),
        backdrop_subtitle(window),
        preferences.compositor_blur,
        lambda active: window._appearance_changed("compositor_blur", active),
    )
    group.add(window._backdrop_row)
    if getattr(getattr(window, "_window_backdrops", None), "blur_my_shell_offer", False):
        group.add(_blur_my_shell_row(window))
