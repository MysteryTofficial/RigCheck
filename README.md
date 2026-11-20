# RigCheck

**RigCheck v1.0.0 — PC Diagnostics & Service Toolkit**  
*Made by: MysteryT*

RigCheck is a cross-platform (Windows & Linux) desktop diagnostics and service toolkit built with Python, Tkinter, and [psutil](https://github.com/giampaolo/psutil). It provides a single GUI for hardware inspection, sensor/health checks, BIOS & security status, reliability and repair helpers, peripheral tests, and network/security tools — with a live system dashboard, dark mode, and exportable reports.

> **Legal disclaimer:** RigCheck is provided for informational and diagnostic purposes only. Use this software **at your own risk**. The developer (MysteryT) assumes no liability for any data loss, hardware damage, or system issues resulting from its use.

## Features

- **Live system dashboard:** OS, CPU, RAM, system info, primary storage, network/local IP, and on-demand public IP (hidden by default for privacy).
- **Main:** S.M.A.R.T. check, CPU stress test, RAM inspection, network & latency, temperatures, Windows/Linux event logs, SFC/DISM & package integrity, Device Manager / lspci-lsusb, disk tools, memory diagnostic helpers, control/settings, startup check, and more.
- **Quick Reports:** Quick health summary, HTML report export, service tag + QR code generator, hardware signature scan/change detection.
- **Deep Sensors:** RAM/XMP info, DPC/latency hints, GPU details, SSD TBW/health, PSU/sensor hints, fan/RPM readings (where available).
- **BIOS & Security:** Secure Boot, boot mode, Resizable BAR hints, VBS/core isolation, fast startup status.
- **Reliability:** Reliability/history signals, pending updates/reboot checks, minidump/crash info, restore point/snapshot helpers.
- **Repair & Safety:** Guided repair/integrity checks, Winsock/TCP-IP reset helpers, bloat/startup review aids (platform-appropriate actions).
- **Peripherals:** Pixel/display checks, audio/surround test (stereo + true 5.1 channel-isolated WAVs), keyboard test, USB device view, sound settings launcher, HD Audio jack retask (detect-and-launch when `hdajackretask` is installed; never bundled).
- **Network & Security:** Wi-Fi/signal info, hosts file inspection/restore (with elevated/UAC path on Windows and sudo/pkexec path on Linux), MTU checks, firewall status.
- **Settings:** Theme (dark/light) saved to `~/.rigcheck/settings.json`, applied live.
- **Safety model:** RigCheck refuses to run as root/superuser. Privileged actions are performed via visible elevation prompts (UAC on Windows, sudo terminal/pkexec on Linux) with captured output where possible; nothing runs silently as admin.

## Requirements

- **Python 3.9+** (tested with modern CPython)
- **Tkinter** (usually included with Python; on some Linux distros install separately, e.g. `sudo dnf install python3-tkinter` / `sudo zypper install python3-tk` / `sudo pacman -S tk`)
- **psutil** (required)
- **qrcode** and **Pillow** (optional, for service tag + QR sticker rendering; the app falls back gracefully if missing)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running from source

```bash
python3 RigCheck.py
```

Run as a **normal user** (not root/Administrator). RigCheck will refuse to start with elevated privileges and will prompt for elevation only when a specific privileged action requires it.

## Building distributables (from Linux)

Two helper scripts are provided (run as a normal user, from the project directory):

- **Linux AppImage:** `./build_linux_appimage.sh` → `dist/RigCheck-x86_64.AppImage`  
  Requires `python3`, `curl`, and `binutils` (`objdump`). The script creates a local build venv, runs PyInstaller, and bundles an AppImage with `appimagetool`.

- **Windows .exe (cross-build from Linux):** `./build_windows_exe.sh` → `dist/RigCheck.exe`  
  Requires `python3`, `curl`, and 64-bit **Wine**. The script installs a Windows CPython into a local Wine prefix, installs build deps, and runs PyInstaller under Wine (`--onefile --windowed`).

Build artifacts (`build/`, `.build_venv/`, `dist/`) are ignored by git.

## Platform notes

- Many tools have **platform-specific implementations or equivalents** (e.g. `wmic`/PowerShell/`netsh`/registry on Windows; `/sys`/`/proc`/`lsblk`/`journalctl`/`nmcli`/package tools on Linux). Where a native equivalent does not exist, RigCheck reports that clearly instead of crashing.
- Some checks require optional system utilities (`smartctl`, `dmidecode`, `sensors`, `iw`, `nmcli`, `gparted`, `hdajackretask`, etc.). RigCheck detects availability and provides install hints (e.g. via your package manager) when missing.
- GUI appearance of dark mode depends on the Tk theme/backend; it is tested headlessly but should be visually verified on your system.

## Legal & licensing

- **RigCheck:** MIT License — see [LICENSE](LICENSE).
- **Third-party notices:** Techniques/dependencies adapted from or used with permissive licenses (stress-injector MIT, pystress BSD-2-Clause, qrcode BSD-3-Clause, Pillow HPND). Full texts: [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).
- **No GPL code bundled:** GPL tools such as `hdajackretask` (alsa-tools-gui) and `gparted` are **never bundled** — RigCheck only detects and launches them if already installed on your system. HDA pin information is read from plain kernel sysfs data.

## Contributing / uploading

This repository contains the source, license texts, build scripts, and documentation needed to build and distribute RigCheck. Do not commit generated reports, local settings (`~/.rigcheck/`), virtualenvs, or build outputs.
