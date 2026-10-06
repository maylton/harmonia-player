#!/usr/bin/env bash
# Build the Windows bundle and installer. Run from an MSYS2 UCRT64 shell:
#     packaging/windows/build.sh [version]
# The version defaults to the one in pyproject.toml. ISCC (Inno Setup 6) is
# looked up on PATH and in its default install folders; set ISCC to override.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
VERSION="${1:-$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')}"
STAGING="build/windows"

rm -rf "$STAGING"
mkdir -p "$STAGING/locale"

for language in $(cat po/LINGUAS); do
  mkdir -p "$STAGING/locale/$language/LC_MESSAGES"
  msgfmt --check -o "$STAGING/locale/$language/LC_MESSAGES/harmonia.mo" "po/$language.po"
done
python packaging/windows/make_ico.py data/icons/hicolor "$STAGING/harmonia.ico"

pyinstaller --noconfirm --clean \
  --distpath "$STAGING/dist" --workpath "$STAGING/work" \
  packaging/windows/harmonia.spec

# Every bundled typelib must find the typelibs it depends on in the bundle:
# the build machine has all of them installed, so a missing one only shows
# up on the user's machine, when its namespace is first imported.
python packaging/windows/check_typelibs.py "$STAGING/dist/Harmonia/_internal/gi_typelibs"

# Inno Setup wants a numeric x.y.z.w file version; "0.1.0-beta.1" -> "0.1.0.1".
NUMERIC="$(python - "$VERSION" <<'EOF'
import re, sys
numbers = re.findall(r"\d+", sys.argv[1])[:4]
print(".".join((numbers + ["0"] * 4)[:4]))
EOF
)"

ISCC="${ISCC:-$(command -v iscc || true)}"
USER_PROGRAMS="$(cygpath -u "${LOCALAPPDATA:-C:\\}")/Programs"
for candidate in "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" "/c/Program Files/Inno Setup 6/ISCC.exe" \
  "$USER_PROGRAMS/Inno Setup 6/ISCC.exe"; do
  if [ -z "$ISCC" ] && [ -x "$candidate" ]; then ISCC="$candidate"; fi
done
if [ -z "$ISCC" ]; then
  echo "Inno Setup 6 (ISCC.exe) não encontrado; o bundle está em $STAGING/dist/Harmonia" >&2
  exit 1
fi

# "-" switches: MSYS2 would rewrite "/D..." arguments as if they were paths.
"$ISCC" -Qp \
  "-DAppVersion=$VERSION" "-DFileVersion=$NUMERIC" \
  "-DSourceDir=$(cygpath -w "$ROOT/$STAGING/dist/Harmonia")" \
  "-DIconFile=$(cygpath -w "$ROOT/$STAGING/harmonia.ico")" \
  "-DLicenseFile=$(cygpath -w "$ROOT/LICENSE")" \
  "-O$(cygpath -w "$ROOT/$STAGING")" \
  "$(cygpath -w "$ROOT/packaging/windows/harmonia.iss")"
echo "$STAGING/Harmonia-$VERSION-x86_64-setup.exe"
