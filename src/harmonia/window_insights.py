from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .i18n import _, ngettext
from .ui import page_header, page_shell


class WindowInsightsMixin:
    def show_insights(self) -> None:
        self.main_view = "insights"
        self.back.set_visible(False)
        self._set_active_nav("insights")
        old = self.stack.get_child_by_name("insights")
        if old:
            self.stack.remove(old)
        insights = self.storage.playback_insights()
        shell = page_shell("reading", spacing=24)
        scroll, content = shell.scroll, shell.content
        content.append(
            page_header(
                _("Sua retrospectiva de {year}").format(year=insights.year),
                _("Estatísticas privadas calculadas somente neste dispositivo"),
            )
        )

        summary = Adw.PreferencesGroup(title=_("Resumo"))
        values = (
            (
                _("Reproduções qualificadas"),
                ngettext("{count} faixa", "{count} faixas", insights.total_plays).format(
                    count=insights.total_plays
                ),
            ),
            (_("Músicas diferentes"), str(insights.unique_tracks)),
            (
                _("Tempo registrado"),
                ngettext("{count} minuto", "{count} minutos", insights.listened_minutes).format(
                    count=insights.listened_minutes
                ),
            ),
        )
        for title, value in values:
            row = Adw.ActionRow(title=title, subtitle=value)
            row.add_css_class("insight-summary-row")
            summary.add(row)
        content.append(summary)

        if not insights.total_plays:
            content.append(
                Adw.StatusPage(
                    icon_name="applications-multimedia-symbolic",
                    title=_("Ainda não há estatísticas"),
                    description=_(
                        "Reproduza músicas por pelo menos 30 segundos para formar sua retrospectiva."
                    ),
                )
            )
        else:
            tracks = Adw.PreferencesGroup(title=_("Mais ouvidas"))
            for position, ranked in enumerate(insights.top_tracks, 1):
                row = Adw.ActionRow(
                    title=ranked.item.title,
                    subtitle=ngettext(
                        "{count} reprodução", "{count} reproduções", ranked.plays
                    ).format(count=ranked.plays),
                )
                row.add_prefix(Gtk.Label(label=str(position), width_chars=2))
                row.add_prefix(self._square_cover(ranked.item, size=48, fixed=True))
                row.set_activatable(True)
                row.connect(
                    "activated",
                    lambda _row, item=ranked.item: self.set_queue([item], 0),
                )
                tracks.add(row)
            content.append(tracks)

            artists = Adw.PreferencesGroup(title=_("Artistas mais ouvidos"))
            for position, ranked in enumerate(insights.top_artists, 1):
                row = Adw.ActionRow(
                    title=ranked.name,
                    subtitle=ngettext(
                        "{count} reprodução", "{count} reproduções", ranked.plays
                    ).format(count=ranked.plays),
                )
                row.add_prefix(Gtk.Label(label=str(position), width_chars=2))
                artists.add(row)
            content.append(artists)

            months = Adw.PreferencesGroup(title=_("Atividade mensal"))
            month_names = (
                _("Jan"),
                _("Fev"),
                _("Mar"),
                _("Abr"),
                _("Mai"),
                _("Jun"),
                _("Jul"),
                _("Ago"),
                _("Set"),
                _("Out"),
                _("Nov"),
                _("Dez"),
            )
            maximum = max(insights.monthly_plays) or 1
            for name, plays in zip(month_names, insights.monthly_plays, strict=True):
                row = Adw.ActionRow(title=name, subtitle=str(plays))
                level = Gtk.LevelBar(min_value=0, max_value=maximum, value=plays)
                level.set_size_request(220, 8)
                level.set_valign(Gtk.Align.CENTER)
                row.add_suffix(level)
                months.add(row)
            content.append(months)

        self.stack.add_named(scroll, "insights")
        self.stack.set_visible_child_name("insights")
