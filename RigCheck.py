#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#=============================================================================
# RigCheck v1.0.0 - PC Diagnostics & Service Toolkit
# Made by: MysteryT
#
# Cross-platform (Windows / Linux) PC diagnostic and system service toolkit.
# Built exclusively with standard Python libraries plus the free / open-source
# psutil module. Open-source friendly (MIT public-domain style code).
#
# LEGAL DISCLAIMER: RigCheck is provided for informational and diagnostic
# purposes only. Use this software at your own risk. The developer (MysteryT)
# assumes no liability for any data loss, hardware damage, or system issues
# resulting from its use.
#=============================================================================

import os
import re
import sys
import time
import queue
import shlex
import json
import html
import math
import wave
import struct
import tempfile
import platform
import socket
import shutil
import subprocess
import threading
import multiprocessing
import datetime
import urllib.request

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, scrolledtext, filedialog

import psutil

#------------------------------------------------------------------------------
# Application constants / branding
#------------------------------------------------------------------------------
APP_NAME = "RigCheck"
APP_VERSION = "v1.0.0"
AUTHOR_LABEL = "Made by: MysteryT"
BRANDING = f"{APP_NAME} {APP_VERSION} | {AUTHOR_LABEL}"
FULL_TITLE = f"{APP_NAME} - PC Diagnostics & Service Toolkit {APP_VERSION} - {AUTHOR_LABEL}"

DISCLAIMER_TEXT = (
    "LEGAL DISCLAIMER: RigCheck is provided for informational and diagnostic "
    "purposes only. Use this software at your own risk. The developer "
    "(MysteryT) assumes no liability for any data loss, hardware damage, or "
    "system issues resulting from its use."
)

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# Terminal emulators used on Linux to show CLI output / sudo prompts visibly.
TERMINAL_ARGS = {
    "konsole": lambda inner: ["konsole", "--hold", "-e", "bash", "-c", inner],
    "gnome-terminal": lambda inner: ["gnome-terminal",
                                     "--", "bash", "-c", inner],
    "xfce4-terminal": lambda inner: ["xfce4-terminal", "--hold",
                                     "-e", "bash", "-c", inner],
    "lxterminal": lambda inner: ["lxterminal",
                                 "--command=bash -c " + shlex.quote(inner)],
    "tilix": lambda inner: ["tilix", "-e", "bash", "-c", inner],
    "kitty": lambda inner: ["kitty", "bash", "-c", inner],
    "alacritty": lambda inner: ["alacritty", "-e", "bash", "-c", inner],
    "rxvt": lambda inner: ["rxvt", "-hold", "-e", "bash", "-c", inner],
    "xterm": lambda inner: ["xterm", "-hold", "-e", "bash", "-c", inner],
}
TERMINAL_SEARCH = list(TERMINAL_ARGS) + ["wezterm", "eterm", "weston-terminal"]


#------------------------------------------------------------------------------
# Small utility helpers
#------------------------------------------------------------------------------
def new_console_flag():
    """Return the Windows CREATE_NEW_CONSOLE flag when it exists."""
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def gb(num):
    """Format a byte count into a human-readable GB string."""
    try:
        return f"{num / (1024 ** 3):.2f} GB"
    except Exception:
        return "0.00 GB"


def format_uptime():
    """Return human readable system uptime from psutil.boot_time()."""
    try:
        elapsed = int(time.time() - psutil.boot_time())
        days, rem = divmod(elapsed, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        return f"{days}d {hours}h {mins}m {secs}s"
    except Exception:
        return "n/a"


def pick_monospace_font():
    """Pick the best available monospaced font family."""
    try:
        families = set(tkfont.families())
        for name in ("Consolas", "DejaVu Sans Mono", "Liberation Mono",
                     "Courier New", "Courier"):
            if name in families:
                return name
    except Exception:
        pass
    return "Courier"


#------------------------------------------------------------------------------
# CPU stress helper - one worker process per logical core.
# Technique adapted from the open-source projects below (see
# THIRD_PARTY_NOTICES.txt for the full license texts):
#   * stress-injector (MIT) - https://github.com/thevickypedia/stress-injector
#   * pystress (BSD-2-Clause) - https://github.com/shichao-an/pystress
#
# Real multi-core load requires one PROCESS per core: Python threads share
# the GIL, so thread-based busy loops cannot load more than a single core.
#------------------------------------------------------------------------------
def _cpu_stress_run():
    """Busy-loop body executed in each stress child process."""
    x = 0.0
    try:
        while True:
            for i in range(1_000_000):
                x = (x + (i & 1)) * 1.00000001 + 0.00001
                x = x % 2147483647.0
    except (KeyboardInterrupt, SystemExit):
        pass


#=============================================================================
# Theme + persisted settings
#=============================================================================
THEMES = {
    "dark": {
        "bg": "#1b1f26", "frame": "#16191e", "fg": "#c8d4dc",
        "text_bg": "#101418", "select": "#2d3a4a",
        "ts": "#6c7a85", "head": "#ffffff",
        "info": "#7ec8ff", "ok": "#6fe39f",
        "warn": "#ffd97a", "err": "#ff6b6b",
    },
    "light": {
        "bg": "#f0f0f0", "frame": "#e4e4e4", "fg": "#202020",
        "text_bg": "#ffffff", "select": "#cfe0f4",
        "ts": "#888888", "head": "#000000",
        "info": "#0b6bc2", "ok": "#1e7d3a",
        "warn": "#9a6700", "err": "#c62828",
    },
}

DEFAULT_SETTINGS = {
    "theme": "dark",   # "dark" or "light"
}


#=============================================================================
# Main application
#=============================================================================
class RigCheckApp:

    def __init__(self, root):
        self.root = root
        self.root.title(FULL_TITLE)
        self.root.geometry("1150x800")
        self.root.minsize(1000, 700)

        self._q = queue.Queue()
        self._mono = pick_monospace_font()
        self._cpu_name = self._get_cpu_name()
        self._pub_visible = False
        self._pub_fetching = False
        self._cleanup_guard = threading.Lock()

        # Persisted user settings (theme, ...) - loaded before the UI exists
        self._load_settings()

        # Linux terminal handling
        self.terminal = self._detect_terminal() if IS_LINUX else None
        self._stress_running = False
        self._stress_btn = None

        # StringVars for the live information panel
        self.os_var = tk.StringVar(value="Detecting...")
        self.cpu_var = tk.StringVar(value="Detecting...")
        self.ram_var = tk.StringVar(value="Detecting...")
        self.sys_var = tk.StringVar(value="Detecting...")
        self.stor_var = tk.StringVar(value="Detecting...")
        self.net_var = tk.StringVar(value="Detecting...")
        self.pub_ip_var = tk.StringVar(value="***** (hidden)")
        self.status_var = tk.StringVar(value="Ready")

        self._configure_styles()
        self._build_menu()
        self._build_ui()
        self._lock_ui_geometry()

        self._refresh_static_info()
        self._poll_queue()
        self.root.after(2000, self._tick)
        self.root.after(500, self._show_disclaimer)

    #--------------------------------------------------------------------------
    # UI construction
    #--------------------------------------------------------------------------
    def _configure_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("Helvetica", 15, "bold"))
        style.configure("Sub.TLabel", font=("Helvetica", 9))
        style.configure("InfoKey.TLabel", font=("Helvetica", 9, "bold"))
        style.configure("InfoVal.TLabel", font=(self._mono, 9))
        style.configure("Tool.TButton", padding=(8, 4))
        style.configure("TLabelframe", padding=6)
        style.configure("TLabelframe.Label", font=("Helvetica", 10, "bold"))
        style.configure("Status.TLabel", font=("Helvetica", 9))
        self._apply_theme()

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Export Log", command=self._export_log)
        file_menu.add_command(label="Clear Log", command=self._clear_log)
        file_menu.add_separator()
        file_menu.add_command(label="Settings...", command=self._settings_worker)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About / Legal Disclaimer",
                              command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

    def _lock_ui_geometry(self):
        # Size the window so all button text is readable: never below 1400x880,
        # honour the full requested width of the content, and clamp to the
        # available screen so the window is never pushed off-screen.
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        w = max(req_w, 1400)
        h = max(req_h, 880)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w = min(w, max(screen_w - 40, 1000))
        h = min(h, max(screen_h - 100, 700))
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 3)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(w, h)

    def _build_ui(self):
        #----------------------- HEADER with branding -------------------------
        # Tk labels are used (not ttk) so their colours always follow the
        # active theme - they are re-coloured by _apply_theme().
        header = tk.Frame(self.root, padx=12, pady=10, relief=tk.FLAT)
        header.pack(side=tk.TOP, fill=tk.X)
        self._header = header
        self._header_brand = tk.Label(header, text=BRANDING,
                                      font=("Helvetica", 15, "bold"),
                                      anchor="w", relief=tk.FLAT)
        self._header_brand.pack(side=tk.LEFT)
        self._header_sub = tk.Label(header, text="PC Diagnostics & "
                                    "Service Toolkit",
                                    font=("Helvetica", 9), anchor="e",
                                    relief=tk.FLAT)
        self._header_sub.pack(side=tk.RIGHT)
        self._apply_theme()

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=6)

        #----------------------- TOP: LIVE SYSTEM INFO -----------------------
        info_frame = ttk.LabelFrame(self.root, text="Live System Information",
                                    padding=8)
        info_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 4))

        rows = [
            ("Operating System", "os_var", self.os_var),
            ("Processor / CPU", "cpu_var", self.cpu_var),
            ("Memory / RAM", "ram_var", self.ram_var),
            ("System Info", "sys_var", self.sys_var),
            ("Primary Storage", "stor_var", self.stor_var),
            ("Network / Local IP", "net_var", self.net_var),
        ]
        for i, (key, name, var) in enumerate(rows):
            col = i % 2
            row = i // 2
            ttk.Label(info_frame, text=key + ":", style="InfoKey.TLabel"
                      ).grid(row=row, column=col * 2, sticky="ne", padx=(4, 6),
                             pady=2)
            ttk.Label(info_frame, textvariable=var, style="InfoVal.TLabel",
                      wraplength=430, justify="left",
                      anchor="w").grid(row=row, column=col * 2 + 1,
                                       sticky="w", padx=(0, 12), pady=2)

        # Public IP row (STREAMER PRIVACY FEATURE)
        pub_row = 3
        ttk.Label(info_frame, text="Public IP:",
                  style="InfoKey.TLabel").grid(row=pub_row, column=0,
                                               sticky="ne", padx=(4, 6), pady=2)
        self._pub_ip_label = ttk.Label(info_frame, textvariable=self.pub_ip_var,
                                       style="InfoVal.TLabel", wraplength=330,
                                       justify="left", anchor="w")
        self._pub_ip_label.grid(row=pub_row, column=1, sticky="w",
                                padx=(0, 12), pady=2)
        self._pub_btn = ttk.Button(info_frame, text=" [ Show Public IP ] ",
                                   command=self._toggle_public_ip)
        self._pub_btn.grid(row=pub_row, column=3, sticky="w", padx=4, pady=2)

        #----------------------- CENTER: TOOL NOTEBOOK -----------------------
        center = ttk.Frame(self.root, padding=8)
        center.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        nb = ttk.Notebook(center)
        nb.pack(fill=tk.BOTH, expand=True)

        #---------- Tab: Main (original core tools) ----------
        tab_main = ttk.Frame(nb, padding=6)
        nb.add(tab_main, text="Main")

        top_row = ttk.Frame(tab_main)
        top_row.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Section 1 - Hardware & Diagnostics
        self._section_hw = ttk.LabelFrame(top_row,
                                          text="Hardware & Diagnostics",
                                          padding=8)
        self._section_hw.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                              padx=(0, 4))
        hw_buttons = [
            ("S.M.A.R.T. Check", self._safe("SMART", lambda: self._smart_worker())),
            ("CPU Stress Test", self._safe("CPU Stress", lambda: self._stress_worker())),
            ("RAM Inspection", self._safe("RAM Inspect", lambda: self._ram_worker())),
            ("Network & Latency", self._safe("Net Test", lambda: self._net_worker())),
            ("Temperatures", self._safe("Temps", lambda: self._temp_worker())),
            ("Crash / Event Log", self._safe("Crash Log", lambda: self._crash_worker())),
        ]
        hw_grid = self._grid_buttons(self._section_hw, hw_buttons, rows=3)
        self._stress_btn = hw_grid.get("CPU Stress Test")

        # Section 2 - Native System Tools
        section_native = ttk.LabelFrame(top_row, text="Native System Tools",
                                        padding=8)
        section_native.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                            padx=4)
        native_buttons = [
            ("SFC / DISM", self._safe("SFC", lambda: self._sfc_worker())),
            ("Device Manager", self._safe("DevMgr", lambda: self._devmgr_worker())),
            ("Event Viewer", self._safe("EventVwr", lambda: self._eventvwr_worker())),
            ("Disk Management", self._safe("DiskMgmt", lambda: self._diskmgmt_worker())),
            ("Memory Diagnostic", self._safe("MDSched", lambda: self._mdsched_worker())),
            ("Network Connections", self._safe("NetCPL", lambda: self._ncpa_worker())),
            ("Control Panel / Settings", self._safe("Control", lambda: self._control_worker())),
        ]
        self._grid_buttons(section_native, native_buttons, rows=3)

        # Section 3 - Service Utilities
        section_svc = ttk.LabelFrame(tab_main, text="Service Utilities",
                                     padding=8)
        section_svc.pack(side=tk.TOP, fill=tk.X, pady=(6, 0))
        svc_buttons = [
            ("Startup Check", self._safe("Startup", lambda: self._startup_worker())),
            ("Clean Temp Files", self._safe("Temp Clean", lambda: self._tempclean_worker())),
            ("Flush DNS Cache", self._safe("FlushDNS", lambda: self._flushdns_worker())),
            ("Battery Report", self._safe("Battery", lambda: self._battery_worker())),
            ("Open Ports / Netstat", self._safe("Netstat", lambda: self._ports_worker())),
            ("System Terminal", self._safe("Terminal", lambda: self._terminal_worker())),
            ("Export Log", self._export_log),
            ("Clear Log", self._clear_log),
            ("Program Info", self._program_info),
            ("System Report", self._safe("Sys Report",
                                         lambda: self._system_report())),
        ]
        self._grid_buttons(section_svc, svc_buttons, rows=3)

        #---------- Tab: Quick Reports ----------
        tab_quick = ttk.Frame(nb, padding=8)
        nb.add(tab_quick, text="Quick Reports")
        sec_q = ttk.LabelFrame(tab_quick,
                               text="One-Click Diagnostics & Reporting",
                               padding=8)
        sec_q.pack(fill=tk.BOTH, expand=True)
        self._grid_buttons(sec_q, [
            ("Quick Health Check", self._safe(
                "Quick Health", lambda: self._quick_health())),
            ("Export HTML Report", self._safe(
                "HTML Report", lambda: self._html_report())),
            ("Service Tag + QR Code", self._safe(
                "Service Tag", lambda: self._service_tag())),
        ], rows=2)

        #---------- Tab: Deep Sensors ----------
        tab_sensors = ttk.Frame(nb, padding=8)
        nb.add(tab_sensors, text="Deep Sensors")
        sec_sensors = ttk.LabelFrame(
            tab_sensors, text="Deep Hardware & Sensor Diagnostics",
            padding=8)
        sec_sensors.pack(fill=tk.BOTH, expand=True)
        self._grid_buttons(sec_sensors, [
            ("RAM XMP / EXPO", self._safe(
                "RAM XMP", lambda: self._ram_xmp_worker())),
            ("DPC Latency", self._safe(
                "DPC Latency", lambda: self._dpc_worker())),
            ("GPU VRAM + PCIe", self._safe(
                "GPU/PCIe", lambda: self._gpu_worker())),
            ("SSD TBW + Health", self._safe(
                "SSD TBW", lambda: self._ssd_tbw_worker())),
            ("PSU Voltages", self._safe(
                "PSU Volts", lambda: self._psu_worker())),
            ("Fan Speeds (RPM)", self._safe(
                "Fan RPM", lambda: self._fan_worker())),
        ], rows=2)

        #---------- Tab: BIOS & Security ----------
        tab_bios = ttk.Frame(nb, padding=8)
        nb.add(tab_bios, text="BIOS & Security")
        sec_bios = ttk.LabelFrame(
            tab_bios, text="BIOS, Boot & Security Checks", padding=8)
        sec_bios.pack(fill=tk.BOTH, expand=True)
        self._grid_buttons(sec_bios, [
            ("Secure Boot + TPM", self._safe(
                "SecureBoot/TMP", lambda: self._secureboot_worker())),
            ("UEFI vs CSM Mode", self._safe(
                "Boot Mode", lambda: self._bootmode_worker())),
            ("Resizable BAR / SAM", self._safe(
                "ReBAR/SAM", lambda: self._rebar_worker())),
            ("VBS / Core Isolation", self._safe(
                "VBS/HVCI", lambda: self._vbs_worker())),
            ("Fast Startup Status", self._safe(
                "Fast Startup", lambda: self._faststartup_worker())),
        ], rows=2)

        #---------- Tab: Reliability ----------
        tab_rel = ttk.Frame(nb, padding=8)
        nb.add(tab_rel, text="Reliability")
        sec_rel = ttk.LabelFrame(
            tab_rel, text="System Updates & Reliability", padding=8)
        sec_rel.pack(fill=tk.BOTH, expand=True)
        self._grid_buttons(sec_rel, [
            ("Reliability Scanner", self._safe(
                "Reliability", lambda: self._reliability_worker())),
            ("Pending Updates + Reboot", self._safe(
                "Pending Upd", lambda: self._pending_worker())),
            ("Crash Minidump Analyzer", self._safe(
                "Minidump", lambda: self._minidump_worker())),
            ("Hardware Change Logger", self._safe(
                "Hw Changelog", lambda: self._hw_change_worker())),
        ], rows=2)

        #---------- Tab: Repair & Safety ----------
        tab_repair = ttk.Frame(nb, padding=8)
        nb.add(tab_repair, text="Repair & Safety")
        sec_repair = ttk.LabelFrame(
            tab_repair, text="Service Automation & Safety Tools", padding=8)
        sec_repair.pack(fill=tk.BOTH, expand=True)
        self._grid_buttons(sec_repair, [
            ("Create Restore Point", self._safe(
                "Restore Pt", lambda: self._restorepoint_worker())),
            ("SFC / DISM Repair Loop", self._safe(
                "Repair Loop", lambda: self._repair_worker())),
            ("Winsock / TCP-IP Reset", self._safe(
                "Winsock Reset", lambda: self._winsock_worker())),
            ("Temp + Bloat Cleaner", self._safe(
                "Bloat Clean", lambda: self._bloat_worker())),
        ], rows=2)

        #---------- Tab: Peripherals ----------
        tab_media = ttk.Frame(nb, padding=8)
        nb.add(tab_media, text="Peripherals")
        sec_media = ttk.LabelFrame(
            tab_media, text="Peripheral & Media Testing", padding=8)
        sec_media.pack(fill=tk.BOTH, expand=True)
        self._grid_buttons(sec_media, [
            ("Monitor Pixel Checker", self._pixel_worker),
            ("Audio Surround Test", lambda: self._safe(
                "Audio", self._audio_worker)()),
            ("Sound Settings", self._safe(
                "SoundSet", lambda: self._sound_settings_worker())),
            ("Remap Jack", self._safe(
                "HDJack", lambda: self._hdajack_worker())),
            ("Keyboard + Mouse Test", self._keyboard_worker),
            ("USB & Controller Check", self._safe(
                "USB", lambda: self._usb_worker())),
        ], rows=2)

        #---------- Tab: Network & Security ----------
        tab_netsec = ttk.Frame(nb, padding=8)
        nb.add(tab_netsec, text="Network & Security")
        sec_netsec = ttk.LabelFrame(
            tab_netsec, text="Network, Security & Maintenance", padding=8)
        sec_netsec.pack(fill=tk.BOTH, expand=True)
        self._grid_buttons(sec_netsec, [
            ("Wi-Fi Signal Analyzer", self._safe(
                "Wi-Fi", lambda: self._wifi_worker())),
            ("Hosts File Inspector", self._safe(
                "Hosts", lambda: self._hosts_worker())),
            ("MTU Size Test", self._safe(
                "MTU", lambda: self._mtu_worker())),
            ("Firewall + Antivirus", self._safe(
                "FW/AV", lambda: self._firewall_worker())),
        ], rows=2)

        #----------------------- BOTTOM: LOG CONSOLE -------------------------
        log_frame = ttk.LabelFrame(self.root, text="Diagnostic Console Log",
                                   padding=6)
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True,
                       padx=8, pady=8)

        self._log = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, state=tk.NORMAL, height=14,
            font=(self._mono, 9), relief=tk.FLAT)
        self._log.pack(fill=tk.BOTH, expand=True)
        self._apply_theme()

        #----------------------- STATUS BAR ---------------------------------
        status_bar = ttk.Frame(self.root, padding=(8, 3))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_var,
                  style="Status.TLabel", anchor="w").pack(side=tk.LEFT)
        ttk.Label(status_bar, text=BRANDING, style="Status.TLabel",
                  anchor="e").pack(side=tk.RIGHT)

    def _grid_buttons(self, frame, buttons, rows=6):
        """Lay the buttons out in a grid so every column gets equal width."""
        n = len(buttons)
        columns = (n + rows - 1) // rows
        mapping = {}
        for idx, (text, cmd) in enumerate(buttons):
            col = idx // rows
            row = idx % rows
            b = ttk.Button(frame, text=text, style="Tool.TButton",
                           command=cmd)
            b.grid(row=row, column=col, sticky="ew", padx=3, pady=3)
            mapping[text] = b
        for c in range(columns):
            frame.columnconfigure(c, weight=1, uniform="tools")
        if not columns:
            frame.columnconfigure(0, weight=1)
        return mapping

    #--------------------------------------------------------------------------
    # Thread-safe helpers: every call from a worker thread goes through a queue
    #--------------------------------------------------------------------------
    def log(self, kind, text):
        self._q.put((kind, text))

    def log_info(self, text):
        self._q.put(("INFO", text))

    def log_ok(self, text):
        self._q.put(("OK", text))

    def log_warn(self, text):
        self._q.put(("WARN", text))

    def log_err(self, text):
        self._q.put(("ERR", text))

    def log_head(self, text):
        self._q.put(("HEAD", text))

    def status(self, text):
        self._q.put(("STATUS", text))

    def ask_user(self, title, message, paths):
        self._q.put(("ASK", title, message, paths))

    def _poll_queue(self):
        """Drain the worker -> UI queue on the main thread every 80 ms."""
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]
                if kind == "STATUS":
                    self.status_var.set(item[1])
                elif kind == "ASK":
                    _, title, message, paths = item
                    proceed = messagebox.askyesno(title, message)
                    if proceed:
                        threading.Thread(target=self._purge_files,
                                         args=(paths,), daemon=True).start()
                else:
                    ts = time.strftime("[%H:%M:%S]")
                    tag = {"INFO": "info", "OK": "ok", "WARN": "warn",
                           "ERR": "err", "HEAD": "head"}.get(kind, "info")
                    self._log.insert(tk.END, ts + " ", "ts")
                    self._log.insert(tk.END, item[1] + "\n", tag)
                    self._log.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _safe(self, title, target):
        """Wrap a worker method so it always runs inside a daemon thread."""
        def runner():
            self.status(f"Running {title.title()}...")
            try:
                target()
            except Exception as exc:
                self.log_err(f"Unhandled error in {title}: {exc}")
            finally:
                self.status("Ready")
        return lambda: threading.Thread(target=runner, daemon=True).start()

    def _run(self, args, timeout=60, shell=False):
        """Run a subprocess and capture stdout+stderr as text."""
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                shell=shell, text=True, errors="replace")
            out, _ = proc.communicate(timeout=timeout)
            return proc.returncode, (out or "").strip()
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            return -1, "[TIMEOUT - command took too long]"
        except Exception as exc:
            return -1, f"[ERROR] {exc}"

    def _log_output(self, label, code, output, max_lines=120):
        """Log wrapped command output line-by-line with truncation."""
        lines = output.splitlines() if output else []
        for line in lines[:max_lines]:
            self.log_info("  " + line)
        if len(lines) > max_lines:
            self.log_warn(f"  ... output truncated "
                          f"({len(lines) - max_lines} more lines)")
        status = "OK" if code == 0 else ("WARN" if code is None else "ERR")
        self.log(status, f"  [{label}] exit code: {code}  "
                         f"({len(lines)} lines)")

    #--------------------------------------------------------------------------
    # Static hardware discovery
    #--------------------------------------------------------------------------
    def _get_cpu_name(self):
        try:
            name = platform.processor()
            if name and name.strip():
                return name.strip()
        except Exception:
            pass
        if IS_LINUX:
            try:
                with open("/proc/cpuinfo", "r", errors="replace") as fh:
                    for line in fh:
                        if line.lower().startswith("model name"):
                            return line.split(":", 1)[1].strip()
            except Exception:
                pass
        return "Unknown CPU"

    def _get_os_label(self):
        if IS_LINUX and os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release", "r", errors="replace") as fh:
                    for line in fh:
                        if line.startswith("PRETTY_NAME="):
                            return line.split("=", 1)[1].strip().strip('"')
            except Exception:
                pass
        return f"{platform.system()} {platform.release()}"

    def _refresh_static_info(self):
        try:
            arch = platform.machine() or platform.architecture()[0]
            self.os_var.set(f"{self._get_os_label()}"
                            f"  ({platform.system()} {arch})")
        except Exception as exc:
            self.os_var.set(f"OS detect error: {exc}")

    def _storage_summary(self):
        try:
            parts = [p for p in psutil.disk_partitions() if p.fstype]
            if not parts:
                return "No storage partitions detected"
            pick = None
            if IS_WINDOWS:
                sys_drive = os.environ.get("SystemDrive", "C:")
                pick = next(
                    (p for p in parts
                     if p.mountpoint.replace("\\", "").upper()
                     == sys_drive.upper()
                     or p.mountpoint.upper().startswith(sys_drive.upper())),
                    None) or parts[0]
            else:
                pick = next((p for p in parts if p.mountpoint == "/"),
                            None)
                if pick is None:
                    home = os.path.expanduser("~")
                    by_home = [p for p in parts
                               if home.startswith(p.mountpoint) and p.mountpoint != "/"]
                    if by_home:
                        pick = max(by_home,
                                   key=lambda p: len(p.mountpoint))
                if pick is None:
                    sized = []
                    for part in parts:
                        try:
                            sized.append(
                                (part, psutil.disk_usage(part.mountpoint).total))
                        except Exception:
                            continue
                    if sized:
                        pick = max(sized, key=lambda x: x[1])[0]
            if pick is None:
                return "No primary storage partition found"
            usage = psutil.disk_usage(pick.mountpoint)
            return (f"{pick.mountpoint} | Total {gb(usage.total)} | "
                    f"Free {gb(usage.free)} | Used {usage.percent:.1f}%")
        except Exception as exc:
            return f"Storage error: {exc}"

    def _net_label(self):
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for iface, entries in addrs.items():
                for entry in entries:
                    family = getattr(entry.family, "name", None) or entry.family
                    is_v4 = (family == "AF_INET") or (family == socket.AF_INET)
                    if is_v4 and not entry.address.startswith("127."):
                        st = stats.get(iface)
                        state = ""
                        if st is not None:
                            state = f"  ({'UP' if st.isup else 'DOWN'})"
                        return f"{iface} | {entry.address}{state}"
            return "No active LAN interface"
        except Exception as exc:
            return f"Network error: {exc}"

    # Periodic 2-second refresh of the live panel (non-blocking polling).
    def _tick(self):
        try:
            mem = psutil.virtual_memory()
            load = psutil.cpu_percent(interval=None)

            try:
                freq = psutil.cpu_freq()
                freq_txt = f"{int(freq.current)} MHz" if freq and freq.current else "n/a"
            except Exception:
                freq_txt = "n/a"

            phys = psutil.cpu_count(logical=False)
            logc = psutil.cpu_count(logical=True)

            self.cpu_var.set(
                f"{self._cpu_name} | {phys or '?'} physical / "
                f"{logc or '?'} threads | {freq_txt} | Load {load:.1f}%")
            self.ram_var.set(
                f"Total {gb(mem.total)} | Used {mem.percent:.1f}% | "
                f"Free {gb(mem.available)}")
            self.sys_var.set(
                f"{socket.gethostname() or platform.node()} | "
                f"Uptime {format_uptime()}")
            self.stor_var.set(self._storage_summary())
            self.net_var.set(self._net_label())
        except Exception as exc:
            self.log_err(f"Live refresh error: {exc}")
        self.root.after(2000, self._tick)

    #--------------------------------------------------------------------------
    # STREAMER PRIVACY FEATURE - public IP stays hidden until requested
    #--------------------------------------------------------------------------
    def _toggle_public_ip(self):
        if self._pub_visible:
            self._pub_visible = False
            self.pub_ip_var.set("***** (hidden)")
            self._pub_btn.config(text=" [ Show Public IP ] ")
            self.log_info("Public IP hidden again (privacy preserved).")
            return
        if self._pub_fetching:
            return
        self._pub_fetching = True
        self.pub_ip_var.set("Fetching (one-time, on demand)...")
        threading.Thread(target=self._fetch_public_ip, daemon=True).start()

    def _fetch_public_ip(self):
        try:
            request = urllib.request.Request(
                "https://api.ipify.org", headers={"User-Agent": BRANDING})
            with urllib.request.urlopen(request, timeout=8) as resp:
                ip = resp.read().decode("utf-8").strip()
            self.log_ok(f"Public IP fetched on demand: {ip}")
            self._pub_visible = True
            # UI updates must happen on the Tk main thread.
            self.root.after(0, lambda: self.pub_ip_var.set(ip))
            self.root.after(0, lambda: self._pub_btn.config(
                text=" [ Hide Public IP ] "))
            self.root.after(0, lambda: self.status_var.set(
                f"Public IP: {ip}"))
        except Exception as exc:
            self.log_warn(f"Could not fetch public IP: {exc}")
            self.root.after(0, lambda: self.pub_ip_var.set(
                "***** (hidden - fetch failed)"))
            self.root.after(0, lambda: self.status_var.set("Ready"))
        finally:
            self._pub_fetching = False

    #--------------------------------------------------------------------------
    # Detached process launching + Linux terminal handling
    #--------------------------------------------------------------------------
    def _spawn_detached(self, argv, cwd=None, env=None):
        """Launch a process fully detached so its output never pollutes
        RigCheck's own console. GUI apps such as Konsole print Qt/DBus
        portal warnings to stderr when spawned; those must go to DEVNULL
        instead of the terminal running RigCheck."""
        try:
            use_shell = isinstance(argv, str)
            kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "creationflags": new_console_flag(),
            }
            if use_shell:
                kwargs["shell"] = True
            if not IS_WINDOWS:
                kwargs["start_new_session"] = True
            if cwd:
                kwargs["cwd"] = cwd
            if env:
                kwargs["env"] = env
            return subprocess.Popen(argv, **kwargs)
        except Exception as exc:
            shown = argv if isinstance(argv, str) else " ".join(argv)
            self.log_err(f"  Could not launch {shown}: {exc}")
            return None

    @staticmethod
    def _detect_terminal():
        for name in TERMINAL_SEARCH:
            if shutil.which(name):
                return name
        return None

    def _terminal_open(self):
        """Open a command prompt / terminal - its default shell only."""
        if IS_WINDOWS:
            self.log_info("  Opening a new PowerShell window...")
            spawned = self._spawn_detached(["powershell"],
                                           cwd=os.path.expanduser("~"))
            return spawned is not None
        terminal = self.terminal
        if not terminal:
            self.log_err("  No supported terminal emulator found "
                         "(install xterm, konsole or gnome-terminal).")
            return False
        self.log_info(f"  Opening terminal: {terminal}")
        spawned = self._spawn_detached([terminal],
                                       cwd=os.path.expanduser("~"))
        return spawned is not None

    def _terminal_run(self, command, keep_open=True):
        """Run a command in a VISIBLE console window (cmd/PowerShell on
        Windows, konsole/xterm/... on Linux)."""
        if IS_WINDOWS:
            self.log_info(f"  Opening a console window to run: {command}")
            cmdline = "cmd /K " + command
            return self._spawn_detached(
                cmdline, cwd=os.path.expanduser("~")) is not None
        terminal = self.terminal
        if not terminal:
            self.log_err("  No supported terminal emulator found "
                         "(install xterm, konsole or gnome-terminal).")
            return False
        inner = command
        if keep_open:
            inner += ("\n\necho\n"
                      f"echo '[{APP_NAME}] process finished - press Enter "
                      "to close this window.'\n"
                      "read -r _")
        launcher = TERMINAL_ARGS.get(terminal)
        args = launcher(inner) if launcher else \
            [terminal, "-e", "bash", "-c", inner]
        self.log_info(f"  Opening terminal ({terminal}) to run: {command}")
        env = dict(os.environ)
        env.setdefault("HOME", os.path.expanduser("~"))
        spawned = self._spawn_detached(args, cwd=os.path.expanduser("~"),
                                       env=env)
        return spawned is not None

    def _terminal_run_captured(self, command, timeout=120):
        """Run a command in a visible terminal; ALSO capture its output so it
        can be written into the GUI console log. Returns the output text or
        None on failure / timeout."""
        if IS_WINDOWS:
            # Windows has no 'tee' pipeline; elevated work is captured via
            # _run_root_batch's UAC path instead. Just run it visibly.
            self._terminal_run(command, keep_open=True)
            return None
        terminal = self.terminal
        if not terminal:
            self.log_err("  No supported terminal emulator found "
                         "(install xterm, konsole or gnome-terminal).")
            return None
        try:
            tmp = tempfile.NamedTemporaryFile(
                prefix="rigcheck_capture_", suffix=".txt", delete=False)
            out_path = tmp.name
            tmp.close()
        except Exception as exc:
            self.log_err(f"  Could not create capture file: {exc}")
            return None
        done_path = out_path + ".done"
        for path in (out_path, done_path):
            try:
                os.unlink(path)
            except OSError:
                pass

        wrapped = ("{ " + command + "; } 2>&1 | tee "
                   + shlex.quote(out_path) + "\n"
                   + "touch " + shlex.quote(done_path))
        self.log_info("  The terminal output will also appear in the log "
                      "below once the command completes.")
        if not self._terminal_run(wrapped, keep_open=True):
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(done_path):
                break
            if not self.terminal:
                break
            time.sleep(0.5)

        if not os.path.exists(done_path):
            self.log_warn("  Timed out waiting for the terminal command "
                          f"to finish ({timeout}s).")
            return None

        try:
            with open(out_path, "r", errors="replace") as fh:
                text = fh.read()
        except Exception as exc:
            self.log_warn(f"  Could not read captured output: {exc}")
            return None
        finally:
            for path in (out_path, done_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return text

    def _am_root(self):
        try:
            return os.geteuid() == 0
        except Exception:
            return False

    def _run_root_batch(self, commands, timeout=150):
        """Run a list of shell commands with elevation, using a VISIBLE
        privilege prompt - the same principle as the smartctl/dmesg sudo
        terminal on Linux. On Windows it runs an elevated PowerShell via
        UAC; on Linux a visible 'sudo' terminal (pkexec as a fallback). Bare
        unobtrusive elevation is never used. Returns (code, output)."""
        steps = "; ".join(commands)

        # ---- Windows: elevated PowerShell (UAC is always a visible prompt)
        if IS_WINDOWS:
            self.log_info("  This needs administrator rights - a UAC prompt "
                          "will appear; press Yes to continue.")
            fwd = lambda p: p.replace("\\", "/")
            out_tmp = tempfile.NamedTemporaryFile(
                prefix="rigcheck_uac_", suffix=".txt", delete=False)
            out_path = out_tmp.name
            out_tmp.close()
            script = ("$ErrorActionPreference = 'Continue'\n"
                      "& { " + "; ".join(commands) + " } 2>&1 | "
                      "Out-File -FilePath '" + fwd(out_path)
                      + "' -Encoding utf8")
            script_tmp = tempfile.NamedTemporaryFile(
                prefix="rigcheck_uac_", suffix=".ps1", delete=False,
                mode="w", encoding="utf-8")
            script_tmp.write(script)
            script_path = script_tmp.name
            script_tmp.close()
            code, out = self._run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-Command",
                "Start-Process powershell -Verb RunAs -Wait "
                "-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',"
                "'-File','" + fwd(script_path) + "'"], timeout=timeout)
            text = ""
            try:
                with open(out_path, "r", errors="replace") as fh:
                    text = fh.read()
            except Exception:
                pass
            finally:
                for p in (out_path, script_path):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
            if text.strip():
                return 0, text
            if code == 0:
                return 0, ""
            self.log_warn("  The elevated console did not run (was the UAC "
                          "prompt accepted?).")
            return code, out or ""

        # ---- Linux: visible sudo terminal (already root -> run directly)
        if self._am_root():
            return self._run(["sh", "-c", steps], timeout=timeout)
        terminal = getattr(self, "terminal", None)
        if terminal:
            self.log_info("  This needs root - opening a sudo terminal.")
            self.log_info("  Type your password when prompted; the output "
                          "is also copied into the log below.")
            output = self._terminal_run_captured(
                "sudo sh -c " + shlex.quote(steps), timeout=timeout)
            if output is not None:
                return 0, output
            self.log_warn("  No output was captured (password cancelled or "
                          "the terminal timed out).")
            return -1, ""
        if shutil.which("pkexec"):
            self.log_info("  Using pkexec (graphical password prompt).")
            return self._run(
                ["pkexec", "sh", "-c", " ".join(commands)], timeout=timeout)
        self.log_warn("  This needs root, but no terminal emulator or "
                      "pkexec is available here.")
        self.log_info("  Run it yourself: "
                      + " && ".join(commands))
        return -1, ""

    def _set_button_state(self, button, enabled):
        try:
            if button is not None:
                state = tk.NORMAL if enabled else tk.DISABLED
                self.root.after(0, lambda: button.config(state=state))
        except Exception:
            pass

    def _terminal_worker(self):
        self.log_head("========== System Terminal ==========")
        self.log_info("  The System Terminal button only opens a terminal "
                      "window - it does not run any scripts or commands.")
        if not self._terminal_open():
            self.log_warn("  Could not open a terminal window.")

    #--------------------------------------------------------------------------
    # Disclaimer / about
    #--------------------------------------------------------------------------
    def _show_disclaimer(self):
        messagebox.showinfo("RigCheck - Legal Disclaimer", DISCLAIMER_TEXT)

    def _show_about(self):
        messagebox.showinfo(
            "About RigCheck",
            f"{BRANDING}\n\n"
            "PC Diagnostics & Service Toolkit\n\n"
            "Open-source (MIT-friendly) desktop diagnostic application built "
            "with Python, Tkinter and psutil.\n\n"
            "Features:\n"
            "- Live system information panel\n"
            "- Hardware diagnostics (SMART, CPU stress, RAM, network, temps)\n"
            "- Crash / event log filtering\n"
            "- Native OS tool launcher\n"
            "- Service utilities (startup, temp cleaning, DNS, battery, "
            "ports)\n\n"
            "Open-source credits:\n"
            "- CPU stress test technique: stress-injector (MIT) and "
            "pystress (BSD-2-Clause)\n"
            "- See THIRD_PARTY_NOTICES.txt for the required license "
            "texts.\n\n"
            f"{DISCLAIMER_TEXT}")

    #==========================================================================
    # SECTION 1 - HARDWARE & DIAGNOSTICS
    #==========================================================================
    def _smart_worker(self):
        self.log_head("========== S.M.A.R.T. Check ==========")
        if IS_WINDOWS:
            self._smart_windows()
        elif IS_LINUX:
            self._smart_linux()
        else:
            self.log_warn("SMART not supported on this platform.")

    def _smart_windows(self):
        self.log_info("Querying physical disks via PowerShell...")
        ps_code = (
            "Get-PhysicalDisk | Select-Object FriendlyName, SerialNumber, "
            "MediaType, BusType, HealthStatus, OperationalStatus, "
            "@{n='Size(GB)';e={[math]::Round($_.Size/1GB,1)}} "
            "| Format-List")
        code, out = self._run(
            ["powershell", "-NoProfile", "-Command", ps_code], timeout=60)
        if code == 0 and out:
            self._log_output("S.M.A.R.T. disks", code, out, 80)
        else:
            self.log_warn("Get-PhysicalDisk failed - falling back to WMI...")
            code, out = self._run(
                ["wmic", "diskdrive", "get", "model,status,serialnumber"],
                timeout=40)
            if out:
                self._log_output("WMI diskdrive", code, out, 60)
            else:
                self.log_warn("No SMART data available (WMI missing).")

        self.log_info("Fetching wear level / temperature counters...")
        ps_wear = (
            "Get-PhysicalDisk | Get-StorageReliabilityCounter | "
            "Select-Object DeviceId, Wear, Temperature, "
            "ReadErrorsCorrected, WriteErrorsCorrected | Format-List")
        code, out = self._run(
            ["powershell", "-NoProfile", "-Command", ps_wear], timeout=60)
        if out:
            self._log_output("S.M.A.R.T. reliability", code, out, 80)
        else:
            self.log_warn("Reliability counters unavailable "
                          "(may require Administrator rights).")

    def _smart_linux(self):
        if not shutil.which("smartctl"):
            self.log_warn("smartmontools not installed. Install it with "
                          "your package manager, e.g. on Fedora: "
                          "sudo dnf install smartmontools")
            return

        code, out = self._run(
            ["lsblk", "-d", "-o", "NAME,SIZE,MODEL", "-n"], timeout=20)
        disks = [ln.split()[0] for ln in out.splitlines()
                 if ln.strip() and not ln.split()[0].startswith("loop")]
        if not disks:
            self.log_warn("No block devices found via lsblk.")
            disks = ["sda"]

        already_root = False
        try:
            already_root = os.geteuid() == 0
        except Exception:
            pass

        # smartctl genuinely needs root. It uses the SAME visible-sudo mechanism as
        # the other root tools (see _run_root_batch): the command runs in a
        # visible terminal so the password prompt is never hidden, and its
        # output is ALSO captured into a temp file and written to the console
        # log below.
        if not already_root and self.terminal:
            steps = []
            for disk in disks:
                steps.append(f"echo ============ /dev/{disk} ============")
                steps.append(f"smartctl -H /dev/{disk}")
                steps.append(f"smartctl -A /dev/{disk}")
            command = "sudo sh -c " + shlex.quote("; ".join(steps))
            self.log_info("  smartctl needs root - opening a sudo terminal "
                          "to run the S.M.A.R.T. checks.")
            self.log_info("  Type your password when prompted; the results "
                          "are also copied into the console log below.")
            output = self._terminal_run_captured(command, timeout=150)
            if output and output.strip():
                self.log_head("  S.M.A.R.T. results (root):")
                for line in output.splitlines():
                    if line.strip():
                        self.log_info("  " + line.strip())
                self.log_info("  End of S.M.A.R.T. results.")
            else:
                self.log_warn("  No S.M.A.R.T. output captured (was the "
                              "password entered / did the check finish?).")
            return

        for disk in disks:
            self.log_head(f"--- {disk} ---")

            base = ["smartctl"]
            if not already_root and shutil.which("pkexec"):
                base = ["pkexec", "smartctl"]
                self.log_info("  Using pkexec (graphical password prompt).")

            code, out = self._run(
                base + ["-H", f"/dev/{disk}"], timeout=40)
            if code == 0 and out:
                for line in out.splitlines():
                    if ("health" in line.lower()
                            or "result" in line.lower()):
                        self.log_info(f"  {line.strip()}")
            else:
                self.log_warn(
                    f"smartctl needs root for /dev/{disk}: {out}")

            code, out = self._run(
                base + ["-A", f"/dev/{disk}"], timeout=40)
            if out:
                self._smart_parse_attributes(out)

    def _smart_parse_attributes(self, output):
        for line in output.splitlines():
            if re.search(r"(Temperature_Celsius|Current_Pending_Sector|"
                         r"Reallocated_Sector_Ct|Wear_Leveling|"
                         r"Percent_Lifetime_Remain|Media_Wearout_Indicator)",
                         line):
                parts = line.split()
                if len(parts) >= 10:
                    attr_id = parts[0]
                    name = parts[1]
                    value = parts[3]
                    raw = parts[9]
                    self.log_info(
                        f"    [{attr_id}] {name}: value={value} "
                        f"raw={raw}")

    def _stress_worker(self):
        self.log_head("========== CPU Stress Test (30 seconds) ==========")
        if self._stress_running:
            self.log_warn("  A CPU stress test is already running - please "
                          "wait for it to finish.")
            return
        self._stress_running = True
        self._set_button_state(self._stress_btn, False)
        duration = 30
        procs = []
        try:
            cores = psutil.cpu_count(logical=True) or 4
            self.log_info(f"Stressing {cores} logical cores using "
                          f"{cores} separate PROCESSES ({duration}s)...")
            self.log_info("  A real process per core is used (not threads) "
                          "so every core is genuinely loaded.")
            ctx = multiprocessing.get_context()
            for _ in range(cores):
                proc = ctx.Process(target=_cpu_stress_run, daemon=True)
                proc.start()
                procs.append(proc)

            start = time.time()
            samples = []
            # Measure per-core utilization once per second while stressing.
            while time.time() - start < duration:
                per_core = psutil.cpu_percent(interval=1, percpu=True)
                if per_core:
                    samples.append(per_core)
                    elapsed = time.time() - start
                    avg = sum(per_core) / len(per_core)
                    self.log_info(
                        f"  [{elapsed:4.0f}s] per-core utilization: "
                        f"avg {avg:5.1f}%  peak {max(per_core):5.1f}%")

            self.log_ok(f"Stress load finished after {duration}s.")
            self.log_head("  CPU utilization report (per logical core):")
            if samples:
                for i in range(len(samples[0])):
                    vals = [s[i] for s in samples if i < len(s)]
                    if vals:
                        avg_val = sum(vals) / len(vals)
                        self.log_info(
                            f"    Core {i + 1}: avg {avg_val:5.1f}%  "
                            f"max {max(vals):5.1f}%")
                all_avg = sum(sum(s) / len(s) for s in samples) / len(samples)
                self.log_ok(f"  Result: {all_avg:.1f}% average utilization "
                            f"across {len(samples[0])} logical cores.")
            else:
                self.log_warn("  No utilization samples were collected.")
        except Exception as exc:
            self.log_err(f"  CPU stress test failed: {exc}")
        finally:
            for proc in procs:
                try:
                    proc.terminate()
                except Exception:
                    pass
            for proc in procs:
                try:
                    proc.join(timeout=5)
                except Exception:
                    pass
            self._stress_running = False
            self._set_button_state(self._stress_btn, True)

    def _ram_worker(self):
        self.log_head("========== RAM Inspection ==========")
        try:
            mem = psutil.virtual_memory()
            self.log_info(f"  Total:               {gb(mem.total)}")
            self.log_info(f"  Available:           {gb(mem.available)}")
            self.log_info(f"  Used:                {gb(mem.used)} "
                          f"({mem.percent:.1f}%)")
            self.log_info(f"  Free:                {gb(mem.free)}")
            buffers = getattr(mem, "buffers", 0) or 0
            cached = getattr(mem, "cached", 0) or 0
            if buffers or cached:
                self.log_info(f"  Buffers:             {gb(buffers)}")
                self.log_info(f"  Cached:              {gb(cached)}")
        except Exception as exc:
            self.log_err(f"  Memory data error: {exc}")

        try:
            swap = psutil.swap_memory()
            self.log_info(f"  SWAP total:          {gb(swap.total)}")
            self.log_info(f"  SWAP used:           {gb(swap.used)} "
                          f"({swap.percent:.1f}%)")
            self.log_info(f"  SWAP free:           {gb(swap.free)}")
        except Exception as exc:
            self.log_warn(f"  Swap info unavailable: {exc}")
        self.log_ok("RAM inspection complete.")

    def _net_worker(self):
        self.log_head("========== Network & Latency ==========")
        try:
            self.log_info(f"  Adapter: {self._net_label()}")
            for ifname, st in psutil.net_if_stats().items():
                speed = getattr(st, "speed", 0) or 0
                if speed:
                    speed_txt = (f"{speed / 1000:.1f} Gb/s"
                                 if speed > 1000 else f"{speed} Mb/s")
                else:
                    speed_txt = "unknown"
                self.log_info(
                    f"  {ifname}: {'UP' if st.isup else 'DOWN'} | "
                    f"duplex={st.duplex} | MTU={st.mtu} | speed={speed_txt}")
        except Exception as exc:
            self.log_err(f"  Adapter info error: {exc}")

        for name, host in (("Google", "8.8.8.8"),
                           ("Cloudflare", "1.1.1.1")):
            self._ping_diag(name, host)

    def _ping_diag(self, name, host):
        if IS_WINDOWS:
            args = ["ping", "-n", "4", host]
            pattern = re.compile(r"Average\s*=\s*(\d+)ms", re.IGNORECASE)
            loss_pat = re.compile(r"Lost\s*=\s*\d+\s*\(\s*(\d+)%",
                                  re.IGNORECASE)
        else:
            args = ["ping", "-c", "4", host]
            pattern = re.compile(r"min/avg/max/mdev\s*=\s*[\d.]+\s*/"
                                 r"([\d.]+)\s*/", re.IGNORECASE)
            loss_pat = re.compile(r"(\d+)%\s+packet loss", re.IGNORECASE)

        self.log_info(f"  Pinging {name} ({host})...")
        code, out = self._run(args, timeout=25)
        avg = pattern.search(out)
        loss = loss_pat.search(out)
        avg_txt = f"{avg.group(1)} ms" if avg else "n/a"
        loss_txt = f"{loss.group(1)}%" if loss else "n/a"

        if code == 0:
            self.log_ok(f"  {name} ({host}): avg={avg_txt} | "
                        f"packet loss={loss_txt}")
        else:
            self.log_warn(f"  {name} ({host}): unreachable | "
                          f"packet loss={loss_txt}")
            for line in out.splitlines()[1:6]:
                self.log_warn(f"    {line}")

    def _temp_worker(self):
        self.log_head("========== Temperatures ==========")
        try:
            sensors = psutil.sensors_temperatures()
        except Exception as exc:
            self.log_err(f"  Temperature API error: {exc}")
            return

        if sensors:
            for name, entries in sensors.items():
                for entry in entries:
                    high = entry.high if entry.high else float("nan")
                    crit = entry.critical if entry.critical else float("nan")
                    detail = (f"{entry.current:.1f} C"
                              + (f"  / high {high:.1f} C" if high == high else "")
                              + (f"  / crit {crit:.1f} C" if crit == crit else ""))
                    self.log_info(f"  {name} ({entry.label or 'sensor'}): "
                                  f"{detail}")
        else:
            if IS_WINDOWS:
                self.log_warn("  No thermal sensor data exposed through ")
                self.log_warn("  psutil on Windows (requires a vendor tool ")
                self.log_warn("  such as HWiNFO). Trying WMI thermal zone...")
                code, out = self._run([
                    "wmic", r"/namespace:\\root\wmi",
                    "PATH", "MSAcpi_ThermalZoneTemperature",
                    "get", "CurrentTemperature"], timeout=20)
                if out and "CurrentTemperature" in out:
                    for line in out.splitlines()[1:]:
                        if line.strip().isdigit():
                            millis = int(line.strip())
                            self.log_info(f"  Thermal zone: "
                                          f"{(millis - 2732) / 10:.1f} C")
                else:
                    self.log_warn("  WMI thermal zone = no data (admin "
                                  "required or unsupported).")
            else:
                if shutil.which("sensors"):
                    self.log_info("  psutil found no sensors; querying "
                                  "lm-sensors CLI...")
                    code, out = self._run(["sensors"], timeout=20)
                    if out:
                        self._log_output("lm-sensors", code, out, 80)
                    else:
                        self.log_warn(f"  lm-sensors returned nothing: {out}")
                else:
                    self.log_warn("  No thermal data. Install lm-sensors "
                                  "with your package manager, e.g. on "
                                  "Fedora: sudo dnf install lm_sensors "
                                  "&& sudo sensors-detect")

    def _crash_worker(self):
        self.log_head("========== Crash / Event Log Filter ==========")
        if IS_WINDOWS:
            ps_code = (
                "$e = Get-WinEvent -FilterHashtable "
                "@{LogName='System','Application'; Level=1,2} -MaxEvents 15 "
                "-ErrorAction SilentlyContinue | ForEach-Object { "
                "('[' + $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss') + '] ' "
                "+ $_.LevelDisplayName + ' | ' + $_.ProviderName + ' | ' + "
                "($_.Message.Substring(0, [Math]::Min(160, "
                "$_.Message.Length)))) }; if (-not $e) { "
                "'No recent errors or warnings found.' } else { $e }")
            code, out = self._run(
                ["powershell", "-NoProfile", "-Command", ps_code], timeout=70)
            if out:
                self._log_output("Event log (Error/Warning)", code, out, 40)
            else:
                self.log_warn(f"  Get-WinEvent failed: {out}")
        elif IS_LINUX:
            if shutil.which("journalctl"):
                self.log_info("  Scanning recent errors via journalctl...")
                code, out = self._run(
                    ["journalctl", "-b", "-p", "3", "-n", "25", "--no-pager"],
                    timeout=60)
                if out.strip():
                    self._log_output("journalctl -p err", code, out, 40)
                else:
                    self.log_warn("  journalctl: no errors found or no access.")
            elif shutil.which("dmesg"):
                self.log_info("  Falling back to dmesg error scan...")
                code, out = self._run(["dmesg", "-l", "err"],
                                      timeout=30)
                if ("operation not permitted" in out.lower()
                        and not out.strip().splitlines()[0].startswith("[")):
                    self.log_warn("  dmesg needs root privileges - it is one "
                                  "of the few commands that runs with sudo.")
                    if self.terminal:
                        self.log_info("  Opening dmesg in a sudo terminal...")
                        dmesg_out = self._terminal_run_captured(
                            "dmesg -l err | head -40", timeout=90)
                        if dmesg_out and dmesg_out.strip():
                            self.log_head("  dmesg errors (root):")
                            for line in dmesg_out.strip().splitlines():
                                if line.strip():
                                    self.log_info("  " + line.strip())
                        else:
                            self.log_warn("  No dmesg output captured.")
                elif out.strip():
                    self._log_output("dmesg -l err", code, out, 40)
                else:
                    self.log_warn("  dmesg reported no errors.")
            else:
                self.log_warn("  Neither journalctl nor dmesg is available.")
        else:
            self.log_warn("  Event log scan is Windows/Linux only.")

    #==========================================================================
    # SECTION 2 - NATIVE SYSTEM TOOLS (VISIBLE CONSOLE / GUI WINDOWS)
    #==========================================================================
    def _launch_visible(self, title, cmdline):
        """Launch a native tool in a VISIBLE console / GUI window."""
        self.log_ok(f"  Launching {title}...")
        self._spawn_detached(cmdline, cwd=os.path.expanduser("~"))
        self.log_info(f"  {title} should now be open on screen.")

    def _sfc_worker(self):
        self.log_head("========== SFC / DISM ==========")
        if IS_WINDOWS:
            self.log_info("  Opening a visible Command Prompt to run "
                          "SFC /scannow and DISM RestoreHealth...")
            self._launch_visible(
                "SFC / DISM",
                'start "RigCheck - SFC / DISM" cmd /k '
                '"sfc /scannow && DISM /Online /Cleanup-Image /RestoreHealth"')
        else:
            self.log_warn("  SFC / DISM are Windows-only utilities.")
            if shutil.which("rpm"):
                self.log_info("  Running RPM package integrity check "
                              "(rpm -Va)...")
                code, out = self._run(["rpm", "-Va"], timeout=180)
                if out.strip():
                    self._log_output("rpm -Va", code, out, 40)
                else:
                    self.log_ok("  rpm -Va: no integrity errors found.")
            else:
                self.log_info("  Package integrity on Fedora: dnf verify "
                              "(or check with your distro's package tools).")

    def _devmgr_worker(self):
        self.log_head("========== Device Manager ==========")
        if IS_WINDOWS:
            self._launch_visible("Device Manager", 'start "" devmgmt.msc')
        else:
            self.log_info("  Device Manager is Windows-only; logging "
                          "lspci / lsusb instead.")
            for tool in ("lspci", "lsusb"):
                if shutil.which(tool):
                    code, out = self._run([tool], timeout=30)
                    self._log_output(tool, code, out, 40)
                else:
                    self.log_warn(f"  {tool} not installed.")

    def _eventvwr_worker(self):
        self.log_head("========== Event Viewer ==========")
        if IS_WINDOWS:
            self._launch_visible("Event Viewer", 'start "" eventvwr.msc')
        else:
            self.log_info("  Event Viewer is Windows-only; logging the 20 "
                          "most recent journalctl errors instead.")
            if shutil.which("journalctl"):
                code, out = self._run(
                    ["journalctl", "-b", "-p", "3", "-n", "20", "--no-pager"],
                    timeout=60)
                self._log_output("journalctl", code, out, 30)
            else:
                self.log_warn("  journalctl not installed.")

    def _diskmgmt_worker(self):
        self.log_head("========== Disk Management ==========")
        if IS_WINDOWS:
            self._launch_visible("Disk Management", 'start "" diskmgmt.msc')
        else:
            self.log_info("  Logging block device table (lsblk)...")
            code, out = self._run(
                ["lsblk", "-o", "NAME,SIZE,FSTYPE,MOUNTPOINT,MODEL"],
                timeout=30)
            self._log_output("lsblk", code, out, 60)
            if shutil.which("gparted"):
                self.log_ok("  gparted found - launching it for you...")
                self._launch_visible("GParted", "gparted")
            else:
                self.log_warn("  gparted not installed (install with your package "
                              "manager, e.g. on Fedora: "
                              "sudo dnf install gparted).")

    def _mdsched_worker(self):
        self.log_head("========== Windows Memory Diagnostic ==========")
        if IS_WINDOWS:
            self.log_info("  Launching mdsched.exe (Windows Memory "
                          "Diagnostic)...")
            self._spawn_detached('start "" mdsched.exe',
                                 cwd=os.path.expanduser("~"))
            self.log_warn("  You will need to restart the PC to run the "
                          "memory test.")
        else:
            self.log_warn("  Windows Memory Diagnostic is Windows-only.")
            self.log_info("  On Linux use memtest86+ from your boot menu, "
                          "or install it with your package manager, e.g. on "
                          "Fedora: sudo dnf install memtest86+")

    def _ncpa_worker(self):
        self.log_head("========== Network Connections ==========")
        if IS_WINDOWS:
            self._launch_visible("Network Connections", 'start "" ncpa.cpl')
        else:
            self.log_info("  Logging network configuration instead "
                          "(nmcli / ip)...")
            if shutil.which("nmcli"):
                code, out = self._run(["nmcli", "connection", "show"],
                                      timeout=30)
                self._log_output("nmcli connection show", code, out, 40)
            code, out = self._run(["ip", "-brief", "addr"], timeout=20)
            self._log_output("ip -brief addr", code, out, 40)

    def _control_worker(self):
        self.log_head("========== Control Panel / Settings ==========")
        if IS_WINDOWS:
            self._launch_visible("Control Panel", 'start "" control')
            return

        # Linux: open the desktop's own graphical settings manager (visible).
        candidates = ("gnome-control-center", "systemsettings",
                      "xfce4-settings-manager", "cinnamon-settings",
                      "mate-control-center", "ksystemsettings5")
        app = next((c for c in candidates if shutil.which(c)), None)
        if app:
            self.log_ok(f"  Launching system settings: {app}")
            if self._spawn_detached([app],
                                    cwd=os.path.expanduser("~")) is not None:
                self.log_info("  Settings window opened on screen.")
            else:
                self.log_info(f"  Try running it from a terminal: {app}")
        else:
            self.log_warn("  No known settings manager is installed.")
            self.log_info("  Install one with your package manager, e.g. "
                          "on Fedora: "
                          "sudo dnf install gnome-control-center")

    def _log_hda_pin_configs(self):
        """Read-only display of the ALSA HDA jack pin tables from sysfs.
        This is plain kernel data (no third-party code involved)."""
        try:
            cards = [d for d in os.listdir("/sys/class/sound")
                     if d.startswith("card")]
        except Exception:
            cards = []
        if not cards:
            self.log_info("  No HDA sound cards found in /sys/class/sound.")
            return
        for card in sorted(cards):
            cfg = os.path.join("/sys/class/sound", card,
                               "init_pin_configs")
            if not os.path.exists(cfg):
                continue
            self.log_head(f"  {card} - current jack pin defaults:")
            try:
                with open(cfg, "r", errors="replace") as fh:
                    for line in fh.read().splitlines():
                        if line.strip():
                            self.log_info("    " + line.strip())
            except Exception as exc:
                self.log_info(f"    (unreadable: {exc})")
        self.log_info("  The 'config' column is the ALSA pin-verb value that "
                      "hdajackretask edits when it applies a new mapping.")

    def _sound_settings_worker(self):
        self.log_head("========== Sound Settings ==========")
        if IS_WINDOWS:
            self.log_info("  Opening Windows sound settings...")
            self._launch_visible("Sound Settings",
                                 'start ms-settings:sound')
            self.log_info("  For device / jack / channel layout options use "
                          "the classic panel too: start mmsys.cpl")
        else:
            candidates = (
                (["gnome-control-center", "sound"],
                 "gnome-control-center"),
                (["systemsettings", "kcm_pulseaudio"],
                 "systemsettings"),
                (["xfce4-settings-manager", "sound"],
                 "xfce4-settings-manager"),
                (["mate-volume-control"], "mate-volume-control"),
                (["pavucontrol"], "pavucontrol"),
            )
            found = next((args for args, name in candidates
                          if shutil.which(name)), None)
            if found:
                self.log_ok("  Launching sound settings: "
                            + " ".join(found))
                if self._spawn_detached(
                        found, cwd=os.path.expanduser("~")) is not None:
                    self.log_info("  Sound settings opened on screen.")
                else:
                    self.log_info("  Try running it from a terminal: "
                                  + " ".join(found))
                self.log_info("  Set Speaker Configuration to 5.1/7.1 here "
                              "before running the Surround test.")
            else:
                self.log_warn("  No sound settings app installed.")
                self.log_info("  Install one with your package manager, "
                              "e.g. on Fedora: "
                              "sudo dnf install pavucontrol "
                              "(PulseAudio Volume Control)")

    def _hdajack_worker(self):
        self.log_head("========== HD Audio Jack Retask ==========")
        if IS_WINDOWS:
            self.log_warn("  hdajackretask is a Linux-only ALSA tool.")
            self.log_info("  On Windows, jack remapping is handled by your "
                          "audio driver's control panel (Realtek Audio "
                          "Console / UAD) or via 'Sound devices' -> "
                          "Properties -> Jack Settings.")
            self._launch_visible("Sound devices", 'start "" mmsys.cpl')
            return
        if not shutil.which("hdajackretask"):
            self.log_warn("  hdajackretask is not installed. It ships in "
                          "the 'alsa-tools-gui' package (GPL software) - "
                          "RigCheck does NOT bundle it, it only launches it "
                          "when your system provides it.")
            self.log_info("  Install it with your package manager, e.g. "
                          "on Fedora: sudo dnf install alsa-tools-gui")
            self.log_info("  Until then, here is the current status:")
            self._log_hda_pin_configs()
            return
        path = shutil.which("hdajackretask")
        self.log_info(f"  Found hdajackretask at: {path}")
        self.log_info("  Launching it for the current user (no root "
                      "needed)...")
        spawned = self._spawn_detached(["hdajackretask"],
                                       cwd=os.path.expanduser("~"))
        if spawned is not None:
            self.log_ok("  hdajackretask launched - remap the jack and use "
                        "'Apply now' to save it.")
        else:
            self.log_err("  Could not start hdajackretask.")
            self.log_info("  Try running it from a terminal: "
                          "hdajackretask")
        self.log_info("  Tip: a saved mapping persists until you reset it "
                      "in the tool or reboot with verbose options - use the "
                      "'Reset' button inside hdajackretask if a jack "
                      "misbehaves after remapping.")

    #==========================================================================
    # SECTION 3 - SERVICE UTILITIES
    #==========================================================================
    def _startup_worker(self):
        self.log_head("========== Startup Check ==========")
        if IS_WINDOWS:
            self.log_info("  Reading auto-start registry Run keys...")
            for hive in ("HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                         "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"):
                code, out = self._run(["reg", "query", hive], timeout=20)
                if out:
                    self._log_output(hive.split("\\")[0], code, out, 30)
                else:
                    self.log_info(f"  {hive}: empty or not present")
            if os.environ.get("APPDATA"):
                folder = os.path.join(
                    os.environ["APPDATA"], "Microsoft", "Windows",
                    "Start Menu", "Programs", "Startup")
                self.log_info(f"  Startup folder: {folder}")
                try:
                    items = os.listdir(folder) if os.path.isdir(folder) else []
                    for item in items:
                        self.log_info(f"    {item}")
                    if not items:
                        self.log_info("    (empty)")
                except Exception as exc:
                    self.log_warn(f"    Cannot list startup folder: {exc}")
        else:
            self.log_info("  Enabled systemd services...")
            code, out = self._run(
                ["systemctl", "list-unit-files", "--type=service",
                 "--state=enabled", "--no-pager"], timeout=30)
            if out:
                self._log_output("systemd enabled services", code, out, 40)
            else:
                self.log_warn("  systemctl unavailable or not running.")
            autostart = os.path.expanduser("~/.config/autostart")
            if os.path.isdir(autostart):
                self.log_info(f"  Autostart entries: {autostart}")
                for item in sorted(os.listdir(autostart)):
                    self.log_info(f"    {item}")
            else:
                self.log_info("  No ~/.config/autostart desktop entries.")

    def _tempclean_worker(self):
        self.log_head("========== Clean Temp Files ==========")
        if IS_WINDOWS:
            targets = [os.environ.get("TEMP", ""),
                       os.environ.get("TMP", "")]
            prefetch = os.path.join(os.environ.get(
                "SystemRoot", r"C:\Windows"), "Prefetch")
            targets.append(prefetch)
        else:
            targets = ["/tmp"]
        targets = [t for t in targets if t and os.path.isdir(t)]

        if not targets:
            self.log_warn("  No temporary directories found.")
            return

        candidates = []
        total_size = 0
        for tdir in sorted(set(targets)):
            self.log_info(f"  Scanning: {tdir}")
            entries = []
            dir_size = 0
            try:
                with os.scandir(tdir) as it:
                    for entry in it:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                sz = entry.stat(follow_symlinks=False).st_size
                                entries.append(entry.path)
                                dir_size += sz
                            elif entry.is_dir(follow_symlinks=False):
                                sz = self._dir_size(entry.path)
                                if sz is not None:
                                    entries.append(entry.path)
                                    dir_size += sz
                        except (OSError, ValueError):
                            continue
            except Exception as exc:
                self.log_warn(f"    Scan error: {exc}")
                continue
            self.log_info(f"    {len(entries)} item(s), "
                          f"approx {gb(dir_size)}")
            for path in entries[:15]:
                self.log_info(f"      {path}")
            if len(entries) > 15:
                self.log_warn(f"      ... and {len(entries) - 15} more")
            candidates.extend(entries)
            total_size += dir_size

        self.log_info(f"  Total cleanable: {len(candidates)} item(s), "
                      f"approx {gb(total_size)}.")
        self.log_warn("  Only temporary files are removed; items in use are "
                      "skipped safely.")
        self.ask_user(
            "Confirm Temporary File Cleanup",
            f"Purge {len(candidates)} temporary item(s) "
            f"(approx {gb(total_size)})?\n\n"
            "Files in use will be skipped. Continue?",
            candidates)

    def _dir_size(self, path, cap=20000):
        """Walk a directory, bounded, returning total bytes (or None)."""
        total = 0
        count = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for name in filenames:
                    try:
                        fp = os.path.join(dirpath, name)
                        total += os.path.getsize(fp)
                    except OSError:
                        continue
                    count += 1
                    if count > cap:
                        return total
        except OSError:
            return None
        return total

    def _purge_files(self, paths):
        self.status("Cleaning temp files...")
        removed = 0
        freed = 0
        skipped = 0
        for path in paths:
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    for dirpath, dirnames, filenames in os.walk(path):
                        for name in filenames:
                            try:
                                size = os.path.getsize(os.path.join(dirpath, name))
                                os.remove(os.path.join(dirpath, name))
                                removed += 1
                                freed += size
                            except OSError:
                                skipped += 1
                        try:
                            os.rmdir(dirpath)
                        except OSError:
                            pass
                else:
                    try:
                        size = os.path.getsize(path)
                        os.remove(path)
                        removed += 1
                        freed += size
                    except OSError:
                        skipped += 1
            except Exception:
                skipped += 1
        self.log_ok(f"  Cleanup finished: {removed} file(s) removed "
                    f"({gb(freed)} freed), {skipped} skipped (in use / "
                    f"protected).")
        self.status("Ready")

    def _flushdns_worker(self):
        self.log_head("========== Flush DNS Cache ==========")
        if IS_WINDOWS:
            code, out = self._run(["ipconfig", "/flushdns"], timeout=30,
                                  shell=False)
            self._log_output("ipconfig /flushdns", code, out, 20)
            if code == 0:
                self.log_ok("  DNS resolver cache flushed.")
        else:
            # These run WITHOUT sudo - flushing the user DNS cache normally
            # needs no root. A root-only flush (nscd -i hosts) is left to the
            # user; it is deliberately never run by RigCheck.
            commands = [
                ["resolvectl", "flush-caches"],
                ["systemd-resolve", "--flush-caches"],
            ]
            for cmd in commands:
                if shutil.which(cmd[0]):
                    code, out = self._run(cmd, timeout=25)
                    self._log_output(" ".join(cmd), code, out, 15)
                    if code == 0:
                        self.log_ok("  DNS cache flushed successfully.")
                        return
                    self.log_warn(f"  {cmd[0]} did not succeed; trying next...")
            self.log_warn("  No DNS flush tool available "
                          "(try: systemd-resolved / nscd / NetworkManager).")

    def _battery_worker(self):
        self.log_head("========== Battery Report ==========")
        if IS_WINDOWS:
            tempdir = os.environ.get("TEMP", ".")
            out_file = os.path.join(
                tempdir, f"RigCheck_battery_report_{int(time.time())}.html")
            code, out = self._run(
                ["powercfg", "/batteryreport", "/output", out_file],
                timeout=60)
            if code == 0 and os.path.exists(out_file):
                self.log_ok(f"  Battery report generated: {out_file}")
                self.log_info("  Opening the report in your browser...")
                try:
                    os.startfile(out_file)
                except Exception as exc:
                    self.log_warn(f"  Could not auto-open report: {exc}")
            else:
                self.log_warn(f"  powercfg failed: {out}")
                self.log_warn("  Battery report only works on laptops.")
        else:
            found = False
            base = "/sys/class/power_supply"
            if os.path.isdir(base):
                for name in sorted(os.listdir(base)):
                    if not name.startswith(("BAT", "PSY")):
                        continue
                    uevent = os.path.join(base, name, "uevent")
                    if os.path.isfile(uevent):
                        found = True
                        self.log_info(f"  [{name}]")
                        try:
                            with open(uevent, "r", errors="replace") as fh:
                                for line in fh:
                                    if line.strip():
                                        self.log_info("    " + line.strip())
                        except Exception as exc:
                            self.log_warn(f"    read error: {exc}")
            if not found:
                self.log_warn("  No battery detected (desktop PC or "
                              "unsupported sysfs layout).")

    def _ports_worker(self):
        self.log_head("========== Open Ports / Netstat ==========")
        if IS_WINDOWS:
            args = ["netstat", "-ano"]
        else:
            args = ["netstat", "-tulpn"]
            if not shutil.which("netstat"):
                args = ["ss", "-tulpn"]
        code, out = self._run(args, timeout=30)
        lines = out.splitlines() if out else []
        if not lines:
            self.log_warn("  netstat produced no output "
                          f"({'ss' if args[0] == 'ss' else 'netstat'}).")
            return
        self.log_info(f"  Raw connection count: {len(lines)}")
        self._log_output("netstat", code, out, 80)
        listening = [ln for ln in lines
                     if "LISTEN" in ln or "LISTENING" in ln]
        if listening:
            self.log_ok(f"  Listening sockets: {len(listening)}")
            for ln in listening[:15]:
                self.log_info("    " + ln)
        else:
            self.log_info("  No listening sockets found in output.")

    #--------------------------------------------------------------------------
    # Cross-platform helpers for the expanded modules
    #--------------------------------------------------------------------------
    def _run_ps(self, script, timeout=70):
        """Run a PowerShell snippet on Windows (graceful on Linux)."""
        if not IS_WINDOWS:
            return (-1, "")
        return self._run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-Command", script], timeout=timeout)

    def _open_file(self, path):
        """Open a file/location with the OS default application."""
        try:
            if IS_WINDOWS:
                os.startfile(path)
            else:
                code, _ = self._run(["xdg-open", path], timeout=10)
                if code != 0:
                    self._run(["gio", "open", path], timeout=10)
        except Exception as exc:
            self.log_warn(f"  Could not auto-open {path}: {exc}")

    def _local_store(self, name):
        """Per-user data directory used by RigCheck (created on demand)."""
        base = os.path.join(os.path.expanduser("~"), ".rigcheck")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            pass
        return os.path.join(base, name)

    def _load_settings(self):
        """Load persisted settings from ~/.rigcheck/settings.json."""
        self._settings = dict(DEFAULT_SETTINGS)
        self._dark = self._settings.get("theme", "dark") != "light"
        try:
            with open(self._local_store("settings.json"),
                      "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    self._settings.update(data)
        except Exception:
            pass
        self._dark = self._settings.get("theme", "dark") != "light"

    def _save_settings(self):
        """Persist current settings to ~/.rigcheck/settings.json."""
        try:
            with open(self._local_store("settings.json"),
                      "w", encoding="utf-8") as fh:
                json.dump(self._settings, fh, indent=2)
        except Exception as exc:
            self.log_warn(f"  Could not save settings: {exc}")

    def _apply_theme(self):
        """Apply the current theme (dark/light) to styles + the console log.
        Uses a complete ttk "clam" recipe: the notebook tabs need explicit
        bordercolor/lightcolor/darkcolor and state maps, the global palette
        covers Tk-level widgets, and the header labels are colored directly
        so they follow the theme even on default Tk themes."""
        theme = THEMES["dark" if self._dark else "light"]
        bg, fg, frame, select = (theme["bg"], theme["fg"],
                                 theme["frame"], theme["select"])
        # ---- global Tk palette (root, plain widgets, dialogs defaults)
        try:
            self.root.configure(bg=bg)
            self.root.tk_setPalette(
                background=bg, foreground=fg,
                activeBackground=select, activeForeground=fg,
                selectBackground=select, selectForeground=fg,
                highlightBackground=bg, highlightColor=select,
                disabledForeground=theme["ts"],
                insertBackground=fg, troughColor=frame)
        except Exception:
            pass
        # ---- ttk style colours
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=bg, foreground=fg)
        for widget in ("TFrame", "TButton", "TLabel", "TLabelframe",
                       "TLabelframe.Label", "TEntry", "TCombobox",
                       "Header.TLabel", "Sub.TLabel", "InfoKey.TLabel",
                       "InfoVal.TLabel", "Status.TLabel"):
            try:
                style.configure(widget, background=bg, foreground=fg)
            except tk.TclError:
                pass
        style.configure("Tool.TButton", padding=(8, 4),
                        background=frame, foreground=fg)
        style.map("Tool.TButton",
                  background=[("active", select), ("pressed", select)],
                  foreground=[("disabled", theme["ts"])])
        # ---- notebook: tabs must set the 3D colours + state maps as well
        style.configure("TNotebook", background=bg, borderwidth=0,
                        bordercolor=frame)
        style.configure("TNotebook.Tab", background=frame, foreground=fg,
                        bordercolor=frame, lightcolor=frame, darkcolor=frame,
                        padding=(10, 5))
        style.map("TNotebook.Tab",
                  background=[("selected", bg), ("active", select)],
                  foreground=[("selected", fg), ("active", fg)],
                  lightcolor=[("selected", bg), ("active", select)],
                  darkcolor=[("selected", bg), ("active", select)])
        # ---- header (Tk labels, colored directly for guaranteed theming)
        for attr in ("_header_brand", "_header_sub"):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.config(bg=bg, fg=fg)
                except Exception:
                    pass
        _header = getattr(self, "_header", None)
        if _header is not None:
            try:
                _header.config(bg=bg)
            except Exception:
                pass
        # ---- console log widget
        log = getattr(self, "_log", None)
        if log is not None:
            try:
                log.config(bg=theme["text_bg"], fg=fg,
                           insertbackground=fg)
                for tag, key in (("ts", "ts"), ("head", "head"),
                                 ("info", "info"), ("ok", "ok"),
                                 ("warn", "warn"), ("err", "err")):
                    opts = {"foreground": theme[key]}
                    if tag == "head":
                        opts["font"] = (self._mono, 9, "bold")
                    log.tag_configure(tag, **opts)
            except Exception:
                pass

    def _settings_worker(self):
        """Small settings dialog - theme choice, applied live + saved."""
        top = tk.Toplevel(self.root)
        top.title(f"{APP_NAME} Settings")
        top.transient(self.root)
        top.grab_set()
        try:
            top.resizable(False, False)
            top.configure(bg=THEMES["dark" if self._dark else "light"]["bg"])
        except Exception:
            pass
        body = ttk.Frame(top, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Settings are saved automatically",
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
        dark_var = tk.BooleanVar(value=self._dark)

        def toggle_dark():
            self._dark = bool(dark_var.get())
            self._apply_theme()

        ttk.Checkbutton(body, text="Dark mode",
                        variable=dark_var, command=toggle_dark).pack(anchor="w")
        ttk.Label(body, text="Settings file:", style="Sub.TLabel").pack(
            anchor="w", pady=(12, 0))
        ttk.Label(body, text=os.path.join("~", ".rigcheck",
                                          "settings.json"),
                  style="Sub.TLabel").pack(anchor="w")
        btns = ttk.Frame(body)
        btns.pack(fill=tk.X, pady=(12, 0))

        def on_close():
            self._settings["theme"] = "dark" if dark_var.get() else "light"
            self._save_settings()
            top.destroy()

        def on_reset():
            self._settings = dict(DEFAULT_SETTINGS)
            dark_var.set(True)
            self._dark = True
            self._apply_theme()

        ttk.Button(btns, text="Reset to defaults", style="Tool.TButton",
                   command=on_reset).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close", style="Tool.TButton",
                   command=on_close).pack(side=tk.RIGHT)

    def _spec_data(self):
        """Return a list of (key, value) lines describing this machine."""
        mem = psutil.virtual_memory()
        os_label = self._get_os_label()
        arch = platform.machine() or platform.architecture()[0]
        phys = psutil.cpu_count(logical=False)
        logc = psutil.cpu_count(logical=True)
        try:
            freq = psutil.cpu_freq()
            freq_txt = (f"{int(freq.current)} MHz"
                        if freq and freq.current else "n/a")
        except Exception:
            freq_txt = "n/a"
        return [
            ("Operating System",
             f"{os_label} ({platform.system()} {arch})"),
            ("Hostname", socket.gethostname() or platform.node()),
            ("CPU", self._cpu_name),
            ("Cores", f"{phys or '?'} physical / "
                      f"{logc or '?'} logical | {freq_txt}"),
            ("Memory", f"Total {gb(mem.total)} | Used {mem.percent:.1f}% | "
                       f"Free {gb(mem.available)}"),
            ("Storage", self._storage_summary()),
            ("Network", self._net_label()),
            ("Uptime", format_uptime()),
            ("Python", platform.python_version()),
            ("RigCheck", BRANDING),
        ]

    def _log_spec(self):
        self.log_head("----- Machine Specifications -----")
        for key, val in self._spec_data():
            self.log_info(f"  {key:<22}: {val}")

    def _ping_diag_quick(self, host):
        """Quick single-hop reachability probe. Returns bool."""
        if IS_WINDOWS:
            args = ["ping", "-n", "2", host]
        else:
            args = ["ping", "-c", "2", "-W", "3", host]
        code, raw = self._run(args, timeout=15)
        if code == 0:
            return True
        return bool(re.search(r"0% loss", raw, re.IGNORECASE))

    #==========================================================================
    # MODULE 1 - ONE-CLICK DIAGNOSTICS & REPORTING
    #==========================================================================
    def _quick_health(self):
        self.log_head("========== Quick Health Check (up to 60s) ==========")
        started = time.time()
        problems = []
        score = 100

        # 1) SMART / disk health (best-effort, no sudo required here)
        if IS_WINDOWS:
            code, out = self._run_ps(
                "(Get-PhysicalDisk -ErrorAction SilentlyContinue | "
                "Select-Object DeviceId,HealthStatus,OperationalStatus | "
                "Format-Table -HideTableHeaders | Out-String).Trim()")
            if out.strip():
                self.log_info("  SMART (Get-PhysicalDisk):")
                for line in out.splitlines():
                    if line.strip():
                        self.log_info("    " + line.strip())
                if re.search(r"Unhealthy|Failing|Degraded", out,
                             re.IGNORECASE):
                    problems.append("Disk health degraded (SMART).")
                    score -= 25
                else:
                    self.log_ok("  SMART: disks report healthy.")
            else:
                self.log_warn("  SMART: no data exposed (permissions).")
        else:
            if shutil.which("smartctl") and self.terminal:
                code, out = self._run(["smartctl", "-H"], timeout=30)
                if out and "PASSED" in out:
                    self.log_ok("  SMART: health PASSED (root-free device).")
                else:
                    self.log_info("  SMART: full check needs root - skipped "
                                  "here (use the S.M.A.R.T. button).")
            else:
                self.log_info("  SMART: smartmontools not installed (or no "
                              "terminal) - skipped for the quick scan.")

        # 2) temperatures
        try:
            sensors = psutil.sensors_temperatures()
            hot = 0
            n = 0
            for name, entries in sensors.items():
                for entry in entries:
                    n += 1
                    if entry.current and entry.current > 75:
                        hot += 1
                        self.log_warn(
                            f"  Temperature {name}/{entry.label or 'sensor'}: "
                            f"{entry.current:.0f}C (hot)")
            if hot:
                problems.append(f"{hot} temperature sensor(s) above 75C.")
                score -= 15
            elif n:
                self.log_ok(f"  Temperatures: {n} sensor(s) within limits.")
            else:
                self.log_warn("  Temperatures: no sensor data available.")
        except Exception as exc:
            self.log_warn(f"  Temperature scan error: {exc}")

        # 3) background CPU load sampler while the remaining checks run
        samples = []
        stop_load = threading.Event()

        def sample():
            while not stop_load.is_set():
                try:
                    samples.append(psutil.cpu_percent(interval=0.5))
                except Exception:
                    time.sleep(0.5)
        threading.Thread(target=sample, daemon=True).start()

        # 4) critical session errors
        err_count = 0
        if IS_WINDOWS:
            code, out = self._run_ps(
                "(Get-WinEvent -FilterHashtable @{LogName='System'; "
                "Level=1,2} -MaxEvents 30 -ErrorAction "
                "SilentlyContinue).Count")
            if out.strip().isdigit():
                err_count = int(out.strip())
        elif shutil.which("journalctl"):
            code, out = self._run(
                ["journalctl", "-b", "-p", "3", "--no-pager"], timeout=60)
            err_count = len([ln for ln in out.splitlines()
                             if re.match(r"^[A-Z]\w{2} \s*\d{1,2} ", ln)])
        if err_count:
            self.log_warn(f"  {err_count} critical log entr(ies) this "
                          "session.")
            problems.append(f"{err_count} recent critical log entr(ies).")
            score -= 10
        else:
            self.log_ok("  No critical errors in the current session logs.")

        # 5) connectivity
        if self._ping_diag_quick("8.8.8.8"):
            self.log_ok("  Internet connectivity: OK.")
        else:
            self.log_warn("  Ping to 8.8.8.8 failed - network may be "
                          "offline.")
            problems.append("No internet connectivity (ping failed).")
            score -= 15

        # 6) let the scan run for a full 60s so the CPU load is a real sample
        while time.time() - started < 60:
            time.sleep(1)
        stop_load.set()
        if samples:
            avg_load = sum(samples) / len(samples)
            self.log_info(f"  Sustained CPU load during scan: "
                          f"{avg_load:.0f}%")
            if avg_load > 85:
                problems.append(f"Sustained CPU load of {avg_load:.0f}%.")
                score -= 15
        ram = psutil.virtual_memory()
        if ram.percent > 90:
            problems.append(f"RAM usage at {ram.percent:.0f}%.")
            score -= 10
        self.log_info(f"  RAM usage now: {ram.percent:.0f}% | "
                      f"Free {gb(ram.available)}")

        score = max(score, 0)
        self.log_head(f"----- Overall System Health Score: {score}% -----")
        if problems:
            self.log_warn("  Warning summary:")
            for p in problems:
                self.log_warn(f"    - {p}")
            self.log_info("  Verdict: review the warnings and run the "
                          "targeted tests if worried.")
        else:
            self.log_ok("  Verdict: system is in good shape.")
        self.log_ok(f"  Quick Health Check finished in "
                    f"{time.time() - started:.0f}s.")

    def _html_report(self):
        self.log_head("========== Export HTML Diagnostic Report ==========")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".html",
            initialfile="RigCheck_report_"
                        f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        ".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        if not path:
            self.log_info("  HTML export cancelled.")
            return
        try:
            rows_html = "".join(
                f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
                for k, v in self._spec_data())
            log_text = self._log.get("1.0", "end-1c").strip() or \
                "(console log empty)"
            log_escaped = "".join(
                f"<p>{html.escape(line)}</p>" for line in
                log_text.splitlines())
            doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>RigCheck Diagnostic Report</title>
<style>
  body {{ font-family: "Segoe UI", Arial, sans-serif; margin: 2em; color: #222; }}
  h1 {{ color: #0b5394; }} h2 {{ color: #555; border-bottom: 1px solid #ccc; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background: #e8f0f8; }} .meta {{ color: #777; }}
  #log {{ background: #101418; color: #c8d4dc; padding: .8em;
          font-family: Consolas, monospace; max-height: 320px; overflow: auto; }}
</style></head><body>
<h1>RigCheck PC Diagnostic Report</h1>
<p class="meta">{html.escape(BRANDING)} &middot; generated {html.escape(stamp)}</p>
<h2>System Specifications</h2><table>{rows_html}</table>
<h2>Diagnostic Console Log</h2><div id="log">{log_escaped}</div>
<p class="meta">{html.escape(DISCLAIMER_TEXT)}</p>
</body></html>"""
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(doc)
            self.log_ok(f"  HTML report saved: {path}")
            self.log_info("  Open it in any browser to view or print.")
        except Exception as exc:
            self.log_err(f"  HTML export failed: {exc}")

    def _service_tag(self):
        self.log_head("========== Service Tag + QR Code Generator ==========")
        try:
            import qrcode  # noqa: F401
            QR_OK = True
        except Exception:
            QR_OK = False
        try:
            from PIL import Image  # noqa: F401
            from PIL import ImageDraw  # noqa: F401
            PIL_OK = True
        except Exception:
            PIL_OK = False

        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary = "\n".join(f"{k}: {v}" for k, v in self._spec_data())
        qr_text = f"RigCheck service tag {stamp}\n" + summary
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            initialfile="RigCheck_service_tag_"
                        f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        ".png",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
        if not path:
            self.log_info("  Service tag generation cancelled.")
            return
        try:
            if not QR_OK or not PIL_OK:
                self.log_warn("  qrcode and/or pillow not installed - "
                              "writing a plain-text service tag instead.")
                self.log_info("  Install with: pip install qrcode pillow")
                txt_path = os.path.splitext(path)[0] + ".txt"
                with open(txt_path, "w", encoding="utf-8") as fh:
                    fh.write(summary + "\n\nTest date: " + stamp + "\n")
                self.log_ok(f"  Text service tag saved: {txt_path}")
                return

            import qrcode
            from PIL import Image, ImageDraw
            qr_img = qrcode.make(qr_text)
            card_w = max(560, qr_img.width + 260)
            card_h = max(qr_img.height + 190, len(self._spec_data()) * 24 + 170)
            card = Image.new("RGB", (card_w, card_h), "white")
            draw = ImageDraw.Draw(card)
            draw.rectangle([0, 0, card_w - 1, card_h - 1],
                           outline="#0b5394", width=4)
            y = 14
            draw.text((20, y), "RigCheck - Service Sticker", fill="#0b5394")
            y += 24
            draw.text((20, y), stamp, fill="#666666")
            y += 22
            for k, v in self._spec_data()[:9]:
                draw.text((20, y), k + ":", fill="#999999")
                draw.text((165, y), v[:52], fill="#222222")
                y += 20
            card.paste(qr_img, (card_w - qr_img.width - 20, 14))
            card.save(path)
            self.log_ok(f"  Service sticker saved: {path}")
            self.log_info("  Scan the QR code with a phone to view this "
                          "machine's summary.")
            self._open_file(path)
        except Exception as exc:
            self.log_err(f"  Service tag generation failed: {exc}")

    def _scan_hardware_signature(self):
        """Collect a compact snapshot of the installed hardware."""
        sig = {
            "cpu": self._cpu_name,
            "cpu_logical": psutil.cpu_count(logical=True),
            "ram_total": psutil.virtual_memory().total,
            "os": self._get_os_label(),
        }
        serials = []
        if IS_WINDOWS:
            code, out = self._run_ps(
                "(Get-PhysicalDisk -ErrorAction SilentlyContinue | "
                "ForEach-Object { $_.FriendlyName })")
            serials = [l.strip() for l in out.splitlines()
                       if l.strip() and "---" not in l][:6]
        else:
            code, out = self._run(
                ["lsblk", "-d", "-o", "NAME,SERIAL", "-n"], timeout=20)
            serials = [l.strip() for l in out.splitlines() if l.strip()][:6]
        sig["disks"] = serials
        gpus = []
        if IS_WINDOWS:
            code, out = self._run_ps(
                "(Get-CimInstance Win32_VideoController | "
                "ForEach-Object { $_.Name })")
            gpus = [l.strip() for l in out.splitlines() if l.strip()][:2]
        else:
            code, out = self._run(["lspci"], timeout=20)
            gpus = [l for l in out.splitlines()
                    if re.search(r"VGA|3D controller|Display controller",
                                 l)][:2]
        sig["gpus"] = gpus
        return sig

    def _hw_change_worker(self):
        self.log_head("========== Hardware Change Logger ==========")
        store = self._local_store("hardware.json")
        current = self._scan_hardware_signature()
        previous = None
        try:
            with open(store, "r", encoding="utf-8") as fh:
                previous = json.load(fh)
        except Exception:
            previous = None
        if previous is None:
            self.log_info("  First launch - storing a baseline hardware "
                          "snapshot.")
        else:
            self.log_info("  Comparing against the previous snapshot...")
            changed = False
            for key in ("cpu", "cpu_logical", "ram_total", "os"):
                if previous.get(key) != current.get(key):
                    changed = True
                    self.log_warn(
                        f"  CHANGED {key}: {previous.get(key)} -> "
                        f"{current.get(key)}")
            prev_d = set(previous.get("disks") or [])
            cur_d = set(current.get("disks") or [])
            prev_g = set(previous.get("gpus") or [])
            cur_g = set(current.get("gpus") or [])
            for d in prev_d - cur_d:
                changed = True
                self.log_warn(f"  DISK REMOVED: {d}")
            for d in cur_d - prev_d:
                changed = True
                self.log_ok(f"  DISK ADDED: {d}")
            for g in prev_g - cur_g:
                changed = True
                self.log_warn(f"  GPU REMOVED: {g}")
            for g in cur_g - prev_g:
                changed = True
                self.log_ok(f"  GPU ADDED: {g}")
            if changed:
                self.log_warn("  Hardware changes detected since the last "
                              "review.")
            else:
                self.log_ok("  No hardware changes detected.")
        self._log_spec()
        try:
            with open(store, "w", encoding="utf-8") as fh:
                json.dump(current, fh, indent=2, default=str)
            self.log_ok(f"  Snapshot updated: {store}")
        except Exception as exc:
            self.log_warn(f"  Could not save snapshot: {exc}")

    #==========================================================================
    # MODULE 2 - DEEP HARDWARE & SENSOR DIAGNOSTICS
    #==========================================================================
    def _ram_xmp_worker(self):
        self.log_head("========== RAM XMP / EXPO Clock Inspector ==========")
        if IS_WINDOWS:
            code, out = self._run_ps(
                "(Get-CimInstance Win32_PhysicalMemory | "
                "Select-Object BankLabel, Capacity, Speed, "
                "ConfiguredClockSpeed, DeviceLocator | Format-List | "
                "Out-String -Width 160)")
            if out.strip():
                self._log_output("Win32_PhysicalMemory", code, out, 30)
                self.log_info("  Compare 'Speed' (installed) vs "
                              "'ConfiguredClockSpeed' - if configured is "
                              "lower, XMP/EXPO is off and RAM runs at base "
                              "speed.")
            else:
                self.log_warn("  No memory module data exposed "
                              "(permissions).")
        else:
            if not shutil.which("dmidecode"):
                self.log_warn("  dmidecode not installed (install it from "
                              "your package manager).")
                return
            code, out = self._run(["dmidecode", "-t", "memory"], timeout=30)
            if "permission" in out.lower() or (code == 1
                                               and "denied" in out.lower()):
                self.log_info("  dmidecode needs root - re-running it via "
                              "the sudo terminal (same as smartctl).")
                code, out = self._run_root_batch(
                    ["dmidecode -t memory"], timeout=150)
                if code != 0 or not out:
                    return
            if not out.strip():
                self.log_warn("  No memory data returned by dmidecode.")
                return
            for line in out.splitlines():
                if re.search(r"\b(Speed:|Configured Memory Speed:|"
                             r"Voltage Configured:|Manufacturer:|"
                             r"Part Number:|Rank:|Size:)",
                             line):
                    self.log_info("  " + line.strip())
            if "Configured Memory Speed" not in out:
                self.log_info("  No 'Configured Memory Speed' field - "
                              "XMP profile info may be absent here.")

    def _dpc_worker(self):
        self.log_head("========== DPC Latency / Micro-Stutter Detector ======")
        self.log_info("  Measuring scheduling jitter for 10 seconds...")
        self.log_info("  (Soft estimate - true DPC latency needs a "
                      "kernel-level tool such as LatencyMon.)")
        best = float("inf")
        worst = 0.0
        total = 0.0
        count = 0
        prev = time.perf_counter()
        end = time.time() + 10
        while time.time() < end:
            now = time.perf_counter()
            delta = now - prev
            prev = now
            if delta > 0:
                us = delta * 1_000_000
                total += us
                count += 1
                if us < best:
                    best = us
                if us > worst:
                    worst = us
        avg = total / count if count else 0
        self.log_info(f"  Samples   : {count}")
        self.log_info(f"  Avg jitter: {avg:.1f} us")
        self.log_info(f"  Best      : {best:.1f} us")
        self.log_info(f"  Worst     : {worst:,.0f} us")
        if worst < 15000:
            self.log_ok("  No obvious micro-stutter risk (worst sample "
                        "under 15 ms).")
        elif worst < 60000:
            self.log_warn("  Moderate jitter - investigate drivers and "
                          "background load.")
        else:
            self.log_warn("  High latency spikes - update chipset/GPU "
                          "drivers and stop optional telemetry processes.")

    def _gpu_worker(self):
        self.log_head("========== GPU VRAM + PCIe Link Inspector ==========")
        found = False
        if IS_WINDOWS:
            code, out = self._run_ps(
                "(Get-CimInstance Win32_VideoController | "
                "Select-Object Name, AdapterRAM, DriverVersion | "
                "Format-List | Out-String -Width 160)")
            if out.strip():
                self.log_head("  Graphics adapter (WMI):")
                for line in out.splitlines():
                    if line.strip():
                        self.log_info("  " + line.rstrip())
            if shutil.which("nvidia-smi"):
                found = True
                self.log_head("  NVIDIA live sensors:")
                code, out = self._run(
                    ["nvidia-smi", "--query-gpu=name,memory.used,"
                     "memory.total,temperature.gpu,utilization.gpu",
                     "--format=csv,noheader"], timeout=25)
                self._log_output("nvidia-smi", code, out, 10)
        else:
            try:
                base = "/sys/class/drm"
                if os.path.isdir(base):
                    for card in sorted(os.listdir(base)):
                        if not card.startswith("card"):
                            continue
                        dev = os.path.join(base, card, "device")
                        vu = os.path.join(dev, "mem_info_vram_used")
                        vt = os.path.join(dev, "mem_info_vram_total")
                        if os.path.exists(vu):
                            found = True
                            self.log_head(f"  {card} (AMD GPU):")
                            with open(vu) as fh:
                                used = int(fh.read().strip())
                            with open(vt) as fh:
                                total = int(fh.read().strip())
                            self.log_info(
                                f"    VRAM used : {gb(used)} / {gb(total)} "
                                f"({used / total * 100:.1f}%)")
                            if os.path.isdir(dev):
                                for sub in os.listdir(dev):
                                    if sub.startswith("hwmon"):
                                        t = os.path.join(dev, sub,
                                                         "temp1_input")
                                        if os.path.exists(t):
                                            with open(t) as fh:
                                                tc = int(fh.read().strip())
                                            self.log_info(
                                                f"    GPU temp : "
                                                f"{tc / 1000:.1f} C")
            except Exception as exc:
                self.log_warn(f"  AMD sysfs probe failed: {exc}")
            if shutil.which("nvidia-smi"):
                found = True
                self.log_head("  NVIDIA live sensors:")
                code, out = self._run(
                    ["nvidia-smi", "--query-gpu=name,memory.used,"
                     "memory.total,temperature.gpu,utilization.gpu",
                     "--format=csv,noheader"], timeout=25)
                self._log_output("nvidia-smi", code, out, 10)
            if not found:
                self.log_warn("  No GPU sensor data from sysfs or "
                              "nvidia-smi.")
                code, out = self._run(["lspci"], timeout=20)
                gpus = [l for l in out.splitlines()
                        if re.search(r"VGA|3D controller|Display controller",
                                     l)]
                if gpus:
                    self.log_info("  GPUs on the PCIe bus:")
                    for g in gpus:
                        self.log_info("    " + g)

        self.log_head("  PCIe link state:")
        if IS_WINDOWS:
            self.log_info("    Windows hides the live PCIe link speed from "
                          "user mode - see GPU-Z / HWiNFO for LnkSta.")
        else:
            if not shutil.which("lspci"):
                self.log_warn("    lspci not installed.")
                return
            code, out = self._run(["lspci"], timeout=20)
            gpu_slot = next((ln.split()[0] for ln in out.splitlines()
                             if re.search(r"VGA|3D controller|"
                                          r"Display controller", ln)), None)
            if not gpu_slot:
                self.log_warn("    No GPU found on the PCIe bus.")
                return
            code, out = self._run(["lspci", "-vvvv", "-s", gpu_slot],
                                  timeout=30)
            for line in out.splitlines():
                if re.search(r"LnkCap:|LnkSta:|Resizable BAR", line):
                    self.log_info("    " + line.strip())
            if "Resizable BAR" not in out:
                self.log_info("    (No 'Resizable BAR' capability line - "
                              "see the ReBAR / SAM button for details.)")

    def _ssd_tbw_worker(self):
        self.log_head("========== SSD TBW + Health % ==========")
        if IS_WINDOWS:
            code, out = self._run_ps(
                "(Get-PhysicalDisk | Get-StorageReliabilityCounter | "
                "Select-Object DeviceId, Wear, Temperature, "
                "ReadErrorsTotal, WriteErrorsTotal | Format-List | "
                "Out-String -Width 160)")
            if out.strip():
                self.log_head("  Storage reliability counters:")
                self._log_output("reliability", code, out, 40)
                self.log_info("  'Wear' is the remaining life in % - a "
                              "low value means the SSD is aging.")
            else:
                self.log_warn("  Reliability counters need Administrator "
                              "rights or are unsupported here.")
        else:
            if not shutil.which("smartctl"):
                self.log_warn("  smartmontools not installed (install with "
                              "your package manager, e.g. "
                              "sudo dnf install smartmontools).")
                return
            code, out = self._run(["lsblk", "-d", "-o", "NAME", "-n"],
                                  timeout=20)
            disks = [l.strip() for l in out.splitlines()
                     if l.strip() and not l.strip().startswith("loop")][:8]
            if not disks:
                disks = ["nvme0n1", "sda"]

            per_disk = {}
            need_root = False
            for disk in disks:
                code, out = self._run(["smartctl", "-a", f"/dev/{disk}"],
                                      timeout=40)
                if not out or "permission denied" in out.lower():
                    need_root = True
                    break
                per_disk[disk] = out

            if need_root:
                self.log_info("  smartctl needs root to read the wear "
                              "counters - opening a sudo terminal for all "
                              "listed drives (same as the S.M.A.R.T. "
                              "button).")
                steps = []
                for disk in disks:
                    steps.append(f"echo ============ /dev/{disk} ============")
                    steps.append(f"smartctl -a /dev/{disk}")
                code, out = self._run_root_batch(steps, timeout=180)
                if code != 0 or not out:
                    return
                current = None
                for line in out.splitlines():
                    m = re.search(r"^\s*=+ /dev/(\S+) =+\s*$", line)
                    if m:
                        current = m.group(1)
                        per_disk[current] = ""
                    elif current is not None and current in per_disk:
                        per_disk[current] += line + "\n"

            for disk in disks:
                self.log_head(f"--- /dev/{disk} ---")
                out = per_disk.get(disk)
                if not out:
                    self.log_warn("    No smartctl data returned for this "
                                  "drive.")
                    continue
                interesting = False
                for line in out.splitlines():
                    if re.search(r"(Total_LBAs_Written|Media_Wearout_"
                                 r"Indicator|Percent_Lifetime_Remain|"
                                 r"NAND_GB_Written|GB_Written|"
                                 r"Data_Units_Written|Percentage_Used|"
                                 r"Wear_Leveling_Count|Model|"
                                 r"Power_On_Hours)", line):
                        interesting = True
                        self.log_info("    " + line.strip())
                if not interesting:
                    self.log_info("    No TBW/wear attributes exposed for "
                                  "this device.")

    def _lm_sensors_text(self):
        """Return lm-sensors CLI lines (empty on Windows / absent)."""
        if not (IS_LINUX and shutil.which("sensors")):
            return []
        code, out = self._run(["sensors"], timeout=20)
        return out.splitlines() if out else []

    def _psu_worker(self):
        self.log_head("========== PSU Voltage Monitor ==========")
        lines = self._lm_sensors_text()
        if not lines:
            if IS_LINUX:
                self.log_warn("  lm-sensors is not installed or no "
                              "voltage sensors are configured. Install it "
                              "with your package manager, e.g. "
                              "sudo dnf install lm_sensors.")
            else:
                self.log_warn("  Windows exposes no motherboard rail "
                              "voltages to user-mode tools - use "
                              "HWiNFO/OpenHardwareMonitor (free) or your "
                              "BIOS for +12V/+5V/+3.3V.")
            return
        found = 0
        for line in lines:
            if re.search(r"[+~]?\d+(\.\d+)?V", line) and \
                    re.search(r"in\d|12V|5V|3\.3V", line, re.IGNORECASE):
                found += 1
                self.log_info("  " + line.strip())
        if not found:
            self.log_warn("  lm-sensors reported no voltage rails.")
        else:
            self.log_info("  Check rails against their nominal values "
                          "(12.0V / 5.0V / 3.3V); a deviation over ~5% "
                          "indicates a power delivery problem.")

    def _fan_worker(self):
        self.log_head("========== Fan Speed (RPM) Monitor ==========")
        if IS_WINDOWS:
            self.log_warn("  Windows has no standard fan RPM API - use "
                          "HWiNFO/OpenHardwareMonitor or the BIOS fan "
                          "control page.")
            return
        lines = self._lm_sensors_text()
        if not lines:
            self.log_warn("  lm-sensors is not installed or has no fan "
                          "sensors.")
            return
        found = 0
        for line in lines:
            if re.search(r"fan\d|RPM", line, re.IGNORECASE):
                found += 1
                self.log_info("  " + line.strip())
        if not found:
            self.log_info("  No fan RPM sensors detected by lm-sensors.")
        elif any(re.search(r"fan\d.*0 RPM", l, re.IGNORECASE) for l in lines):
            self.log_warn("  A fan reports 0 RPM - check for a stalled "
                          "or failed fan!")

    #--------------------------------------------------------------------------
    # Log export
    #--------------------------------------------------------------------------
    def _export_log(self):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"RigCheck_log_{stamp}.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            content = self._log.get("1.0", "end-1c")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.log_ok(f"Log exported to: {path}")
        except Exception as exc:
            self.log_err(f"Export failed: {exc}")

    def _clear_log(self):
        """Wipe the diagnostic console log."""
        try:
            self._log.delete("1.0", tk.END)
            self.log_ok("Diagnostic log cleared.")
        except Exception as exc:
            self.log_err(f"Could not clear the log: {exc}")

    def _program_info(self):
        """Write information about RigCheck itself into the console."""
        self.log_head("========== About RigCheck ==========")
        self.log_info(f"{APP_NAME} {APP_VERSION} | {AUTHOR_LABEL}")
        self.log_info("PC Diagnostics & Service Toolkit - built with "
                      "Python, Tkinter and psutil.")
        self.log_info("")
        self.log_info("What RigCheck does:")
        self.log_info("  - Live system information panel (OS, CPU, RAM, "
                      "storage, network).")
        self.log_info("  - Hardware diagnostics: S.M.A.R.T., CPU stress, "
                      "RAM, network, temperatures.")
        self.log_info("  - Crash / event log filtering and service "
                      "utilities (startup, temp cleaning, DNS, ports).")
        self.log_info("  - Fast access to native OS tools.")
        self.log_info("")
        self.log_info("Open-source credits:")
        self.log_info("  CPU stress technique adapted from stress-injector "
                      "(MIT) and pystress (BSD-2-Clause);")
        self.log_info("  see THIRD_PARTY_NOTICES.txt for the required "
                      "license texts.")
        self.log_ok(DISCLAIMER_TEXT)

    def _system_report(self):
        """Write a full system information report into the console."""
        self.log_head("========== System Information Report ==========")
        try:
            os_label = self._get_os_label()
            arch = platform.machine() or platform.architecture()[0]
            self.log_info(
                f"Operating System : {os_label} "
                f"({platform.system()} {arch})")
            self.log_info(
                f"Hostname         : "
                f"{socket.gethostname() or platform.node()}")
            self.log_info(f"CPU              : {self._cpu_name}")

            phys = psutil.cpu_count(logical=False)
            logc = psutil.cpu_count(logical=True)
            try:
                freq = psutil.cpu_freq()
                freq_txt = (f"{int(freq.current)} MHz"
                            if freq and freq.current else "n/a")
            except Exception:
                freq_txt = "n/a"
            self.log_info(
                f"Cores            : {phys or '?'} physical / "
                f"{logc or '?'} logical | {freq_txt}")

            mem = psutil.virtual_memory()
            self.log_info(
                f"Memory           : Total {gb(mem.total)} | "
                f"Used {mem.percent:.1f}% | Free {gb(mem.available)}")
            self.log_info(f"Storage          : {self._storage_summary()}")
            self.log_info(f"Network          : {self._net_label()}")
            self.log_info(f"Uptime           : {format_uptime()}")
            if IS_LINUX:
                try:
                    boot_time = datetime.datetime.fromtimestamp(
                        psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
                    self.log_info(f"Boot time        : {boot_time}")
                except Exception:
                    pass
            self.log_info(f"Python           : {platform.python_version()}")
            self.log_info(
                "Public IP        : hidden by default (privacy) - use the "
                "Show Public IP button to reveal it.")
            self.log_ok("System information report complete.")
        except Exception as exc:
            self.log_err(f"System report failed: {exc}")

    #==========================================================================
    # MODULE 3 - BIOS, BOOT & SECURITY CHECKS
    #==========================================================================
    def _secureboot_worker(self):
        self.log_head("========== Secure Boot + TPM 2.0 Status ==========")
        if IS_WINDOWS:
            code, out = self._run_ps((
                "$sb = 'n/a'; try { $sb = Confirm-SecureBootUEFI } "
                "catch { $sb = 'unsupported' }; "
                "$t = Get-Tpm -ErrorAction SilentlyContinue; "
                "Write-Output ('SecureBoot: ' + $sb); "
                "Write-Output ('TPM Present: ' + $t.TpmPresent); "
                "Write-Output ('TPM Ready  : ' + $t.TpmReady); "
                "Write-Output ('TPM Version: ' + $t.TpmVersion)"))
            self._log_output("Secure Boot / TPM", code, out, 15)
            if not out.strip():
                self.log_warn("  No TPM/Secure Boot data (Windows 10+ and "
                              "some checks need admin).")
        else:
            sb = "Unknown"
            try:
                with open("/sys/firmware/efi/efivars/"
                          "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c",
                          "rb") as fh:
                    sb = ("Enabled" if fh.read()[-1:] == b"\x01"
                          else "Disabled")
            except Exception:
                pass
            if sb == "Unknown" and shutil.which("mokutil"):
                code, out = self._run(["mokutil", "--sb-state"], timeout=15)
                if out.strip():
                    sb = out.strip().strip()
            self.log_info(f"  Secure Boot : {sb}")
            tpm = []
            try:
                if os.path.isdir("/sys/class/tpm"):
                    tpm = [d for d in os.listdir("/sys/class/tpm")
                           if d.startswith("tpm")]
            except Exception:
                pass
            if tpm:
                ver = "2.0"
                try:
                    with open("/sys/class/tpm/tpm0/tpm_version_major",
                              "r") as fh:
                        ver = fh.read().strip() + ".0"
                except Exception:
                    pass
                self.log_ok(f"  TPM         : present ({tpm[0]}) - TPM {ver}")
            else:
                self.log_warn("  TPM         : not detected in "
                              "/sys/class/tpm")

    def _bootmode_worker(self):
        self.log_head("========== UEFI vs CSM Boot Mode Detector ==========")
        if IS_WINDOWS:
            code, out = self._run_ps(
                "Write-Output ('FirmwareType: ' + $env:firmware_type)")
            if out.strip() and "FirmwareType" in out:
                self._log_output("Firmware type", code, out, 10)
            else:
                self.log_warn("  Firmware type not exposed by PowerShell "
                              "here (run in an elevated console if empty).")
        else:
            if os.path.isdir("/sys/firmware/efi"):
                self.log_ok("  Boot mode : UEFI (native, no CSM).")
            else:
                self.log_warn("  Boot mode : Legacy BIOS / CSM - booted in "
                              "MBR compatibility mode.")
                self.log_info("  Converting to UEFI + GPT enables Secure "
                              "Boot and faster boot times.")

    def _rebar_worker(self):
        self.log_head("========== Resizable BAR / SAM Detector ==========")
        if IS_WINDOWS:
            self.log_warn("  Windows does not expose ReBAR status to "
                          "user-mode tools.")
            self.log_info("  Check NVIDIA Control Panel / AMD Adrenalin, "
                          "or BIOS -> Advanced -> Resizable BAR.")
        else:
            if not shutil.which("lspci"):
                self.log_warn("  lspci not installed.")
                return
            code, out = self._run(["lspci"], timeout=20)
            slots = [ln.split()[0] for ln in out.splitlines()
                     if re.search(r"VGA|3D controller|Display controller",
                                  ln)]
            if not slots:
                self.log_warn("  No GPU found on the PCIe bus.")
                return
            for slot in slots:
                self.log_head(f"--- {slot} ---")
                code, out = self._run(["lspci", "-vvvv", "-s", slot],
                                      timeout=30)
                hits = [l for l in out.splitlines()
                        if re.search(r"Resizable BAR|BAR 6|ReBAR", l)]
                if hits:
                    for l in hits:
                        self.log_info("  " + l.strip())
                    self.log_info("  Resizable BAR capability is exposed "
                                  "by this GPU.")
                else:
                    self.log_info("  'Resizable BAR' not shown in this "
                                  "adapter's capability list.")
            self.log_info("  Enable ReBAR/SAM in the BIOS (works best on "
                          "AMD Ryzen + RTX 3000+ / RX 6000+).")

    def _vbs_worker(self):
        self.log_head("========== VBS / Core Isolation (HVCI) Status =======")
        if IS_WINDOWS:
            code, out = self._run_ps(
                "$dg = Get-CimInstance -ClassName Win32_DeviceGuard "
                "-Namespace root\\Microsoft\\Windows\\DeviceGuard "
                "-ErrorAction SilentlyContinue; "
                "if ($dg) { 'VBS status: ' + "
                "$dg.VirtualizationBasedSecurityStatus; "
                "'Security services running: ' + "
                "($dg.SecurityServicesRunning -join ',') } "
                "else { 'No DeviceGuard info (Windows 10+ with VBS).' }")
            self._log_output("VBS / HVCI", code, out, 15)
            if not out.strip():
                self.log_warn("  No VBS data available.")
        else:
            lockdown = "Unknown"
            try:
                with open("/sys/kernel/security/lockdown", "r") as fh:
                    lockdown = fh.read().strip()
            except Exception:
                pass
            self.log_info(f"  Kernel lockdown : {lockdown}")
            for label, args in (("SELinux", ["getenforce"]),
                                ("AppArmor", ["aa-status", "--enabled"])):
                if not shutil.which(args[0]):
                    self.log_info(f"  {label:<16} : not installed")
                    continue
                code, out = self._run(args, timeout=15)
                self.log_info(f"  {label:<16} : "
                              f"{out.strip() if out.strip() else 'not active'}")

    def _faststartup_worker(self):
        self.log_head("========== Fast Startup Status ==========")
        if IS_WINDOWS:
            code, out = self._run(
                ["reg", "query",
                 r"HKLM\SYSTEM\CurrentControlSet\Control\Session "
                 r"Manager\Power", "/v", "HiberbootEnabled"], timeout=20)
            if code == 0 and "HiberbootEnabled" in out:
                m = re.search(r"HiberbootEnabled\s+REG_DWORD\s+0x(\w+)", out)
                on = bool(m and int(m.group(1), 16) == 1)
                if on:
                    self.log_ok("  Fast Startup : ENABLED")
                    self.log_warn("  Hiberboot keeps the kernel/driver "
                                  "state across restarts - this can leave "
                                  "driver memory loaded and cause USB/audio "
                                  "glitches. Disable it if you see such "
                                  "issues.")
                else:
                    self.log_ok("  Fast Startup : disabled")
            else:
                self.log_warn("  Fast Startup registry key missing (the "
                              "Windows 10/11 default is usually ON).")
        else:
            config = "not configured"
            try:
                with open("/sys/power/disk", "r") as fh:
                    config = fh.read().strip()
            except Exception:
                pass
            self.log_info(f"  Hibernation config : {config}")
            self.log_info("  Linux manages suspend/hibernate via systemd "
                          "- no Windows-style Fast Startup, so no "
                          "driver-state leak risk.")

    #==========================================================================
    # MODULE 3b - UPDATES, RELIABILITY & MINIDUMPS
    #==========================================================================
    def _reliability_worker(self):
        self.log_head("========== System Reliability Scanner ==========")
        if IS_WINDOWS:
            code, out = self._run_ps(
                "Get-CimInstance -ClassName Win32_ReliabilityRecords "
                "-MaxEvents 12 | Select-Object Date, Type, SourceName, "
                "@{n='Msg';e={ if ($_.Message.Length -gt 120) { "
                "$_.Message.Substring(0,120) } else { $_.Message } }} | "
                "Format-List | Out-String -Width 160")
            self._log_output("Reliability history", code, out, 40)
            if not out.strip():
                self.log_warn("  Reliability history empty (new install or "
                              "permissions).")
        else:
            code, out = self._run(
                ["journalctl", "-b", "--priority=0..3", "--no-pager"],
                timeout=60)
            lines = [l for l in out.splitlines() if l.strip()]
            if lines:
                self.log_warn(f"  {len(lines)} critical/error entr(ies) "
                              f"this boot session:")
                for line in lines[:12]:
                    self.log_info("    " + line)
            else:
                self.log_ok("  No critical/error journal entries this boot.")
            code, out = self._run(
                ["journalctl", "--since=-7days", "--priority=0..3",
                 "--no-pager"], timeout=70)
            week = len([l for l in out.splitlines() if l.strip()])
            self.log_info(f"  Last 7 days: {week} critical/error "
                          f"entr(ies).")

    def _pending_worker(self):
        self.log_head("========== Pending Updates / Reboot Check ==========")
        if IS_WINDOWS:
            code, out = self._run_ps(
                "$keys = @("
                "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                "WindowsUpdate\\Auto Update\\RebootRequired', "
                "'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session "
                "Manager\\PendingFileRenameOperations', "
                "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                "Component Based Servicing\\RebootPending'); "
                "$found = @(); foreach ($k in $keys) { "
                "if (Test-Path $k) { $found += $k } }; "
                "if ($found) { 'Pending reboot markers:'; $found } "
                "else { 'No pending reboot markers.' }")
            self._log_output("Pending reboot", code, out, 15)
            code, out = self._run_ps(
                "$h = Get-HotFix | Sort-Object InstalledOn -Descending | "
                "Select-Object -First 5; "
                "$h | Format-Table HotFixID, InstalledOn -AutoSize | "
                "Out-String -Width 60")
            if out.strip():
                self.log_head("  Recent installed updates:")
                self._log_output("Installed updates", code, out, 12)
        else:
            if os.path.exists("/var/run/reboot-required"):
                self.log_warn("  A reboot IS required (pending kernel "
                              "updates) - /var/run/reboot-required exists.")
            else:
                self.log_ok("  No pending reboot marker "
                            "(/var/run/reboot-required).")
            if shutil.which("dnf"):
                code, out = self._run(["dnf", "check-update"], timeout=120)
                if code == 100:
                    n = max(len([l for l in out.splitlines() if l.strip()]) - 1, 0)
                    self.log_warn(f"  {n} package update(s) available - "
                                  "run 'sudo dnf upgrade'.")
                elif code == 0:
                    self.log_ok("  System is up to date.")
                else:
                    self.log_warn(f"  dnf check-update error: {out}")
            elif shutil.which("apt-get"):
                code, out = self._run(["apt-get", "-s", "upgrade"],
                                      timeout=120)
                n = len([l for l in out.splitlines() if l.startswith("Inst ")])
                if n:
                    self.log_warn(f"  {n} package update(s) available - "
                                  "run 'sudo apt upgrade'.")
                else:
                    self.log_ok("  System is up to date.")
            elif shutil.which("zypper"):
                code, out = self._run(["zypper", "list-updates"], timeout=120)
                self._log_output("zypper list-updates", code, out, 10)
            elif shutil.which("pacman"):
                code, out = self._run(["checkupdates"], timeout=120)
                if code == 0 and out.strip():
                    self.log_warn(f"  {len(out.splitlines())} update(s) "
                                  "available (checkupdates).")
                else:
                    self.log_ok("  System is up to date (checkupdates).")
            else:
                self.log_warn("  No supported package manager detected.")

    def _minidump_worker(self):
        self.log_head("========== Crash Minidump Analyzer ==========")
        if IS_WINDOWS:
            areas = [
                os.path.join(os.environ.get("ProgramData",
                                            r"C:\ProgramData"),
                             "Microsoft", "Windows", "WER",
                             "ReportQueue"),
                os.path.join(os.environ.get("ProgramData",
                                            r"C:\ProgramData"),
                             "Microsoft", "Windows", "WER",
                             "ReportArchive"),
            ]
            wer_files = []
            for area in areas:
                if os.path.isdir(area):
                    try:
                        for root, dirs, files in os.walk(area):
                            for f in files:
                                if f.lower().startswith("report") and \
                                        f.lower().endswith(".wer"):
                                    wer_files.append(os.path.join(root, f))
                    except Exception:
                        pass
            if wer_files:
                self.log_ok(f"  Found {len(wer_files)} Windows Error "
                            "Reporting file(s).")
                for wer in wer_files[:8]:
                    self.log_info("  --- " + wer)
                    module = None
                    try:
                        with open(wer, "r", errors="replace") as fh:
                            for line in fh:
                                m = re.search(
                                    r"(Sig\[2\]|faulting module)[^\n]*",
                                    line, re.IGNORECASE)
                                if m:
                                    module = (m.group(0).split("=", 1)
                                              [-1].strip())
                    except Exception:
                        pass
                    if module:
                        self.log_info("      Faulting module: " + module)
                    else:
                        self.log_info("      (no faulting module line "
                                      "parsed)")
            else:
                self.log_info("  No WER report files found.")
            mini = os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"), "Minidump")
            if os.path.isdir(mini):
                files = sorted(os.listdir(mini))
                if files:
                    self.log_warn(f"  {len(files)} minidump(s) in {mini} - "
                                  "latest:")
                    for f in files[-5:]:
                        self.log_warn("    " + f)
            else:
                self.log_info("  No C:\\Windows\\Minidump folder.")
        else:
            code, out = self._run(
                ["journalctl", "-b", "--no-pager"], timeout=60)
            hits = [l for l in out.splitlines()
                    if re.search(r"segfault|oops|panic|kernel BUG|"
                                 r"general protection fault", l,
                                 re.IGNORECASE)]
            if hits:
                self.log_warn(f"  {len(hits)} crash signature(s) in the "
                              "kernel log this boot:")
                for line in hits[:10]:
                    self.log_info("    " + line.strip())
            else:
                self.log_ok("  No kernel crash signatures this boot.")
            dumps = []
            for path in ("/var/crash", "/var/lib/systemd/coredump"):
                if os.path.isdir(path):
                    try:
                        items = os.listdir(path)
                        dumps.extend([path + "/" + i for i in items[:8]])
                    except Exception:
                        pass
            if dumps:
                self.log_warn("  Core dump files found:")
                for d in dumps:
                    self.log_warn("    " + d)
            else:
                self.log_info("  No core dump files found in /var/crash or "
                              "/var/lib/systemd/coredump.")

    #==========================================================================
    # MODULE 5 - SERVICE AUTOMATION & SAFETY TOOLS
    #==========================================================================
    def _restorepoint_worker(self):
        self.log_head("========== Create System Restore Point ==========")
        if IS_WINDOWS:
            self.log_info("  Creating 'RigCheck Diagnostics Before Fix'...")
            code, out = self._run_ps(
                "Checkpoint-Computer -Description 'RigCheck Diagnostics "
                "Before Fix' -RestorePointType MODIFY_SETTINGS "
                "-ErrorAction Stop")
            if code == 0:
                self.log_ok("  System Restore Point created.")
            else:
                self.log_warn("  System Protection is off or elevation is "
                              "missing.")
                self.log_info("  Enable it via 'System Properties -> "
                              "System Protection', or run RigCheck from an "
                              "admin console.")
                self.log_warn(f"  Details: {out}")
        else:
            self.log_info("  Linux snapshot support...")
            if shutil.which("btrfs"):
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                snapshot = "/@rigcheck-snapshot-" + stamp
                self.log_info("  Creating a btrfs snapshot via the sudo "
                              "terminal (same mechanism as smartctl).")
                code, out = self._run_root_batch(
                    ["btrfs subvolume snapshot / " + snapshot],
                    timeout=240)
                if code == 0:
                    self.log_ok(f"  Snapshot created: {snapshot}")
                else:
                    self.log_warn("  btrfs snapshot did not complete here.")
                    self.log_info("  Run it yourself: "
                                  "sudo btrfs subvolume snapshot / "
                                  + snapshot)
            elif shutil.which("lvm"):
                self.log_info("  LVM detected - snapshot a logical volume "
                              "from root with 'lvcreate -s'.")
            else:
                self.log_info("  No snapshot-capable volume manager found.")
                self.log_warn("  Simplest safety net: back up important "
                              "files before running repairs.")

    def _repair_worker(self):
        self.log_head("========== SFC / DISM Automated Repair Loop =========")
        if IS_WINDOWS:
            self.log_info("  Opening a visible prompt to run the repair "
                          "loop (elevate when asked):")
            self.log_info("    sfc /scannow -> DISM /RestoreHealth -> "
                          "sfc /scannow")
            self._launch_visible(
                "SFC / DISM Repair Loop",
                'start "RigCheck - Repair Loop" cmd /k '
                '"echo Step 1: sfc && sfc /scannow && '
                'echo Step 2: DISM repair && '
                'DISM /Online /Cleanup-Image /RestoreHealth && '
                'echo Step 3: verify && sfc /scannow && '
                'echo Repair loop complete."')
            self.log_warn("  Accept the UAC prompt; if you cannot elevate, "
                          "run the loop from an admin console.")
        else:
            self.log_info("  Linux integrity scan (read-only)...")
            if shutil.which("rpm"):
                self.log_info("  Running rpm -Va (opens a sudo terminal if "
                              "root is required)...")
                code, out = self._run_root_batch(["rpm -Va"], timeout=240)
                if code != 0 and not out:
                    self.log_warn("  rpm -Va needs root and could not run "
                                  "here - run it from a root console.")
                    return
                issues = [l for l in out.splitlines() if l.strip()]
                if issues:
                    self.log_warn(f"  {len(issues)} modified/missing file(s):")
                    self._log_output("rpm -Va", code, out, 25)
                    self.log_info("  Repair from a root shell: "
                                  "sudo dnf verify <package> or "
                                  "sudo rpm -V <package>.")
                else:
                    self.log_ok("  rpm -Va: package integrity is clean.")
            elif shutil.which("apt-get"):
                code, out = self._run(["apt-get", "check"], timeout=60)
                self._log_output("apt-get check", code, out, 10)
            else:
                self.log_info("  No RPM/apt tool found - use your package "
                              "manager's integrity checker.")

    def _winsock_worker(self):
        self.log_head("========== Winsock / TCP-IP Reset ==========")
        if IS_WINDOWS:
            self.log_info("  Opening a visible elevated prompt to reset the "
                          "network stack...")
            self._launch_visible(
                "Winsock Reset",
                'start "RigCheck - Winsock Reset" cmd /k '
                '"netsh winsock reset && netsh int ip reset && '
                'ipconfig /flushdns && echo DONE - a reboot is advised."')
            self.log_warn("  Accept the UAC prompt - a reboot is "
                          "recommended afterwards.")
        else:
            if shutil.which("systemctl") and self._run(
                    ["systemctl", "is-active", "NetworkManager"],
                    timeout=10)[0] == 0:
                self.log_info("  Restarting NetworkManager via the sudo "
                              "terminal...")
                code, out = self._run_root_batch(
                    ["systemctl restart NetworkManager"], timeout=60)
                if code == 0:
                    self.log_ok("  NetworkManager restarted.")
                else:
                    self.log_warn("  NetworkManager restart did not "
                                  "complete here.")
                for cmd in (["resolvectl", "flush-caches"],
                            ["systemd-resolve", "--flush-caches"]):
                    if shutil.which(cmd[0]):
                        self._run(cmd, timeout=20)
            else:
                self.log_info("  No active systemd NetworkManager found - "
                              "restart your network from the GUI or: "
                              "sudo systemctl restart networking")
                for cmd in (["resolvectl", "flush-caches"],
                            ["systemd-resolve", "--flush-caches"]):
                    if shutil.which(cmd[0]):
                        self._run(cmd, timeout=20)

    def _bloat_worker(self):
        self.log_head("========== Temp + Bloatware Cleaner ==========")
        if IS_WINDOWS:
            targets = [os.environ.get("TEMP", ""),
                       os.environ.get("TMP", ""),
                       os.path.join(os.environ.get(
                           "SystemRoot", r"C:\Windows"), "Prefetch")]
        else:
            targets = ["/tmp", "/var/tmp"]
        targets = [t for t in targets if t and os.path.isdir(t)]
        candidates = []
        total_size = 0
        for tdir in sorted(set(targets)):
            self.log_info(f"  Scanning: {tdir}")
            try:
                with os.scandir(tdir) as it:
                    for entry in it:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                sz = entry.stat().st_size
                                candidates.append(entry.path)
                                total_size += sz
                            elif entry.is_dir(follow_symlinks=False):
                                sz = self._dir_size(entry.path)
                                if sz is not None:
                                    candidates.append(entry.path)
                                    total_size += sz
                        except (OSError, ValueError):
                            continue
            except Exception as exc:
                self.log_warn(f"    Scan error: {exc}")
        self.log_info(f"  Temp items ready: {len(candidates)} item(s), "
                      f"{gb(total_size)}.")
        self.log_info("  Reviewing startup 'telemetry' entries...")
        if IS_WINDOWS:
            code, out = self._run(
                ["reg", "query",
                 r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"],
                timeout=20)
            if out and code == 0:
                self.log_info("  HKCU Run entries (review for bloat):")
                self._log_output("HKCU Run", code, out, 15)
            else:
                self.log_info("  No HKCU Run entries.")
        else:
            autostart = os.path.expanduser("~/.config/autostart")
            if os.path.isdir(autostart):
                entries = os.listdir(autostart)
                if entries:
                    self.log_info("  Autostart entries (review for "
                                  "telemetry):")
                    for e in entries:
                        self.log_info("    " + e)
                else:
                    self.log_info("  No autostart entries.")
            else:
                self.log_info("  No ~/.config/autostart folder.")
        if candidates:
            self.ask_user(
                "Confirm Temporary File Cleanup",
                f"Purge {len(candidates)} temporary item(s) "
                f"({gb(total_size)})?\n\n"
                "Only safe temp data is removed; in-use files are "
                "automatically skipped. Continue?",
                candidates)
        else:
            self.log_info("  Nothing to clean.")

    #==========================================================================
    # MODULE 4 - PERIPHERAL & MEDIA TESTING
    #==========================================================================
    def _pixel_worker(self):
        self.log_head("========== Monitor Pixel Checker ==========")
        try:
            top = tk.Toplevel(self.root)
        except Exception as exc:
            self.log_err(f"  Cannot open a full-screen test window: {exc}")
            return
        top.attributes("-fullscreen", True)
        top.configure(cursor="crosshair", bg="#ff0000")
        colors = ["#ff0000", "#00ff00", "#0000ff", "#ffffff", "#000000",
                  "#ff00ff", "#00ffff", "#ffff00", "#808080"]
        idx = [0]
        lbl = tk.Label(top,
                       text="Pixel Checker - 9-colour cycle  |  Space / "
                            "click = advance  |  Esc = exit",
                       font=(self._mono, 14), bg="#000000", fg="#ffffff")
        lbl.pack(side=tk.BOTTOM)
        lbl.focus_set()

        def advance():
            idx[0] = (idx[0] + 1) % len(colors)
            top.configure(bg=colors[idx[0]])

        def autocycle():
            advance()
            top.after(1500, autocycle)

        top.bind("<space>", lambda e: advance())
        top.bind("<Button-1>", lambda e: advance())
        top.bind("<Escape>", lambda e: top.destroy())
        autocycle()
        self.log_info("  Fullscreen colour cycling running - look for dead "
                      "pixels / burn-in. Press Esc when done.")

    def _write_test_wavs(self):
        """Build the audio test set. Returns (label, path, channels) list.

        - 'Front L' / 'Front R': true 2-channel stereo, tone hard-panned,
          played with the system's basic sound API (winsound / mplayer).
        - Center / LFE / Surround-L / Surround-R: TRUE 5.1 files with 6
          channels (FL,FR,FC,LFE,SL,SR). The tone is only written into the
          target channel, so on a real 5.1/7.1 set the physical centre,
          subwoofer and rear speakers are the only ones that sound.
          Generic stereo output can never reach those speakers - that is why
          these must be played through a multichannel-aware player.
        """
        tmp = tempfile.gettempdir()
        rate = 44100
        frames = int(rate * 0.6)
        results = []

        # (label, kind, freq, target_index_or_gains, nchannels)
        # 6-channel layout: 0=FL, 1=FR, 2=FC, 3=LFE, 4=SL, 5=SR
        spec = (
            ("Front left (L)", "stereo", 880, (1.0, 0.0), 2),
            ("Front right (R)", "stereo", 880, (0.0, 1.0), 2),
            ("Center (C)", "5.1", 880, 2, 6),
            ("Sub / LFE", "5.1", 55, 3, 6),
            ("Surround left (SL)", "5.1", 1320, 4, 6),
            ("Surround right (SR)", "5.1", 1760, 5, 6),
        )
        for label, kind, freq, target, nch in spec:
            safe = re.sub(r"[^A-Za-z0-9]+", "_", label)
            path = os.path.join(tmp, f"rigcheck_tone_{safe}.wav")
            with wave.open(path, "w") as f:
                f.setnchannels(nch)
                f.setsampwidth(2)
                f.setframerate(rate)
                data = bytearray()
                for i in range(frames):
                    sample = int(0.35 * 32767 *
                                 math.sin(2 * math.pi * freq * i / rate))
                    if kind == "stereo":
                        g_l, g_r = target
                        data += struct.pack(
                            "<hh", int(g_l * sample), int(g_r * sample))
                    else:
                        values = [0] * 6
                        values[target] = sample
                        data += struct.pack(
                            "<6h", *values)
                f.writeframes(bytes(data))
            results.append((label, path, nch))
        return results

    def _audio_worker(self):
        self.log_head("========== Audio Surround Sound Tester ==========")
        self.log_info("  Playing 6 tones, each routed to ONE speaker:")
        self.log_info("    Front L/R : stereo pan -> winsound / default "
                      "player")
        self.log_info("    Center, Sub, Surround L/R : TRUE 5.1 channel "
                      "files -> multichannel player")
        try:
            wavs = self._write_test_wavs()
        except Exception as exc:
            self.log_err(f"  Audio generation failed: {exc}")
            return
        if IS_WINDOWS:
            try:
                import winsound
            except Exception:
                self.log_warn("  winsound unavailable on this Python.")
                return
            for label, path, nch in wavs:
                if nch == 2:
                    self.log_info(f"  Playing: {label}")
                    winsound.PlaySound(path, winsound.SND_FILENAME)
            self.log_info("  Opening the 5.1 channel files with Windows "
                          "Media Player - it routes Centre / Sub / Rear to "
                          "your configured speakers...")
            for label, path, nch in wavs:
                if nch == 2:
                    continue
                self.log_info(f"  Playing: {label}")
                self._run_ps(
                    "$w = New-Object -ComObject WMPlayer.OCX; "
                    "$w.URL = '" + path.replace("\\", "/")
                    + "'; $w.controls.play(); "
                    "Start-Sleep -Seconds 2; $w.close()", timeout=15)
        else:
            player = next((p for p in ("paplay", "aplay",
                                       "ffplay", "canberra-gtk-play")
                           if shutil.which(p)), None)
            if not player:
                self.log_warn("  No audio player found (install "
                              "pulseaudio-utils / alsa-utils).")
                return
            self.log_info(f"  Using multichannel player: {player}")
            for label, path, nch in wavs:
                self.log_info(f"  Playing: {label}")
                if player == "ffplay":
                    self._run(["ffplay", "-nodisp", "-autoexit", path],
                              timeout=25)
                elif player == "canberra-gtk-play":
                    self._run(["canberra-gtk-play", "-f", path],
                              timeout=25)
                else:
                    self._run([player, path], timeout=25)
        self.log_info("  Centre and Surround only sound on the REAL "
                      "speakers if the OS is set to 5.1/7.1 (Sound Control "
                      "Panel, not stereo).")
        self.log_info("  If Centre / Sub / Rear stay silent while the fronts "
                      "work, your PC output is still configured as 2.0 "
                      "stereo - switch it to 5.1/7.1 and rerun.")

    def _keyboard_worker(self):
        self.log_head("========== Keyboard + Mouse Input Tester ==========")
        try:
            top = tk.Toplevel(self.root)
        except Exception as exc:
            self.log_err(f"  Cannot open the input test window: {exc}")
            return
        top.title("Input Tester - press keys / double-click fast, "
                  "Esc to close")
        top.geometry("640x380")
        counts = {"keys": 0, "dclicks": 0}
        last = [0.0]
        info = tk.Label(top, text="Keys pressed: 0\n"
                                  "Double-clicks: 0\n"
                                  "Last double-click latency: n/a",
                        font=(self._mono, 12), justify="left")
        info.pack(padx=12, pady=10, anchor="w")
        log_area = tk.Text(top, height=13, font=(self._mono, 11))
        log_area.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        top.focus_force()

        def on_key(e):
            counts["keys"] += 1
            name = getattr(e, "keysym", None) or e.char or "?"
            log_area.insert(tk.END, f"Key: {name}  ")
            info.config(text=f"Keys pressed: {counts['keys']}\n"
                             f"Double-clicks: {counts['dclicks']}\n"
                             f"Last double-click latency: n/a")
            log_area.see(tk.END)

        def on_double(e):
            counts["dclicks"] += 1
            now = time.time()
            dt = (now - last[0]) * 1000 if last[0] else 0
            last[0] = now
            verdict = "ok" if dt >= 200 else "too fast / suspicious"
            log_area.insert(tk.END, f"Double-click {dt:.0f} ms "
                                    f"({verdict})\n")
            info.config(text=f"Keys pressed: {counts['keys']}\n"
                             f"Double-clicks: {counts['dclicks']}\n"
                             f"Last double-click latency: {dt:.0f} ms")
            log_area.see(tk.END)

        top.bind("<Key>", on_key)
        top.bind("<Double-Button-1>", on_double)
        top.bind("<Escape>", lambda e: top.destroy())

    def _usb_worker(self):
        self.log_head("========== USB Port & Controller Inspector =========")
        if IS_WINDOWS:
            code, out = self._run_ps(
                "Get-PnpDevice | Where-Object { $_.Class -eq 'USB' -or "
                "$_.FriendlyName -like '*USB*' } | Select-Object Status, "
                "FriendlyName, Class | Format-Table -AutoSize | Out-String "
                "-Width 160")
            if out.strip():
                self._log_output("USB devices", code, out, 40)
            else:
                self.log_warn("  No USB devices listed (permissions).")
            return
        for tool in (["lsusb"], ["lsusb", "-t"]):
            if shutil.which("lsusb"):
                code, out = self._run(tool, timeout=25)
                self._log_output(" ".join(tool), code, out, 40)
            else:
                self.log_warn("  lsusb not installed "
                              "(sudo dnf install usbutils).")
                break
        if shutil.which("lsusb"):
            code, out = self._run(["lsusb", "-v"], timeout=40)
            power = [l.strip() for l in out.splitlines()
                     if "MaxPower" in l]
            if power:
                self.log_head("  USB power draw:")
                for l in power:
                    self.log_info("  " + l)
            else:
                self.log_warn("  MaxPower not shown (needs 'sudo lsusb -v' "
                              "for full descriptors).")

    #==========================================================================
    # MODULE 5b - NETWORK, SECURITY & MAINTENANCE
    #==========================================================================
    def _wifi_worker(self):
        self.log_head("========== Wi-Fi Signal / Channel Analyzer =========")
        if IS_WINDOWS:
            code, out = self._run(["netsh", "wlan", "show", "interfaces"],
                                  timeout=25)
            if code != 0 or not out.strip():
                self.log_warn("  No Wi-Fi interface (wired-only system or "
                              "netsh restricted).")
                return
            fields = {}
            for line in out.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fields[k.strip()] = v.strip()
            for key in ("Name", "SSID", "Signal", "Radio type", "Channel",
                        "Channel frequency (GHz)", "Band",
                        "Receive rate (Mbps)", "Transmit rate (Mbps)"):
                if fields.get(key):
                    self.log_info(f"  {key:<26}: {fields[key]}")
            m = re.search(r"(\d+)\s*%", fields.get("Signal", ""))
            if m:
                pct = int(m.group(1))
                self.log_info(f"  Approx signal: ~{pct / 2 - 100:.0f} dBm "
                              "(Windows reports % only)")
                if pct < 40:
                    self.log_warn("  Weak signal - move closer or check "
                                  "for interference.")
        else:
            got = False
            if shutil.which("iw"):
                code, out = self._run(["iw", "dev"], timeout=25)
                for line in out.splitlines():
                    if line.strip().startswith("Interface") and ":" in line:
                        iface = line.split(":", 1)[1].strip()
                        got = True
                        self.log_head(f"--- {iface} ring ---")
                        code, out = self._run(["iw", "dev", iface, "link"],
                                              timeout=25)
                        for sub in out.splitlines():
                            if sub.strip():
                                self.log_info("  " + sub.strip())
            if shutil.which("nmcli"):
                code, out = self._run(
                    ["nmcli", "-f", "SSID,CHAN,FREQ,SIGNAL,RATE", "dev",
                     "wifi", "list", "--rescan", "no"], timeout=25)
                if out.strip():
                    got = True
                    self.log_head("  NetworkManager Wi-Fi scan:")
                    self._log_output("nmcli wifi", code, out, 20)
            if not got:
                self.log_warn("  No Wi-Fi tools found (install iw or "
                              "NetworkManager CLI).")

    def _hosts_worker(self):
        self.log_head("========== Hosts File Inspector ==========")
        if IS_WINDOWS:
            hosts = os.path.join(os.environ.get(
                "SystemRoot", r"C:\Windows"), "System32", "drivers",
                "etc", "hosts")
        else:
            hosts = "/etc/hosts"
        if not os.path.exists(hosts):
            self.log_warn(f"  Hosts file not found: {hosts}")
            return
        active = []
        with open(hosts, "r", errors="replace") as fh:
            for line in fh.read().splitlines()[:400]:
                if line.strip() and not line.lstrip().startswith("#"):
                    active.append(line.rstrip())
        suspicious = []
        benign = []
        for l in active:
            if re.search(r"\b(localhost|localhost\.localdomain)",
                         l, re.IGNORECASE) and not re.search(
                            r"^\s*(127\.0\.0\.1|::1)", l):
                suspicious.append(l)
            else:
                benign.append(l)
        self.log_info(f"  Active entries: {len(active)}")
        for l in benign[:20]:
            self.log_info("    " + l)
        if len(benign) > 20:
            self.log_info(f"    ... {len(benign) - 20} more")
        if suspicious:
            self.log_warn("  Suspicious entries (hostname redirected away "
                          "from loopback):")
            for l in suspicious:
                self.log_warn("    " + l)
            default = [
                "# RigCheck default hosts file (restored).\n",
                "127.0.0.1 localhost\n",
                "::1 localhost ip6-localhost ip6-loopback\n",
                "ff02::1 ip6-allnodes\n",
                "ff02::2 ip6-allrouters\n",
            ]
            try:
                backup = hosts + ".rigcheck.bak"
                with open(hosts, "r", errors="replace") as fh:
                    with open(backup, "w", encoding="utf-8") as bf:
                        bf.write(fh.read())
                with open(hosts, "w", encoding="utf-8") as fh:
                    fh.writelines(default)
                self.log_ok(f"  Hosts file restored to default (backup: "
                            f"{backup}).")
            except (PermissionError, OSError):
                self.log_info("  The hosts file is protected - restoring it "
                              "via an elevated prompt instead.")
                tmp = None
                try:
                    fh = tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", delete=False,
                        prefix="rigcheck_hosts_", suffix=".txt")
                    fh.writelines(default)
                    fh.close()
                    tmp = fh.name
                except Exception as exc:
                    self.log_warn(f"  Could not stage hosts file: {exc}")
                    return
                if IS_WINDOWS:
                    lines = [
                        "'# RigCheck default hosts file (restored).'",
                        "'127.0.0.1 localhost'",
                        "'::1 localhost ip6-localhost ip6-loopback'",
                        "'ff02::1 ip6-allnodes'",
                        "'ff02::2 ip6-allrouters'",
                    ]
                    code, out = self._run_root_batch(
                        ["Copy-Item -LiteralPath '"
                            + hosts.replace("\\", "/")
                            + "' -Destination '"
                            + (hosts + ".rigcheck.bak").replace("\\", "/")
                            + "' -Force",
                         "Set-Content -LiteralPath '"
                            + hosts.replace("\\", "/")
                            + "' -Value (" + ", ".join(lines)
                            + ") -Encoding Ascii"],
                        timeout=60)
                else:
                    code, out = self._run_root_batch(
                        ["cp -a " + shlex.quote(hosts)
                            + " " + shlex.quote(hosts + ".rigcheck.bak"),
                         "install -m 644 " + shlex.quote(tmp)
                            + " " + shlex.quote(hosts)],
                        timeout=60)
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                if code == 0:
                    self.log_ok(f"  Hosts file restored to default (backup: "
                                f"{hosts + '.rigcheck.bak'}).")
                else:
                    self.log_warn("  Could not restore the hosts file - "
                                  "edit it manually (admin).")
            except Exception as exc:
                self.log_warn(f"  Restore failed: {exc}")
        else:
            self.log_ok("  No suspicious redirects found.")

    def _mtu_worker(self):
        self.log_head("========== MTU & Packet Fragmentation Test ==========")
        target = "8.8.8.8"
        hi, lo = 1472, 500
        best = lo
        while hi - lo > 4:
            mid = (hi + lo) // 2
            if IS_WINDOWS:
                code, out = self._run(
                    ["ping", "-f", "-l", str(mid), "-n", "1", target],
                    timeout=8)
            else:
                code, out = self._run(
                    ["ping", "-M", "do", "-s", str(mid), "-c", "1",
                     "-W", "2", target], timeout=8)
            if code == 0:
                lo, best = mid, mid
            else:
                hi = mid
        mtu = best + 28
        self.log_info(f"  Max non-fragmenting payload : {best} bytes")
        self.log_info(f"  Suggested MTU                : {mtu} bytes "
                      f"(payload + 28 bytes of header)")
        if IS_LINUX and shutil.which("nmcli"):
            self.log_info("  Apply with: sudo nmcli connection modify "
                          "<name> 802-3-ethernet.mtu " + str(mtu))

    def _firewall_worker(self):
        self.log_head("========== Firewall + Antivirus Status ==========")
        if IS_WINDOWS:
            code, out = self._run_ps(
                "Get-NetFirewallProfile | Select-Object Name, Enabled | "
                "Format-Table -AutoSize | Out-String -Width 60")
            if out.strip():
                self.log_head("  Windows Firewall profiles:")
                self._log_output("Firewall", code, out, 10)
            code, out = self._run_ps(
                "Get-CimInstance -Namespace root\\SecurityCenter2 "
                "-ClassName AntiVirusProduct -ErrorAction SilentlyContinue "
                "| Select-Object -ExpandProperty displayName")
            if out.strip():
                self.log_head("  Active antivirus products:")
                self._log_output("Antivirus", code, out, 8)
            else:
                self.log_warn("  No antivirus reported by SecurityCenter "
                              "2 (Defender should be active on Windows "
                              "10/11).")
        else:
            if shutil.which("firewall-cmd"):
                code, out = self._run(["firewall-cmd", "--state"], timeout=15)
                state = out.strip() if out.strip() else "inactive"
                self.log_info(f"  firewalld   : {state}")
            if shutil.which("ufw"):
                code, out = self._run(["ufw", "status"], timeout=15)
                self.log_info("  ufw         : "
                              f"{(out.strip()[:40] or 'not installed/config')}")
            if shutil.which("nft"):
                code, out = self._run(["nft", "list", "ruleset"], timeout=15)
                if out.strip():
                    self.log_info(f"  nftables    : rules present "
                                  f"({len(out.splitlines())} lines)")
                else:
                    self.log_info("  nftables    : empty or user "
                                  "permission needed.")
            if shutil.which("getenforce"):
                code, out = self._run(["getenforce"], timeout=15)
                if out.strip():
                    self.log_info(f"  SELinux     : {out.strip()}")
            if shutil.which("clamav-daemon") or shutil.which("clamdscan"):
                self.log_info("  Antivirus   : ClamAV present.")
            else:
                self.log_info("  Antivirus   : none detected - consider "
                              "ClamAV or your distro's security policy.")


#=============================================================================
# Entry point
#=============================================================================
def main():
    # Crisp HiDPI rendering on Windows where available.
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    # RigCheck must never run as superuser: honest reports need a normal
    # user session, and root could mask or damage things. Refuse to start.
    if IS_LINUX:
        try:
            if os.geteuid() == 0:
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror(
                    APP_NAME + " - Refusing to run as root",
                    "RigCheck must NOT be started as root / with sudo.\n\n"
                    "Running as superuser produces misleading reports and "
                    "can harm your system.\n\n"
                    "Please close this and launch it as a normal user, "
                    "for example:\n\n"
                    "    python3 RigCheck.py")
                try:
                    root.destroy()
                except Exception:
                    pass
                sys.exit(1)
        except AttributeError:
            pass

    root = tk.Tk()
    RigCheckApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()