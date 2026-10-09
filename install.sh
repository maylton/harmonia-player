#!/bin/sh

# Harmonia installer for Linux.
#
# Downloads the latest release and installs it in the format that suits the
# system: the .deb on Debian and Ubuntu, the .rpm on Fedora and other DNF
# distributions (when their libadwaita is 1.7 or newer, which the interface
# needs), and the Flatpak, which brings its own GNOME runtime, everywhere
# else. --method source builds and installs it with Meson instead.

set -eu

APP_ID="io.github.harmonia.Harmonia"
REPOSITORY="maylton/harmonia-player"
FLATHUB_URL="https://dl.flathub.org/repo/flathub.flatpakrepo"
MIN_LIBADWAITA="1.7"
SOURCE_STATE="${XDG_DATA_HOME:-$HOME/.local/share}/harmonia-installer"

release="${HARMONIA_VERSION:-}"
method="auto"
scope="--user"
package_path=""
run_after_install=0
assume_yes=0
uninstall=0
temp_dir=""

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    if [ -n "$temp_dir" ] && [ -d "$temp_dir" ]; then
        rm -rf -- "$temp_dir"
    fi
}

trap cleanup EXIT HUP INT TERM

usage() {
    cat <<EOF
Harmonia installer

Usage:
  ./install.sh [options]

Options:
  --method METHOD  auto (default), deb, rpm, flatpak or source
  --release X      Release to install, e.g. 0.1.0-beta.2 (default: the latest)
  --package FILE   Install a local .deb, .rpm or .flatpak instead of downloading
  --system         Flatpak and source builds: install for every user
  --run            Open Harmonia after installation
  --uninstall      Remove Harmonia, whichever way it was installed
  --yes, -y        Accept installer prompts automatically
  --help, -h       Show this help

"auto" installs the .deb on Debian/Ubuntu and the .rpm on Fedora when the
distribution's libadwaita is $MIN_LIBADWAITA or newer, and the Flatpak otherwise
(for example on Ubuntu 24.04). "source" builds with Meson into ~/.local
(/usr/local with --system); it needs meson, ninja and gettext.

Downloads are checked against the release's SHA-256 checksums. Your
library, settings and YouTube Music session are kept when switching formats.
EOF
}

confirm() {
    prompt=$1
    if [ "$assume_yes" -eq 1 ]; then
        return 0
    fi
    if [ ! -t 0 ]; then
        fail "$prompt Re-run with --yes to continue non-interactively."
    fi
    printf '%s [y/N] ' "$prompt"
    read -r answer
    case "$answer" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

run_privileged() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    elif command -v doas >/dev/null 2>&1; then
        doas "$@"
    else
        fail "Administrator access is required for this step: $*"
    fi
}

has() {
    command -v "$1" >/dev/null 2>&1
}

download_file() {
    url=$1
    destination=$2
    if has curl; then
        curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
            --output "$destination" "$url"
    elif has wget; then
        wget --quiet --tries=3 --output-document="$destination" "$url"
    else
        fail "curl or wget is required to download Harmonia."
    fi
}

sha256_file() {
    target=$1
    if has sha256sum; then
        sha256sum "$target" | awk '{print $1}'
    elif has shasum; then
        shasum -a 256 "$target" | awk '{print $1}'
    elif has openssl; then
        openssl dgst -sha256 "$target" | awk '{print $NF}'
    else
        fail "A SHA-256 utility (sha256sum, shasum, or openssl) is required."
    fi
}

verify_checksum() {
    target=$1
    checksum_file=$2
    expected=$(awk 'NR == 1 {print $1}' "$checksum_file")
    case "$expected" in
        *[!0-9A-Fa-f]*|'') fail "The checksum file is invalid." ;;
    esac
    [ "${#expected}" -eq 64 ] || fail "The checksum file is invalid."
    actual=$(sha256_file "$target")
    [ "$actual" = "$expected" ] || fail "SHA-256 verification failed. Nothing was installed."
    say "SHA-256 checksum verified."
}

make_temp_dir() {
    if [ -z "$temp_dir" ]; then
        temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/harmonia-install.XXXXXX")
        # apt and dnf read the package as another user.
        chmod 755 "$temp_dir"
    fi
}

# Sets release to the newest one on GitHub, pre-releases included.
find_latest_release() {
    make_temp_dir
    listing="$temp_dir/releases.json"
    download_file "https://api.github.com/repos/$REPOSITORY/releases?per_page=1" "$listing" \
        || fail "Could not reach GitHub to find the latest release. Pass --release X to choose one."
    release=$(sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' "$listing" | head -n 1)
    [ -n "$release" ] || fail "No Harmonia release was found on GitHub."
}

# version_at_least A B: whether version A is B or newer.
version_at_least() {
    [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n 1)" = "$2" ]
}

# The libadwaita version the system package manager would install.
libadwaita_from_apt() {
    apt-cache policy gir1.2-adw-1 2>/dev/null \
        | awk '/Candidate:/ {print $2}' | sed 's/^[0-9]*://; s/[-+~].*//; s/(none)//'
}

libadwaita_from_dnf() {
    dnf repoquery --quiet --latest-limit 1 --queryformat '%{version}\n' libadwaita 2>/dev/null \
        | tail -n 1
}

# Sets method for "auto": the system's own package format when its libadwaita
# is new enough, the Flatpak otherwise.
choose_method() {
    native=""
    available=""
    if has apt-get && has dpkg; then
        native="deb"
        available=$(libadwaita_from_apt)
    elif has dnf; then
        native="rpm"
        available=$(libadwaita_from_dnf)
    fi
    if [ -n "$native" ] && [ -n "$available" ] && version_at_least "$available" "$MIN_LIBADWAITA"; then
        method=$native
        return
    fi
    if [ -n "$native" ]; then
        say "This system offers libadwaita ${available:-(none)}; Harmonia needs $MIN_LIBADWAITA or newer, so it will use the Flatpak."
    fi
    method="flatpak"
}

# Sets package_file to the local package (--package) or to release asset $1,
# downloaded and checked against its .sha256.
obtain_package() {
    if [ -n "$package_path" ]; then
        [ -f "$package_path" ] || fail "Package not found: $package_path"
        if [ -f "$package_path.sha256" ]; then
            verify_checksum "$package_path" "$package_path.sha256"
        else
            say "Warning: no $package_path.sha256 next to the package; installing the file you chose."
        fi
        case "$package_path" in
            /*) package_file=$package_path ;;
            *) package_file="$PWD/$package_path" ;;
        esac
        return
    fi
    asset=$1
    make_temp_dir
    url="https://github.com/$REPOSITORY/releases/download/v$release/$asset"
    say "Downloading $asset..."
    download_file "$url" "$temp_dir/$asset" \
        || fail "Release $release has no $asset. See https://github.com/$REPOSITORY/releases"
    download_file "$url.sha256" "$temp_dir/$asset.sha256" \
        || fail "Release $release has no checksum for $asset."
    verify_checksum "$temp_dir/$asset" "$temp_dir/$asset.sha256"
    chmod 644 "$temp_dir/$asset"
    package_file="$temp_dir/$asset"
}

ensure_flatpak() {
    has flatpak && return 0
    say "Flatpak is not installed."
    confirm "Install Flatpak using the system package manager?" || fail "Flatpak is required."
    if has apt-get; then
        run_privileged apt-get update
        run_privileged apt-get install -y flatpak
    elif has dnf; then
        run_privileged dnf install -y flatpak
    elif has zypper; then
        run_privileged zypper --non-interactive install flatpak
    elif has pacman; then
        run_privileged pacman -S --needed --noconfirm flatpak
    elif has apk; then
        run_privileged apk add flatpak
    elif has xbps-install; then
        run_privileged xbps-install -Sy flatpak
    elif has eopkg; then
        run_privileged eopkg install -y flatpak
    else
        fail "No supported package manager was found. Install Flatpak from https://flatpak.org/setup/ and run this script again."
    fi
    has flatpak || fail "Flatpak installation did not complete successfully."
}

flatpak_scope_installed() {
    has flatpak && flatpak info "$1" "$APP_ID" >/dev/null 2>&1
}

native_installed() {
    { has dpkg && dpkg -s harmonia >/dev/null 2>&1; } \
        || { has rpm && rpm -q harmonia >/dev/null 2>&1; }
}

# Settings, library cache and downloads of a Flatpak install live under
# ~/.var/app; a native install reads them from the XDG directories. The
# YouTube Music session is in the keyring and is shared by both.
migrate_flatpak_data() {
    sandbox="$HOME/.var/app/$APP_ID"
    for kind in config cache; do
        from="$sandbox/$kind/harmonia"
        case "$kind" in
            config) to="${XDG_CONFIG_HOME:-$HOME/.config}/harmonia" ;;
            cache) to="${XDG_CACHE_HOME:-$HOME/.cache}/harmonia" ;;
        esac
        if [ -d "$from" ] && [ ! -e "$to" ]; then
            mkdir -p "$(dirname "$to")"
            cp -a "$from" "$to"
            say "Copied your Flatpak $kind to $to."
        fi
    done
}

remove_flatpak_copies() {
    for flatpak_scope in --user --system; do
        if flatpak_scope_installed "$flatpak_scope"; then
            if confirm "The Flatpak version of Harmonia is also installed ($flatpak_scope). Remove it, keeping your data?"; then
                migrate_flatpak_data
                if [ "$flatpak_scope" = "--system" ]; then
                    run_privileged flatpak uninstall --system -y "$APP_ID"
                else
                    flatpak uninstall --user -y "$APP_ID"
                fi
            fi
        fi
    done
}

install_deb() {
    has apt-get || fail "The .deb needs apt-get (Debian, Ubuntu and derivatives)."
    file=$1
    say "Installing the .deb with apt (administrator access required)..."
    run_privileged apt-get install -y "$file"
    remove_flatpak_copies
}

install_rpm() {
    file=$1
    say "Installing the .rpm (administrator access required)..."
    if has dnf; then
        run_privileged dnf install -y "$file"
    elif has zypper; then
        run_privileged zypper --non-interactive install --allow-unsigned-rpm "$file"
    else
        fail "The .rpm needs dnf or zypper."
    fi
    remove_flatpak_copies
}

install_flatpak_bundle() {
    file=$1
    ensure_flatpak
    flatpak remote-add "$scope" --if-not-exists flathub "$FLATHUB_URL"
    say "Installing the Flatpak..."
    if flatpak_scope_installed "$scope"; then
        flatpak install "$scope" -y --reinstall "$file"
    else
        flatpak install "$scope" -y "$file"
    fi
}

install_source() {
    for tool in meson ninja msgfmt; do
        has "$tool" || fail "Building from source needs $tool. Install meson, ninja and gettext first."
    done
    make_temp_dir
    download_file "https://github.com/$REPOSITORY/archive/refs/tags/v$release.tar.gz" "$temp_dir/source.tar.gz" \
        || fail "Could not download the source of release $release."
    tar -xzf "$temp_dir/source.tar.gz" -C "$temp_dir"
    source_dir=$(find "$temp_dir" -mindepth 1 -maxdepth 1 -type d -name 'harmonia-player-*' | head -n 1)
    prefix="$HOME/.local"
    [ "$scope" = "--system" ] && prefix="/usr/local"
    meson setup "$temp_dir/build" "$source_dir" --prefix="$prefix" --buildtype=release -Dprivate_python=true
    meson compile -C "$temp_dir/build"
    if [ "$scope" = "--system" ]; then
        run_privileged meson install -C "$temp_dir/build" --no-rebuild
    else
        meson install -C "$temp_dir/build" --no-rebuild
    fi
    # Keep the list of installed files so --uninstall can remove them.
    mkdir -p "$SOURCE_STATE"
    cp "$temp_dir/build/meson-logs/install-log.txt" "$SOURCE_STATE/install-log${scope#-}.txt"
    say "Harmonia was built and installed into $prefix."
    say "It needs GTK 4, libadwaita $MIN_LIBADWAITA+, PyGObject, GStreamer, libsecret and WebKitGTK 6 from your distribution."
}

uninstall_everything() {
    removed=0
    if has dpkg && dpkg -s harmonia >/dev/null 2>&1; then
        confirm "Remove the Harmonia .deb?" && { run_privileged apt-get remove -y harmonia; removed=1; }
    fi
    if has rpm && rpm -q harmonia >/dev/null 2>&1; then
        if has dnf; then
            confirm "Remove the Harmonia .rpm?" && { run_privileged dnf remove -y harmonia; removed=1; }
        elif has zypper; then
            confirm "Remove the Harmonia .rpm?" && { run_privileged zypper --non-interactive remove harmonia; removed=1; }
        fi
    fi
    for flatpak_scope in --user --system; do
        if flatpak_scope_installed "$flatpak_scope"; then
            if confirm "Remove the Harmonia Flatpak ($flatpak_scope)?"; then
                if [ "$flatpak_scope" = "--system" ]; then
                    run_privileged flatpak uninstall --system -y "$APP_ID"
                else
                    flatpak uninstall --user -y "$APP_ID"
                fi
                removed=1
            fi
        fi
    done
    for log in "$SOURCE_STATE"/install-log*.txt; do
        [ -f "$log" ] || continue
        if confirm "Remove the Harmonia build installed from source ($(basename "$log"))?"; then
            grep -v '^#' "$log" | while IFS= read -r installed; do
                if [ -w "$(dirname "$installed")" ]; then rm -f -- "$installed"; else run_privileged rm -f -- "$installed"; fi
            done
            rm -f -- "$log"
            removed=1
        fi
    done
    if [ "$removed" -eq 1 ]; then
        say "Harmonia was uninstalled. Your library, settings and session were kept."
    else
        say "Nothing was removed."
    fi
}

# The tests source this file for its functions only.
if [ "${HARMONIA_INSTALLER_FUNCTIONS_ONLY:-}" = 1 ]; then
    return 0
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        --method)
            [ "$#" -ge 2 ] || fail "--method requires auto, deb, rpm, flatpak or source."
            method=$2
            shift 2
            ;;
        --release)
            [ "$#" -ge 2 ] || fail "--release requires a version."
            release=${2#v}
            shift 2
            ;;
        --package|--bundle)
            [ "$#" -ge 2 ] || fail "$1 requires a file path."
            package_path=$2
            shift 2
            ;;
        --system)
            scope="--system"
            shift
            ;;
        --run)
            run_after_install=1
            shift
            ;;
        --uninstall)
            uninstall=1
            shift
            ;;
        --yes|-y)
            assume_yes=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fail "Unknown option: $1. Use --help for usage information."
            ;;
    esac
done

if [ "$uninstall" -eq 1 ]; then
    uninstall_everything
    exit 0
fi

if [ -n "$package_path" ]; then
    case "$package_path" in
        *.deb) method="deb" ;;
        *.rpm) method="rpm" ;;
        *.flatpak) method="flatpak" ;;
        *) fail "The package must be a .deb, .rpm or .flatpak file." ;;
    esac
fi

case "$method" in
    auto) choose_method ;;
    deb|rpm|flatpak|source) ;;
    *) fail "Unknown method: $method. Use auto, deb, rpm, flatpak or source." ;;
esac

case "$method" in
    flatpak|source)
        if [ "$(id -u)" -eq 0 ] && [ "$scope" = "--user" ]; then
            fail "Run the installer as your desktop user, or pass --system."
        fi
        ;;
esac

if [ -z "$package_path" ]; then
    [ -n "$release" ] || find_latest_release
    if [ "$method" = "flatpak" ] && [ "$(uname -m)" != "x86_64" ]; then
        fail "Release $release has no Flatpak for $(uname -m). Use --method source."
    fi
fi

say "Installing Harmonia ${release:-from $package_path} as $method."
package_file=""
case "$method" in
    deb)
        obtain_package "Harmonia-$release-all.deb"
        install_deb "$package_file"
        ;;
    rpm)
        obtain_package "Harmonia-$release-noarch.rpm"
        install_rpm "$package_file"
        ;;
    flatpak)
        obtain_package "Harmonia-$release-x86_64.flatpak"
        install_flatpak_bundle "$package_file"
        ;;
    source)
        [ -z "$package_path" ] || fail "--method source downloads the source; it does not take --package."
        install_source
        ;;
esac

say "Harmonia is installed and available in the application menu."
if [ "$method" = "flatpak" ]; then
    launch="flatpak run $APP_ID"
else
    launch="harmonia"
fi
say "You can also start it with: $launch"

if [ "$run_after_install" -eq 1 ]; then
    # shellcheck disable=SC2086
    exec $launch
fi
