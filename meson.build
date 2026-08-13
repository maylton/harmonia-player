project('harmonia', version: '0.1.0-beta.1', meson_version: '>= 0.62')

gnome = import('gnome')
python = import('python').find_installation('python3')

install_subdir(
  'src/harmonia',
  install_dir: python.get_install_dir(),
  exclude_directories: ['__pycache__'],
)
launcher_config = configuration_data({
  'PYTHON': python.full_path(),
  'LOCALEDIR': get_option('prefix') / get_option('datadir') / 'locale',
  'BINDIR': get_option('prefix') / get_option('bindir'),
})
configure_file(
  input: 'data/io.github.harmonia.Harmonia.in',
  output: 'harmonia',
  configuration: launcher_config,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)
configure_file(
  input: 'data/io.github.harmonia.Harmonia.desktop',
  output: 'io.github.harmonia.Harmonia.desktop',
  configuration: launcher_config,
  install: true,
  install_dir: get_option('datadir') / 'applications',
)
install_data('data/io.github.harmonia.Harmonia.metainfo.xml', install_dir: get_option('datadir') / 'metainfo')
install_subdir(
  'data/icons/hicolor',
  install_dir: get_option('datadir') / 'icons',
  exclude_directories: ['1024x1024'],
)
install_data(
  'LICENSE',
  'THIRD_PARTY_NOTICES.md',
  'licenses/Material-Symbols-Apache-2.0.txt',
  install_dir: get_option('datadir') / 'doc/harmonia',
)
subdir('po')
