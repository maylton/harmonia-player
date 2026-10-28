"""Preferences > Sobre o Harmonia: the version, updates and the project's links."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import __version__, host, updates  # noqa: E402
from ..i18n import _  # noqa: E402
from .rows import pill_button, switch_row  # noqa: E402

APP_ID = "io.github.harmonia.Harmonia"
ISSUES_URL = f"https://github.com/{updates.REPOSITORY}/issues"
PROJECT_URL = f"https://github.com/{updates.REPOSITORY}"
# The bundled icon packs, for the credits' legal sections.
ICON_PACKS = (
    ("Material Symbols", "Google", Gtk.License.APACHE_2_0),
    ("Fluent UI System Icons", "Microsoft", Gtk.License.MIT_X11),
    ("Framework7 Icons", "Vladimir Kharlampidi", Gtk.License.MIT_X11),
    ("Breeze Icons", "KDE", Gtk.License.LGPL_3_0),
    ("Papirus Icon Theme", "Papirus Development Team", Gtk.License.GPL_3_0),
)


def install_label(method: str) -> str:
    return {
        "windows": _("instalador do Windows"),
        "flatpak": _("Flatpak"),
        "source": _("compilado pelo install.sh"),
        "source-system": _("compilado pelo install.sh, para todos os usuários"),
        "deb": _("pacote .deb"),
        "rpm": _("pacote .rpm"),
    }.get(method, _("cópia de desenvolvimento"))


def about_group(window) -> Adw.PreferencesGroup:
    controller = window.updates
    group = Adw.PreferencesGroup(title=_("Sobre o Harmonia"))
    platform = "Windows" if host.IS_WINDOWS else "Linux"
    version = Adw.ActionRow(
        title=_("Harmonia {version}").format(version=__version__),
        subtitle=f"GTK · {platform} · {install_label(controller.method)}",
    )
    version.add_suffix(pill_button(_("Créditos"), lambda: show_about(window)))
    group.add(version)

    update = Adw.ActionRow(title=_("Atualizações"))
    spinner = Adw.Spinner(visible=False)
    button = pill_button("", controller.act, "suggested-action")
    update.add_suffix(spinner)
    update.add_suffix(button)

    def refresh() -> None:
        update.set_subtitle(controller.status())
        button.set_label(controller.button_label())
        button.set_visible(not controller.busy())
        spinner.set_visible(controller.busy())

    controller.listen(refresh)
    update.connect("destroy", lambda *_: controller.unlisten(refresh))
    refresh()
    group.add(update)

    group.add(
        switch_row(
            _("Procurar atualizações automaticamente"),
            _(
                "Uma vez por dia, no GitHub do Harmonia; a versão nova só é instalada quando você pede"
            ),
            window.preferences.check_updates,
            lambda value: window._preference_changed("check_updates", value),
        )
    )

    links = Adw.ActionRow(title=_("Código e problemas"), subtitle=PROJECT_URL)
    links.add_suffix(pill_button(_("GitHub"), lambda: _open(window, PROJECT_URL)))
    links.add_suffix(pill_button(_("Relatar um problema"), lambda: _open(window, ISSUES_URL)))
    group.add(links)
    return group


def _open(window, uri: str) -> None:
    Gtk.UriLauncher(uri=uri).launch(window, None, None, None)


def show_about(window) -> None:
    # The launcher icon is installed with the app; a checkout run lacks it.
    theme = Gtk.IconTheme.get_for_display(window.get_display())
    icon = APP_ID if theme.has_icon(APP_ID) else "audio-x-generic-symbolic"
    about = Adw.AboutDialog(
        application_name="Harmonia",
        application_icon=icon,
        version=__version__,
        developer_name=_("Colaboradores do Harmonia"),
        comments=_("Um cliente do YouTube Music para Linux e Windows."),
        website=PROJECT_URL,
        issue_url=ISSUES_URL,
        license_type=Gtk.License.GPL_3_0,
    )
    about.add_acknowledgement_section(
        _("Inspirado no"), ["Metrolist https://github.com/MetrolistGroup/Metrolist"]
    )
    for name, author, license_type in ICON_PACKS:
        about.add_legal_section(name, f"© {author}", license_type, None)
    about.present(window)
