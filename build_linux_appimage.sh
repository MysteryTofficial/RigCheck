#!/usr/bin/env bash
# =============================================================================
# build_linux_appimage.sh - build a portable RigCheck .AppImage (from Linux).
#
#  1. Creates a local virtualenv with PyInstaller + deps
#  2. Builds a self-contained onedir bundle with PyInstaller
#  3. Wraps it into an AppDir (AppRun + .desktop + icon)
#  4. Bundles it into dist/RigCheck-x86_64.AppImage with appimagetool
#
# Requirements: bash, python3, curl, wget not needed (curl used).
# Output: dist/RigCheck-x86_64.AppImage
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# RigCheck (like the app itself) must NOT be built as root: the build tooling
# and the final app refuse to run as root, and root-owned artifacts are painful
# to clean up.
if [ "$(id -u)" = "0" ]; then
    echo "ERROR: do not run this script as root / with sudo." >&2
    echo "  Run it as a normal user instead:" >&2
    echo "    ./$(basename "$0")" >&2
    exit 1
fi

PYTHON="${PYTHON:-python3}"
ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ]; then
    echo "ERROR: this AppImage build currently targets x86_64 only (host: $ARCH)." >&2
    exit 1
fi

command -v "$PYTHON" >/dev/null 2>&1 || { echo "ERROR: '$PYTHON' not found." >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required." >&2; exit 1; }
[ -f "RigCheck.py" ] || { echo "ERROR: RigCheck.py not found in $HERE" >&2; exit 1; }

# PyInstaller needs binutils (objdump) to inspect ELF binaries on Linux.
if ! command -v objdump >/dev/null 2>&1; then
    echo "ERROR: 'objdump' (binutils) is required by PyInstaller on Linux." >&2
    echo "  Install it with your package manager, e.g.:" >&2
    if command -v dnf >/dev/null 2>&1; then
        echo "    sudo dnf install binutils" >&2
    elif command -v zypper >/dev/null 2>&1; then
        echo "    sudo zypper install binutils" >&2
    elif command -v apt-get >/dev/null 2>&1; then
        echo "    sudo apt-get install binutils" >&2
    elif command -v pacman >/dev/null 2>&1; then
        echo "    sudo pacman -S binutils" >&2
    else
        echo "    (see your distribution's package manager)" >&2
    fi
    echo "  Re-run this script afterwards." >&2
    exit 1
fi

# ----------------------------- 1. virtualenv --------------------------------
VENV=".build_venv"
if [ ! -d "$VENV" ]; then
    echo "==> Creating build virtualenv: $VENV"
    "$PYTHON" -m venv "$VENV"
else
    echo "==> Reusing existing build virtualenv: $VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "==> Refreshing build dependencies in $VENV"
python -m pip install --upgrade pip >/dev/null
pip install -q pyinstaller "psutil>=5.9.0" "qrcode>=7.4" "pillow>=9.0"

# ------------------------------- 2. icon ------------------------------------
echo "==> Generating icon assets (build/rigcheck.png, build/rigcheck.ico)"
mkdir -p build
"$VENV/bin/python" - <<'PY'
from PIL import Image, ImageDraw
S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# dark rounded base plate
d.rounded_rectangle([14, 14, S - 14, S - 14], radius=52, fill=(27, 31, 38, 255))
# processor chip with pins
d.rounded_rectangle([56, 56, 200, 200], radius=22, fill=(16, 25, 28, 255),
                    outline=(126, 200, 255, 255), width=6)
for p in range(6):
    x = 88 + p * 16
    d.rectangle([x, 28, x + 8, 58], fill=(126, 200, 255, 255))
    d.rectangle([x, 198, x + 8, 228], fill=(126, 200, 255, 255))
    d.rectangle([28, 88 + p * 16, 58, 96 + p * 16], fill=(126, 200, 255, 255))
    d.rectangle([198, 88 + p * 16, 228, 96 + p * 16], fill=(126, 200, 255, 255))
# inner die
d.rounded_rectangle([90, 90, 166, 166], radius=14, fill=(50, 72, 88, 255))
d.rounded_rectangle([98, 98, 158, 158], radius=10, outline=(126, 200, 255, 200), width=4)
img.save("build/rigcheck.png")
img.save("build/rigcheck.ico", sizes=[(16, 16), (32, 32), (48, 48),
                                      (64, 64), (128, 128), (256, 256)])
print("    icons written")
PY

# --------------------------- 3. PyInstaller build ---------------------------
echo "==> Building RigCheck with PyInstaller (onedir)"
"$VENV/bin/python" -m PyInstaller \
    --noconfirm --clean --onedir --noupx \
    --name RigCheck \
    RigCheck.py >/dev/null

cp THIRD_PARTY_NOTICES.txt "dist/RigCheck/THIRD_PARTY_NOTICES.txt"

# ------------------------------ 4. AppDir -----------------------------------
echo "==> Assembling AppDir"
APPDIR="build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/rigcheck" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -r "dist/RigCheck/." "$APPDIR/usr/lib/rigcheck/"

cat > "$APPDIR/usr/share/applications/rigcheck.desktop" <<'EOF'
[Desktop Entry]
Name=RigCheck
GenericName=PC Diagnostics & Service Toolkit
Comment=Hardware diagnostics, monitoring and repair tools
Exec=RigCheck
Icon=rigcheck
Terminal=false
Type=Application
Categories=System;HardwareSettings;Monitor;
EOF
cp "$APPDIR/usr/share/applications/rigcheck.desktop" "$APPDIR/rigcheck.desktop"
cp build/rigcheck.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/rigcheck.png"
cp build/rigcheck.png "$APPDIR/rigcheck.png"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
set -e
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/rigcheck/RigCheck" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# ----------------------------- 5. appimagetool ------------------------------
APPIMAGE_TOOL="build/appimagetool"
if [ ! -x "$APPIMAGE_TOOL" ]; then
    echo "==> Downloading appimagetool"
    curl -fsSL -o "$APPIMAGE_TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGE_TOOL"
fi

echo "==> Bundling the AppImage (this may take a moment)"
# appimagetool is itself an AppImage: extract it if FUSE is unavailable.
if ! "$APPIMAGE_TOOL" --appimage-extract-and-run --help >/dev/null 2>&1; then
    "$APPIMAGE_TOOL" --appimage-extract >/dev/null 2>&1 || true
fi
if [ -x "build/squashfs-root/AppRun" ]; then
    "build/squashfs-root/AppRun" "$APPDIR" "dist/RigCheck-x86_64.AppImage"
else
    "$APPIMAGE_TOOL" "$APPDIR" "dist/RigCheck-x86_64.AppImage"
fi

echo
echo "==> Done: dist/RigCheck-x86_64.AppImage"
echo "    Test locally with:   ./dist/RigCheck-x86_64.AppImage --appimage-extract-and-run"
ls -lh "dist/RigCheck-x86_64.AppImage"