#!/usr/bin/env bash
# =============================================================================
# build_windows_exe.sh - cross-build a RigCheck.exe for Windows FROM Linux.
#
#  1. Generates the icon (Pillow, host python venv)
#  2. Ensures a 64-bit Wine prefix + a Windows CPython under Wine
#  3. Installs pyinstaller + deps into that Windows python
#  4. Runs PyInstaller under Wine -> dist/RigCheck.exe (onefile, windowed)
#
# Requirements: bash, python3, curl, wine (64-bit).
# Output: dist/RigCheck.exe
#
# Optional overrides:
#   WINDOWS_PYTHON_VER=3.11.9   Python patch version to install under Wine
#   RIGCHECK_INSTALL_WINE=1     try to install Wine via your package manager
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# Same rule as the Linux script and the app itself: never build as root.
if [ "$(id -u)" = "0" ]; then
    echo "ERROR: do not run this script as root / with sudo." >&2
    echo "  Run it as a normal user instead:" >&2
    echo "    ./$(basename "$0")" >&2
    exit 1
fi

PYTHON="${PYTHON:-python3}"
PYVER="${WINDOWS_PYTHON_VER:-3.11.9}"
WINEPREFIX="$HERE/build/wineprefix"
export WINEPREFIX WINEDLLOVERRIDES="mscoree,mshtml="

[ -f "RigCheck.py" ] || { echo "ERROR: RigCheck.py not found in $HERE" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required." >&2; exit 1; }

# ------------------------------ Wine check ----------------------------------
if ! command -v wine >/dev/null 2>&1; then
    echo "ERROR: 'wine' (64-bit) is required to cross-build a Windows .exe." >&2
    echo "  Please install Wine first, for example:" >&2
    if command -v dnf >/dev/null 2>&1; then
        echo "    sudo dnf install wine" >&2
    elif command -v zypper >/dev/null 2>&1; then
        echo "    sudo zypper install wine" >&2
    elif command -v apt-get >/dev/null 2>&1; then
        echo "    sudo apt-get install wine64" >&2
    elif command -v pacman >/dev/null 2>&1; then
        echo "    sudo pacman -S wine" >&2
    else
        echo "    (see your distribution's package manager)" >&2
    fi
    echo "  Re-run this script afterwards." >&2
    exit 1
fi

if [ "${RIGCHECK_INSTALL_WINE:-0}" = "1" ]; then
    echo "==> Installing Wine with your package manager (asks for sudo)..."
    if command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y wine
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper --non-interactive install wine
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y wine64
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm wine
    fi
fi

# ------------------------------- icon ---------------------------------------
VENV=".build_venv"
if [ ! -d "$VENV" ]; then
    echo "==> Creating host virtualenv for icon generation"
    "$PYTHON" -m venv "$VENV"
else
    echo "==> Reusing build virtualenv: $VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "==> Refreshing host build deps in $VENV"
python -m pip install --upgrade pip >/dev/null
pip install -q "pillow>=9.0"

echo "==> Generating icon assets (build/rigcheck.png, build/rigcheck.ico)"
mkdir -p build
"$VENV/bin/python" - <<'PY'
from PIL import Image, ImageDraw
S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([14, 14, S - 14, S - 14], radius=52, fill=(27, 31, 38, 255))
d.rounded_rectangle([56, 56, 200, 200], radius=22, fill=(16, 25, 28, 255),
                    outline=(126, 200, 255, 255), width=6)
for p in range(6):
    x = 88 + p * 16
    d.rectangle([x, 28, x + 8, 58], fill=(126, 200, 255, 255))
    d.rectangle([x, 198, x + 8, 228], fill=(126, 200, 255, 255))
    d.rectangle([28, 88 + p * 16, 58, 96 + p * 16], fill=(126, 200, 255, 255))
    d.rectangle([198, 88 + p * 16, 228, 96 + p * 16], fill=(126, 200, 255, 255))
d.rounded_rectangle([90, 90, 166, 166], radius=14, fill=(50, 72, 88, 255))
d.rounded_rectangle([98, 98, 158, 158], radius=10, outline=(126, 200, 255, 200), width=4)
img.save("build/rigcheck.png")
img.save("build/rigcheck.ico", sizes=[(16, 16), (32, 32), (48, 48),
                                      (64, 64), (128, 128), (256, 256)])
print("    icons written")
PY

# ---------------------- Windows python install (once) ------------------------
WJPY="${PYVER%.*}"                # e.g. 3.11
WJ="$(echo "$WJPY" | tr -d '.')"  # e.g. 311
WPY="C:\\Python$WJ"
URL="https://www.python.org/ftp/python/$PYVER/python-$PYVER-amd64.exe"
INSTALLER="build/python-$PYVER-amd64.exe"

mkdir -p build
[ -d "$WINEPREFIX/drive_c" ] || mkdir -p "$WINEPREFIX"

if [ ! -f "$WINEPREFIX/drive_c/Python$WJ/python.exe" ]; then
    echo "==> Downloading Windows Python $PYVER"
    [ -f "$INSTALLER" ] || curl -fsSL -o "$INSTALLER" "$URL"
    echo "==> (Re)initialising Wine prefix (64-bit)"
    WINEARCH=win64 wineboot -u >/dev/null 2>&1 || true
    echo "==> Installing CPython $PYVER into the Wine prefix (silent)"
    wine start /wait "Z:\\${HERE//\//\\\\}\\$INSTALLER" \
        /quiet InstallAllUsers=1 TargetDir="C:\\Python$WJ" \
        PrependPath=1 Include_test=0 Include_launcher=0 Include_doc=0
else
    echo "==> Windows Python already installed in the prefix"
fi

WINPY="C:\\Python$WJ\\python.exe"
if ! wine "$WINPY" --version 2>/dev/null | grep -q "Python"; then
    echo "ERROR: wine python is not usable at $WINPY" >&2
    echo "  Delete '$WINEPREFIX' and re-run, or pick another WINDOWS_PYTHON_VER." >&2
    exit 1
fi

# ----------------------------- deps inside Wine -----------------------------
echo "==> Installing/upgrading pip + build deps inside Wine python"
wine "$WINPY" -m pip install -q --upgrade pip
wine "$WINPY" -m pip install -q pyinstaller "psutil>=5.9.0" \
    "qrcode>=7.4" "pillow>=9.0"

# --------------------------- PyInstaller (Ctrl) -----------------------------
echo "==> Building dist/RigCheck.exe with PyInstaller under Wine"
wine "$WINPY" -m PyInstaller \
    --noconfirm --clean --onefile --windowed \
    --name RigCheck \
    --icon=build/rigcheck.ico \
    RigCheck.py >/dev/null

cp THIRD_PARTY_NOTICES.txt dist/THIRD_PARTY_NOTICES.txt

echo
echo "==> Done: dist/RigCheck.exe"
echo "    Copy dist/RigCheck.exe (and THIRD_PARTY_NOTICES.txt) to a Windows PC."
ls -lh dist/RigCheck.exe