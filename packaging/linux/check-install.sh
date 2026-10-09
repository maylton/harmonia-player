#!/bin/sh
# Install a built .deb or .rpm into a clean distribution container and check
# that Harmonia starts as far as it can without a display.
#
#     packaging/linux/check-install.sh PACKAGE VERSION
set -eu

package=$1
version=$2

if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq "$package"
else
    dnf install -y -q "$package"
fi

# The launcher, with the version of the package.
test "$(harmonia --version)" = "Harmonia $version"

# Every GObject library the interface needs resolves, libadwaita is new enough
# for Adw.WrapBox, and the whole GTK frontend imports from the private path.
python3 - <<'EOF'
import sys

sys.path.insert(0, "/usr/share/harmonia/python")
import gi

for namespace, version in (
    ("Gtk", "4.0"),
    ("Adw", "1"),
    ("Gst", "1.0"),
    ("Secret", "1"),
    ("WebKit", "6.0"),
    ("GdkPixbuf", "2.0"),
):
    gi.require_version(namespace, version)
from gi.repository import Adw  # noqa: E402

assert hasattr(Adw, "WrapBox"), "libadwaita is older than 1.7"
import harmonia.app  # noqa: E402,F401
import harmonia.auth  # noqa: E402,F401

print("Harmonia imports with libadwaita", Adw.MAJOR_VERSION, Adw.MINOR_VERSION)
EOF

test -f /usr/share/applications/io.github.harmonia.Harmonia.desktop
test -f /usr/share/metainfo/io.github.harmonia.Harmonia.metainfo.xml
# Translations are checked in the package itself: minimal container images
# tell dpkg to skip /usr/share/locale.
echo "Package OK"
