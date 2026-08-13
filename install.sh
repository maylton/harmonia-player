#!/bin/sh

# Portable installer for Harmonia's official release bundle.
# The application is installed per-user by default, keeping the host system clean.

set -eu

APP_ID="io.github.harmonia.Harmonia"
REPOSITORY="maylton/harmonia-player"
DEFAULT_RELEASE="0.1.0-beta.1"
FLATHUB_URL="https://dl.flathub.org/repo/flathub.flatpakrepo"

release="${HARMONIA_VERSION:-$DEFAULT_RELEASE}"
scope="--user"
bundle_path=""
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
  --bundle FILE   Install a local .flatpak bundle instead of downloading one
  --system        Install for every user (requires administrator privileges)
  --run           Open Harmonia after installation
  --uninstall     Uninstall Harmonia instead
  --yes, -y       Accept installer prompts automatically
  --help, -h      Show this help

Environment:
  HARMONIA_VERSION  Release to download (default: $DEFAULT_RELEASE)

The default installation is isolated to the current user. The installer verifies
the official SHA-256 checksum before installing a downloaded release.
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
        fail "Administrator access is required to install Flatpak. Install it manually and run this script again."
    fi
}

install_flatpak() {
    if command -v flatpak >/dev/null 2>&1; then
        return 0
    fi

    say "Flatpak is not installed."
    confirm "Install Flatpak using the system package manager?" || fail "Flatpak is required."

    if command -v apt-get >/dev/null 2>&1; then
        run_privileged apt-get update
        run_privileged apt-get install -y flatpak
    elif command -v dnf >/dev/null 2>&1; then
        run_privileged dnf install -y flatpak
    elif command -v yum >/dev/null 2>&1; then
        run_privileged yum install -y flatpak
    elif command -v zypper >/dev/null 2>&1; then
        run_privileged zypper --non-interactive install flatpak
    elif command -v pacman >/dev/null 2>&1; then
        if [ "$assume_yes" -eq 1 ]; then
            run_privileged pacman -S --needed --noconfirm flatpak
        else
            run_privileged pacman -S --needed flatpak
        fi
    elif command -v apk >/dev/null 2>&1; then
        run_privileged apk add flatpak
    elif command -v xbps-install >/dev/null 2>&1; then
        if [ "$assume_yes" -eq 1 ]; then
            run_privileged xbps-install -Sy flatpak
        else
            run_privileged xbps-install -S flatpak
        fi
    elif command -v eopkg >/dev/null 2>&1; then
        run_privileged eopkg install -y flatpak
    else
        fail "No supported package manager was found. Install Flatpak from https://flatpak.org/setup/ and run this script again."
    fi

    command -v flatpak >/dev/null 2>&1 || fail "Flatpak installation did not complete successfully."
}

download_file() {
    url=$1
    destination=$2
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --retry 3 --retry-delay 2 --output "$destination" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget --tries=3 --output-document="$destination" "$url"
    else
        fail "curl or wget is required to download Harmonia."
    fi
}

sha256_file() {
    target=$1
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$target" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$target" | awk '{print $1}'
    elif command -v openssl >/dev/null 2>&1; then
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
    [ "$actual" = "$expected" ] || fail "SHA-256 verification failed. The bundle was not installed."
    say "SHA-256 checksum verified."
}

normalize_architecture() {
    case "$(uname -m)" in
        x86_64|amd64) printf '%s\n' "x86_64" ;;
        aarch64|arm64) printf '%s\n' "aarch64" ;;
        *) uname -m ;;
    esac
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --bundle)
            [ "$#" -ge 2 ] || fail "--bundle requires a file path."
            bundle_path=$2
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

if [ "$scope" = "--user" ] && [ "$(id -u)" -eq 0 ]; then
    fail "Do not run the per-user installer as root. Run it as your desktop user, or use --system."
fi

install_flatpak

if [ "$uninstall" -eq 1 ]; then
    if ! flatpak info "$scope" "$APP_ID" >/dev/null 2>&1; then
        say "Harmonia is not installed in the selected scope."
        exit 0
    fi
    confirm "Uninstall Harmonia from the selected scope?" || exit 0
    flatpak uninstall "$scope" -y "$APP_ID"
    say "Harmonia was uninstalled. User data was preserved."
    exit 0
fi

flatpak remote-add "$scope" --if-not-exists flathub "$FLATHUB_URL"

if [ -n "$bundle_path" ]; then
    [ -f "$bundle_path" ] || fail "Bundle not found: $bundle_path"
    case "$bundle_path" in
        *.flatpak) ;;
        *) fail "The local bundle must have a .flatpak extension." ;;
    esac
    checksum_path="${bundle_path}.sha256"
    if [ -f "$checksum_path" ]; then
        verify_checksum "$bundle_path" "$checksum_path"
    else
        say "Warning: no sibling checksum found at $checksum_path; installing the explicitly selected local file."
    fi
else
    architecture=$(normalize_architecture)
    if [ "$architecture" != "x86_64" ]; then
        fail "Release $release has no automatic bundle for $architecture. Build the Flatpak locally and pass it with --bundle FILE."
    fi

    asset="Harmonia-${release}-${architecture}.flatpak"
    release_url="https://github.com/${REPOSITORY}/releases/download/v${release}"
    temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/harmonia-install.XXXXXX")
    bundle_path="$temp_dir/$asset"
    checksum_path="$bundle_path.sha256"

    say "Downloading Harmonia $release ($architecture)..."
    download_file "$release_url/$asset" "$bundle_path"
    download_file "$release_url/$asset.sha256" "$checksum_path"
    verify_checksum "$bundle_path" "$checksum_path"
fi

say "Installing Harmonia in the selected Flatpak scope..."
if flatpak info "$scope" "$APP_ID" >/dev/null 2>&1; then
    flatpak install "$scope" -y --reinstall "$bundle_path"
else
    flatpak install "$scope" -y "$bundle_path"
fi

say "Harmonia is installed and available in the application menu."
say "You can also start it with: flatpak run $APP_ID"

if [ "$run_after_install" -eq 1 ]; then
    exec flatpak run "$APP_ID"
fi
