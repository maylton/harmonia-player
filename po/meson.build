i18n = import('i18n')
# Builds the .mo catalogs. Regenerate harmonia.pot with
# tools/update_translations.py: the harmonia-pot target only reads po/POTFILES
# (Python) and would drop the QML messages listed in po/POTFILES.qml.
i18n.gettext(
  'harmonia',
  preset: 'glib',
  args: ['--msgid-bugs-address=https://github.com/maylton/harmonia-player/issues'],
)
