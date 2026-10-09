#!/usr/bin/env bash
# Build Harmonia's .deb and .rpm from a Meson install of the GTK frontend.
#
#     packaging/linux/build-packages.sh [version]
#
# The version defaults to the one in meson.build. Requires meson, ninja,
# gettext, python3, dpkg-deb and rpmbuild. Both packages are architecture
# independent: the code goes to /usr/share/harmonia/python (Meson's
# private_python option), so they work with whichever Python 3 the
# distribution ships. Output: build/linux/Harmonia-<version>-all.deb and
# Harmonia-<version>-noarch.rpm.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
VERSION="${1:-$(sed -n "s/^project('harmonia', version: '\([^']*\)'.*/\1/p" meson.build)}"
[ -n "$VERSION" ] || { echo "Could not read the version from meson.build" >&2; exit 1; }
OUT="build/linux"
STAGE="$ROOT/$OUT/stage"
rm -rf "$OUT"
mkdir -p "$OUT"

meson setup "$OUT/meson" --prefix=/usr --buildtype=release -Dprivate_python=true
meson compile -C "$OUT/meson"
DESTDIR="$STAGE" meson install -C "$OUT/meson" --no-rebuild
find "$STAGE" -name '__pycache__' -prune -exec rm -rf {} +

SUMMARY="YouTube Music client for GNOME"
DESCRIPTION="Harmonia is a native YouTube Music client with a GTK 4 and libadwaita
interface: library, search, playlists, synced lyrics, downloads, MPRIS
media controls and optional Last.fm and Discord integration."
HOMEPAGE="https://github.com/maylton/harmonia-player"
MAINTAINER="Harmonia <https://github.com/maylton/harmonia-player/issues>"
# A pre-release sorts before the final version only with "~" (both formats).
PACKAGE_VERSION="${VERSION/-/\~}"

build_deb() {
    local root="$ROOT/$OUT/deb"
    cp -a "$STAGE" "$root"
    mkdir -p "$root/DEBIAN"
    local size
    size=$(du -sk --exclude=DEBIAN "$root" | cut -f1)
    cat > "$root/DEBIAN/control" <<EOF
Package: harmonia
Version: ${PACKAGE_VERSION}-1
Architecture: all
Maintainer: ${MAINTAINER}
Installed-Size: ${size}
Section: sound
Priority: optional
Homepage: ${HOMEPAGE}
Depends: python3 (>= 3.11), python3-gi, gir1.2-glib-2.0, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.7), gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gir1.2-secret-1, gir1.2-webkit-6.0
Recommends: gstreamer1.0-plugins-bad, gstreamer1.0-libav, gstreamer1.0-gtk4
Description: ${SUMMARY}
$(printf '%s\n' "$DESCRIPTION" | sed 's/^/ /')
EOF
    dpkg-deb --root-owner-group --build "$root" "$OUT/Harmonia-${VERSION}-all.deb"
}

build_rpm() {
    local top="$ROOT/$OUT/rpm"
    mkdir -p "$top/SPECS"
    local files
    files=$(cd "$STAGE" && {
        find usr/share/harmonia -type d | sed 's|^|%dir /|'
        find usr -type f -o -type l | sed 's|^|/|'
    })
    cat > "$top/SPECS/harmonia.spec" <<EOF
# The files are installed by Meson beforehand; the spec only packages them.
%define __os_install_post %{nil}
%define _build_id_links none
Name: harmonia
Version: ${PACKAGE_VERSION}
Release: 1
Summary: ${SUMMARY}
License: GPL-3.0-or-later
URL: ${HOMEPAGE}
BuildArch: noarch
AutoReqProv: no
Requires: python3 >= 3.11, python3-gobject, gtk4, libadwaita >= 1.7, gstreamer1, gstreamer1-plugins-base, gstreamer1-plugins-good, libsecret, webkitgtk6.0
Recommends: gstreamer1-plugins-bad-free, gstreamer1-plugin-libav, gstreamer1-plugin-gtk4

%description
${DESCRIPTION}

%install
cp -a "${STAGE}/." "%{buildroot}/"

%files
${files}
EOF
    rpmbuild --define "_topdir $top" -bb "$top/SPECS/harmonia.spec"
    cp "$top"/RPMS/noarch/*.rpm "$OUT/Harmonia-${VERSION}-noarch.rpm"
}

build_deb
build_rpm
(cd "$OUT" && for package in Harmonia-*.deb Harmonia-*.rpm; do sha256sum "$package" > "$package.sha256"; done)
ls -l "$OUT"/Harmonia-*
