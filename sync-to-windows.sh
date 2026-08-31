#!/usr/bin/env bash
# Copy this project onto the Windows filesystem, where it has to run.
#
# Only needed when you develop under WSL: the Magnification API is a Windows API,
# so the app runs from a Windows path, not /home.
#
#   ./sync-to-windows.sh '/mnt/c/Users/<you>/umbra'
#   UMBRA_WIN_DEST='/mnt/c/Users/<you>/umbra' ./sync-to-windows.sh
set -euo pipefail

DEST="${1:-${UMBRA_WIN_DEST:-}}"
if [ -z "$DEST" ]; then
  echo "usage: $0 <destination>            e.g. /mnt/c/Users/<you>/umbra" >&2
  echo "   or: UMBRA_WIN_DEST=<path> $0" >&2
  exit 2
fi
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$DEST"
rm -rf "$DEST/umbra"
cp -r "$SRC/umbra" "$DEST/umbra"
find "$DEST/umbra" -name '__pycache__' -type d -prune -exec rm -rf {} +
for f in umbra.bat smoketest.bat README.md SPEC.md; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DEST/$f"
done

WINPATH="$(printf '%s' "$DEST" | sed 's|^/mnt/\(.\)|\U\1:|; s|/|\\|g')"
echo "Synced to $WINPATH"
echo "Run it from Windows:  $WINPATH\\umbra.bat"
