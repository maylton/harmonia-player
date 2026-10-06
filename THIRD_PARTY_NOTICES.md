# Third-party assets

Harmonia bundles selected SVG icons locally so that icon themes work without a
network connection. The semantic GTK filenames and their upstream identifiers
are recorded in `tools/sync_icons.py`.

## Material Symbols

- Project: Material Symbols by Google
- Source: https://github.com/google/material-design-icons
- Retrieved through: https://api.iconify.design
- License: Apache License 2.0
- Used by: Harmonia Material icon theme

Copyright Google LLC. Licensed under the Apache License, Version 2.0. You may
obtain a copy of the license at:
https://www.apache.org/licenses/LICENSE-2.0

## Fluent UI System Icons

- Project: Fluent UI System Icons by Microsoft
- Source: https://github.com/microsoft/fluentui-system-icons
- Retrieved through: https://api.iconify.design
- License: MIT (`licenses/Fluent-UI-System-Icons-MIT.txt`)
- Used by: Harmonia Fluent icon theme (`src/harmonia/icons/HarmoniaFluent`),
  the system icons on Windows

Copyright (c) 2020 Microsoft Corporation.

## elementary icons

- Project: elementary icons
- Source: https://github.com/elementary/icons
- License: GNU General Public License, version 3 or later
- Used by: elementary compatibility shadow (`src/harmonia/icons-compat`),
  regenerated with `tools/sync_elementary_icons.py`

A small set of symbolic icons from elementary icons 9.x, merged into the
installed elementary theme (and themes inheriting from it, such as accent
variants) only on GTK 4.21 or newer, where the 8.x versions of these icons
render blank. All other icons keep coming from the installed theme.

## Microsoft WebView2 Loader

- Project: WebView2 Loader from the Microsoft.Web.WebView2 SDK, as packaged by
  MSYS2 (`mingw-w64-ucrt-x86_64-webview2-loader`)
- Source: https://learn.microsoft.com/microsoft-edge/webview2/
- License: BSD 3-Clause (Copyright Microsoft Corporation)
- Used by: the Windows build only, for the embedded Google login
  (`src/harmonia/auth_webview2.py`); the license ships in the installer under
  `licenses/webview2-loader`

The browser itself is the Microsoft Edge WebView2 runtime installed with
Windows; it is not bundled.

## Iconify

Iconify provides the development-time API used to retrieve and normalize the
upstream SVG files. Harmonia does not contact Iconify at runtime. Iconify's
software is MIT licensed; each bundled icon remains under its source icon set's
license.

- Project: https://iconify.design/
- License: https://github.com/iconify/iconify/blob/main/license.txt
