#!/usr/bin/env python3
"""
Bitcoin & Electrs Node Manager
A GUI application for managing local Bitcoin and Electrs nodes with embedded terminals.
"""

import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import subprocess
import threading
import queue
import os
import sys
import time
import json
import traceback
import requests
from pathlib import Path
import shutil
import re

# ── Single-instance guard (macOS / Linux) ────────────────────────────────────
# On macOS, launching a .app can fire two launch events in quick succession,
# causing the app to open, close, then reopen.  We hold an exclusive file lock
# for the entire lifetime of the process; any duplicate launch sees the lock
# taken and exits silently before creating any windows.
try:
    import fcntl as _fcntl
    _HAVE_FCNTL = True
except ImportError:
    _HAVE_FCNTL = False  # Windows — not needed there


# ---------------------------------------------------------------------------
# Config path
# ---------------------------------------------------------------------------

APP_NAME        = "BitcoinNodeManager"
CONFIG_FILENAME = "node_manager_config.json"


def get_config_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path.home() / ".config" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# macOS colour palette
# ---------------------------------------------------------------------------

BG          = '#f2f2f7'
PANEL_BG    = '#ffffff'
BAR_BG      = '#ffffff'
PATH_BOX_BG = '#ffffff'
BORDER      = '#d1d1d6'
BORDER_DARK = '#c7c7cc'

MAC_BLUE    = '#007aff'
MAC_BLUE_H  = '#0071eb'   # hover
MAC_RED     = '#ff3b30'
MAC_RED_H   = '#e6352b'
MAC_GREEN   = '#34c759'
MAC_GREEN_H = '#2fb350'
MAC_ORANGE  = '#ff9500'
MAC_ORANGE_H= '#e68600'

BTN_FILL    = '#e5e5ea'   # secondary button normal
BTN_FILL_H  = '#d8d8de'   # secondary button hover

TEXT_MAIN   = '#1c1c1e'
TEXT_SEC    = '#48484a'
TEXT_TER    = '#8e8e93'
TEXT_WHITE  = '#ffffff'

IND_GREEN   = '#34c759'
IND_OFF     = '#d1d1d6'

TERM_BG     = '#1e1e1e'
TERM_FG     = '#d4d4d4'


# ---------------------------------------------------------------------------
# MacButton — tk.Label behaves as a button that respects colours on macOS.
# tk.Button uses the native Aqua renderer which ignores bg/fg completely.
# ---------------------------------------------------------------------------

class MacButton(tk.Label):
    """
    A clickable Label that renders with explicit colours on macOS.
    Supports hover feedback and disabled state.
    """
    def __init__(self, parent, text, command,
                 bg=BTN_FILL, fg=TEXT_MAIN,
                 hover_bg=None,
                 font=('Helvetica Neue', 11),
                 padx=14, pady=5,
                 radius=0,     # unused — kept for API compatibility
                 **kwargs):
        super().__init__(
            parent,
            text=text,
            bg=bg, fg=fg,
            font=font,
            padx=padx, pady=pady,
            cursor='hand2',
            **kwargs
        )
        self._bg       = bg
        self._fg       = fg
        self._hover_bg = hover_bg if hover_bg else self._darken(bg)
        self._command  = command
        self._enabled  = True

        self.bind('<Button-1>',  self._on_press)
        self.bind('<Enter>',     self._on_enter)
        self.bind('<Leave>',     self._on_leave)

    @staticmethod
    def _darken(hex_color: str) -> str:
        """Return a slightly darker version of a hex colour."""
        hex_color = hex_color.lstrip('#')
        r, g, b = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
        r = max(0, int(r * 0.88))
        g = max(0, int(g * 0.88))
        b = max(0, int(b * 0.88))
        return f'#{r:02x}{g:02x}{b:02x}'

    def _on_press(self, _event):
        if self._enabled and self._command:
            self._command()

    def _on_enter(self, _event):
        if self._enabled:
            self.config(bg=self._hover_bg)

    def _on_leave(self, _event):
        self.config(bg=self._bg)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.config(
            fg=self._fg if enabled else TEXT_TER,
            cursor='hand2' if enabled else 'arrow'
        )


def make_btn(parent, text, command, style='secondary', font=None, padx=14, pady=5):
    """
    Factory for MacButton with named styles:
      primary     — blue fill, white text
      secondary   — light fill, dark text
      destructive — red fill, white text
      warning     — orange fill, white text
      confirm     — green fill, white text
    """
    styles = {
        'primary':     (MAC_BLUE,    MAC_BLUE_H,   TEXT_WHITE),
        'secondary':   (BTN_FILL,    BTN_FILL_H,   TEXT_MAIN),
        'destructive': (MAC_RED,     MAC_RED_H,    TEXT_WHITE),
        'warning':     (MAC_ORANGE,  MAC_ORANGE_H, TEXT_WHITE),
        'confirm':     (MAC_GREEN,   MAC_GREEN_H,  TEXT_WHITE),
    }
    bg, hover, fg = styles.get(style, styles['secondary'])
    return MacButton(
        parent, text=text, command=command,
        bg=bg, fg=fg, hover_bg=hover,
        font=font or ('Helvetica Neue', 11),
        padx=padx, pady=pady
    )


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class NodeManagerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Bitcoin & Electrs Node Manager")
        self.root.configure(bg=BG)

        # ── Config + paths ───────────────────────────────────────────────────
        self.config_dir  = get_config_dir()
        self.config_path = self.config_dir / CONFIG_FILENAME

        if getattr(sys, 'frozen', False):
            default_data_root = Path.home() / "Documents" / APP_NAME
        else:
            default_data_root = Path(__file__).resolve().parent
        self._default_data_root = default_data_root

        self.sv_binaries_path     = tk.StringVar()
        self.sv_bitcoin_data_path = tk.StringVar()
        self.sv_electrs_data_path = tk.StringVar()
        self._load_config()

        # ── Process handles ──────────────────────────────────────────────────
        self.bitcoind_process = None
        self.electrs_process  = None

        # ── Queues ───────────────────────────────────────────────────────────
        self.bitcoin_queue = queue.Queue()
        self.electrs_queue = queue.Queue()

        # ── RPC ──────────────────────────────────────────────────────────────
        self.rpc_port = 8332

        # ── Status ───────────────────────────────────────────────────────────
        self.bitcoin_running      = False
        self.bitcoin_synced       = False
        self.electrs_running      = False
        self.electrs_synced       = False
        self.current_block_height = 0
        self.electrs_start_time   = None

        # ── Build UI then reveal ─────────────────────────────────────────────
        self.setup_gui()
        self.root.update_idletasks()
        # Centre on screen
        w, h = 1440, 960
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.deiconify()   # show now that layout is complete

        # ── Post-UI init ─────────────────────────────────────────────────────
        self.load_rpc_credentials()
        self._ensure_data_dirs()
        self.start_monitoring()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.log_to_terminal("bitcoin", "=== Bitcoin Node Manager started ===")
        self.log_to_terminal("bitcoin", f"Config   : {self.config_path}")
        self.log_to_terminal("bitcoin", f"Binaries : {self.binaries_path}")
        self.log_to_terminal("bitcoin", f"Data dir : {self.bitcoin_data_path}")
        self.log_to_terminal("electrs", "=== Electrs Node Manager started ===")
        self.log_to_terminal("electrs", f"Binaries : {self.binaries_path}")
        self.log_to_terminal("electrs", f"DB dir   : {self.electrs_data_path}")

    # ── Path properties ──────────────────────────────────────────────────────

    @property
    def binaries_path(self) -> Path:
        return Path(self.sv_binaries_path.get())

    @property
    def bitcoin_data_path(self) -> Path:
        return Path(self.sv_bitcoin_data_path.get())

    @property
    def electrs_data_path(self) -> Path:
        return Path(self.sv_electrs_data_path.get())

    # ── Config persistence ───────────────────────────────────────────────────

    def _load_config(self):
        dr = self._default_data_root
        defaults = {
            "binaries_path":     str(dr / "Binaries"),
            "bitcoin_data_path": str(dr / "BitcoinChain"),
            "electrs_data_path": str(dr / "ElectrsDB"),
        }
        cfg = {}
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    cfg = json.load(f)
            except Exception as e:
                print(f"Warning: could not read config ({e}), using defaults.")

        self.sv_binaries_path.set(    cfg.get("binaries_path",     defaults["binaries_path"]))
        self.sv_bitcoin_data_path.set(cfg.get("bitcoin_data_path", defaults["bitcoin_data_path"]))
        self.sv_electrs_data_path.set(cfg.get("electrs_data_path", defaults["electrs_data_path"]))

    def _save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump({
                    "binaries_path":     str(self.binaries_path),
                    "bitcoin_data_path": str(self.bitcoin_data_path),
                    "electrs_data_path": str(self.electrs_data_path),
                }, f, indent=2)
        except Exception as e:
            messagebox.showerror("Config Error", f"Could not save config:\n{e}")

    def _ensure_data_dirs(self):
        for p in (self.bitcoin_data_path, self.electrs_data_path):
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    # =========================================================================
    # GUI construction
    # =========================================================================

    def setup_gui(self):
        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = tk.Frame(self.root, bg=BAR_BG, height=56)
        toolbar.pack(fill=tk.X)
        toolbar.pack_propagate(False)

        # Block-height stat (left)
        stat_frame = tk.Frame(toolbar, bg=BAR_BG)
        stat_frame.pack(side=tk.LEFT, padx=20, fill=tk.Y)
        tk.Label(stat_frame, text="BLOCK HEIGHT",
                 font=('Helvetica Neue', 9), fg=TEXT_TER, bg=BAR_BG
                 ).pack(anchor='w', pady=(10, 0))
        self.block_height_label = tk.Label(
            stat_frame, text="Connecting…",
            font=('Helvetica Neue', 16, 'bold'), fg=TEXT_MAIN, bg=BAR_BG
        )
        self.block_height_label.pack(anchor='w')

        # Update Binaries button (right)
        make_btn(toolbar, "Update Binaries…", self.update_binaries,
                 style='secondary').pack(side=tk.RIGHT, padx=16, pady=12)

        # Hairline under toolbar
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill=tk.X)

        # ── Paths panel ───────────────────────────────────────────────────────
        self._build_paths_panel()

        # ── Node panels ───────────────────────────────────────────────────────
        main_container = tk.Frame(self.root, bg=BG)
        main_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        for side, frame_args, panel_args in [
            ('LEFT',  {'padx': (0, 8)}, ('Bitcoin', 'bitcoin', '#f7931a')),
            ('LEFT',  {'padx': (8, 0)}, ('Electrs', 'electrs', '#5856d6')),
        ]:
            card = tk.Frame(main_container, bg=PANEL_BG,
                            highlightbackground=BORDER, highlightthickness=1)
            card.pack(side=getattr(tk, side), fill=tk.BOTH, expand=True, **frame_args)
            self.build_node_panel(card, *panel_args)

        # ── Bottom bar ────────────────────────────────────────────────────────
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill=tk.X)
        bottom = tk.Frame(self.root, bg=BAR_BG, height=56)
        bottom.pack(fill=tk.X)
        bottom.pack_propagate(False)

        btn_row = tk.Frame(bottom, bg=BAR_BG)
        btn_row.pack(side=tk.LEFT, padx=16, fill=tk.Y)

        make_btn(btn_row, "Shutdown Bitcoind & Electrs", self.shutdown_both,
                 style='destructive').pack(side=tk.LEFT, pady=12, padx=(0, 8))
        make_btn(btn_row, "Shutdown Electrs Only", self.shutdown_electrs_only,
                 style='warning').pack(side=tk.LEFT, pady=12)

    # ── Paths panel ───────────────────────────────────────────────────────────

    def _build_paths_panel(self):
        outer = tk.Frame(self.root, bg=BAR_BG)
        outer.pack(fill=tk.X)

        header = tk.Frame(outer, bg=BAR_BG)
        header.pack(fill=tk.X, padx=20, pady=(10, 6))

        tk.Label(header, text="DIRECTORY PATHS",
                 font=('Helvetica Neue', 10), fg=TEXT_TER, bg=BAR_BG
                 ).pack(side=tk.LEFT)
        tk.Label(header, text=f"Config: {self.config_path}",
                 font=('Helvetica Neue', 9), fg=TEXT_TER, bg=BAR_BG
                 ).pack(side=tk.LEFT, padx=14)

        self._paths_visible = tk.BooleanVar(value=True)
        self._toggle_btn = make_btn(header, "Hide", self._toggle_paths_panel,
                                    style='secondary',
                                    font=('Helvetica Neue', 10), padx=10, pady=3)
        self._toggle_btn.pack(side=tk.RIGHT)

        self._paths_body = tk.Frame(outer, bg=BAR_BG)
        self._paths_body.pack(fill=tk.X, padx=20, pady=(0, 4))

        for label, sv, cmd in [
            ("Binaries Folder",        self.sv_binaries_path,     self._browse_binaries),
            ("Bitcoin Data Directory", self.sv_bitcoin_data_path, self._browse_bitcoin_data),
            ("Electrs DB Directory",   self.sv_electrs_data_path, self._browse_electrs_data),
        ]:
            self._build_path_row(self._paths_body, label, sv, cmd)

        save_row = tk.Frame(self._paths_body, bg=BAR_BG)
        save_row.pack(fill=tk.X, pady=(8, 8))

        tk.Label(save_row, text="Changes take effect on the next node launch.",
                 font=('Helvetica Neue', 10), fg=TEXT_TER, bg=BAR_BG
                 ).pack(side=tk.LEFT)
        make_btn(save_row, "Save Paths", self._on_save_paths,
                 style='confirm').pack(side=tk.RIGHT)

        self._paths_divider = tk.Frame(self.root, bg=BORDER, height=1)
        self._paths_divider.pack(fill=tk.X)

    def _build_path_row(self, parent, label_text, string_var, browse_cmd):
        row = tk.Frame(parent, bg=BAR_BG)
        row.pack(fill=tk.X, pady=3)

        tk.Label(row, text=label_text,
                 font=('Helvetica Neue', 11), fg=TEXT_SEC, bg=BAR_BG,
                 width=22, anchor='w'
                 ).pack(side=tk.LEFT)

        entry = tk.Entry(
            row, textvariable=string_var,
            font=('Menlo', 10),
            bg=PATH_BOX_BG, fg=TEXT_MAIN,
            insertbackground=MAC_BLUE,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightcolor=MAC_BLUE,
            highlightbackground=BORDER
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6), ipady=4)

        make_btn(row, "Browse…", browse_cmd, style='secondary',
                 font=('Helvetica Neue', 10), padx=10, pady=3
                 ).pack(side=tk.LEFT)

        dot = tk.Label(row, text="●", font=('Helvetica Neue', 13),
                       bg=BAR_BG, width=2)
        dot.pack(side=tk.LEFT, padx=(6, 0))

        def _refresh(*_):
            dot.config(fg=IND_GREEN if Path(string_var.get()).exists() else IND_OFF)

        string_var.trace_add("write", _refresh)
        _refresh()

    def _toggle_paths_panel(self):
        if self._paths_visible.get():
            self._paths_body.pack_forget()
            self._paths_divider.pack_forget()
            self._toggle_btn.config(text="Show")
            self._paths_visible.set(False)
        else:
            self._paths_body.pack(fill=tk.X, padx=20, pady=(0, 4))
            self._paths_divider.pack(fill=tk.X)
            self._toggle_btn.config(text="Hide")
            self._paths_visible.set(True)

    def _browse_binaries(self):
        d = filedialog.askdirectory(title="Select Binaries Folder",
                                    initialdir=self.sv_binaries_path.get() or str(Path.home()))
        if d:
            self.sv_binaries_path.set(d)

    def _browse_bitcoin_data(self):
        d = filedialog.askdirectory(title="Select Bitcoin Data Directory",
                                    initialdir=self.sv_bitcoin_data_path.get() or str(Path.home()))
        if d:
            self.sv_bitcoin_data_path.set(d)

    def _browse_electrs_data(self):
        d = filedialog.askdirectory(title="Select Electrs DB Directory",
                                    initialdir=self.sv_electrs_data_path.get() or str(Path.home()))
        if d:
            self.sv_electrs_data_path.set(d)

    def _on_save_paths(self):
        errors = []
        for label, sv in [
            ("Binaries Folder",        self.sv_binaries_path),
            ("Bitcoin Data Directory", self.sv_bitcoin_data_path),
            ("Electrs DB Directory",   self.sv_electrs_data_path),
        ]:
            raw = sv.get().strip()
            if not raw:
                errors.append(f"• {label} is empty.")
            else:
                sv.set(raw)

        if errors:
            messagebox.showerror("Validation Error",
                                 "Please fix the following:\n\n" + "\n".join(errors))
            return

        self._save_config()
        self._ensure_data_dirs()
        self.load_rpc_credentials()
        self.log_to_terminal("bitcoin", "--- Paths updated ---")
        self.log_to_terminal("bitcoin", f"Binaries : {self.binaries_path}")
        self.log_to_terminal("bitcoin", f"Data dir : {self.bitcoin_data_path}")
        self.log_to_terminal("electrs", "--- Paths updated ---")
        self.log_to_terminal("electrs", f"DB dir   : {self.electrs_data_path}")
        messagebox.showinfo("Paths Saved",
                            f"Paths saved to:\n{self.config_path}\n\n"
                            "Changes take effect on the next node launch.")

    # ── Node panel ────────────────────────────────────────────────────────────

    def build_node_panel(self, parent, title, node_type, accent):
        # 3 px accent top bar
        tk.Frame(parent, bg=accent, height=3).pack(fill=tk.X)

        # Header row: title + Launch button
        hrow = tk.Frame(parent, bg=PANEL_BG)
        hrow.pack(fill=tk.X, padx=20, pady=(14, 10))

        tk.Label(hrow, text=title,
                 font=('Helvetica Neue', 20, 'bold'),
                 fg=TEXT_MAIN, bg=PANEL_BG, anchor='w'
                 ).pack(side=tk.LEFT)

        # Launch button uses accent colour — implemented as MacButton for reliable colours
        MacButton(
            hrow, text="Launch",
            command=lambda: self.launch_node(node_type),
            bg=accent, fg=TEXT_WHITE, hover_bg=None,   # hover computed automatically
            font=('Helvetica Neue', 12, 'bold'),
            padx=18, pady=5
        ).pack(side=tk.RIGHT)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill=tk.X)

        # Status indicators — horizontal traffic-light row
        ind_frame = tk.Frame(parent, bg=PANEL_BG)
        ind_frame.pack(fill=tk.X, padx=20, pady=12)

        indicators = {}
        for label_text, attr in [
            ("Running",  f"{node_type}_running_indicator"),
            ("Synced",   f"{node_type}_synced_indicator"),
            ("Ready",    f"{node_type}_ready_indicator"),
        ]:
            badge = tk.Frame(ind_frame, bg=PANEL_BG)
            badge.pack(side=tk.LEFT, padx=(0, 24))

            c = tk.Canvas(badge, width=12, height=12,
                          bg=PANEL_BG, highlightthickness=0)
            c.pack(side=tk.LEFT, padx=(0, 6))
            dot = c.create_oval(1, 1, 11, 11, fill=IND_OFF, outline='')

            tk.Label(badge, text=label_text,
                     font=('Helvetica Neue', 11), fg=TEXT_SEC, bg=PANEL_BG
                     ).pack(side=tk.LEFT)

            indicators[attr] = (c, dot)

        if node_type == "bitcoin":
            self.bitcoin_running_indicator = indicators["bitcoin_running_indicator"]
            self.bitcoin_synced_indicator  = indicators["bitcoin_synced_indicator"]
            self.bitcoin_ready_indicator   = indicators["bitcoin_ready_indicator"]
        else:
            self.electrs_running_indicator = indicators["electrs_running_indicator"]
            self.electrs_synced_indicator  = indicators["electrs_synced_indicator"]
            self.electrs_ready_indicator   = indicators["electrs_ready_indicator"]

        tk.Frame(parent, bg=BORDER, height=1).pack(fill=tk.X)

        # Terminal
        terminal = scrolledtext.ScrolledText(
            parent,
            font=('Menlo', 10),
            bg=TERM_BG, fg=TERM_FG,
            insertbackground=TERM_FG,
            selectbackground='#264f78',
            state=tk.DISABLED,
            wrap=tk.WORD,
            relief=tk.FLAT,
            padx=10, pady=8,
            borderwidth=0
        )
        terminal.pack(fill=tk.BOTH, expand=True)

        if node_type == "bitcoin":
            self.bitcoin_terminal = terminal
        else:
            self.electrs_terminal = terminal

    # =========================================================================
    # bitcoin.conf + cookie auth
    # =========================================================================

    def load_rpc_credentials(self):
        conf_path = self.bitcoin_data_path / "bitcoin.conf"
        if not conf_path.exists():
            self.create_default_bitcoin_conf()
            return

        self.rpc_port = 8332
        try:
            with open(conf_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('rpcport='):
                        try:
                            self.rpc_port = int(line.split('=', 1)[1].strip())
                        except ValueError:
                            pass
        except Exception as e:
            self.log_to_terminal("bitcoin", f"Error reading bitcoin.conf: {e}")

    def _get_rpc_auth(self):
        """
        Prefer the .cookie file bitcoind writes on every start.
        Fall back to rpcuser/rpcpassword from bitcoin.conf only when no cookie
        is found (i.e. the user has explicitly disabled cookie auth).
        """
        for cookie_path in [
            self.bitcoin_data_path / ".cookie",
            self.bitcoin_data_path / "mainnet" / ".cookie",
        ]:
            if cookie_path.exists():
                try:
                    content = cookie_path.read_text().strip()
                    if ':' in content:
                        return tuple(content.split(':', 1))
                except Exception:
                    pass

        # Fallback: static credentials from bitcoin.conf
        user = password = None
        conf_path = self.bitcoin_data_path / "bitcoin.conf"
        if conf_path.exists():
            try:
                with open(conf_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('rpcuser='):
                            user = line.split('=', 1)[1].strip()
                        elif line.startswith('rpcpassword='):
                            password = line.split('=', 1)[1].strip()
            except Exception:
                pass
        return (user or "bitcoin"), (password or "bitcoinrpc")

    def create_default_bitcoin_conf(self):
        try:
            self.bitcoin_data_path.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
        with open(self.bitcoin_data_path / "bitcoin.conf", 'w') as f:
            f.write(
                "# Bitcoin Core — auto-generated by Node Manager\n"
                "server=1\n"
                "txindex=1\n"
                "rpcport=8332\n"
                "rpcallowip=127.0.0.1\n"
                "# Cookie authentication is active by default.\n"
            )
        self.rpc_port = 8332
        self.log_to_terminal("bitcoin", "Created default bitcoin.conf")

    # =========================================================================
    # Launch / run nodes
    # =========================================================================

    def launch_node(self, node_type):
        if node_type == "bitcoin":
            if self.bitcoind_process and self.bitcoind_process.poll() is None:
                messagebox.showinfo("Info", "Bitcoin is already running.")
                return

            bitcoind_path = self.binaries_path / "bitcoind"
            if not bitcoind_path.exists():
                messagebox.showerror("Binary Not Found",
                                     f"bitcoind not found at:\n{bitcoind_path}\n\n"
                                     "Update the Binaries Folder path above.")
                return

            self.bitcoin_data_path.mkdir(parents=True, exist_ok=True)
            cmd = [str(bitcoind_path), f"-datadir={self.bitcoin_data_path}",
                   "-printtoconsole"]
            threading.Thread(target=self.run_bitcoind, args=(cmd,), daemon=True).start()

        elif node_type == "electrs":
            if self.electrs_process and self.electrs_process.poll() is None:
                messagebox.showinfo("Info", "Electrs is already running.")
                return

            if not self.bitcoin_running:
                messagebox.showwarning("Bitcoin Not Running",
                                       "Bitcoin must be running before starting Electrs.\n\n"
                                       "Launch Bitcoin first and wait for the Running indicator.")
                return

            electrs_path = self.binaries_path / "electrs"
            if not electrs_path.exists():
                messagebox.showerror("Binary Not Found",
                                     f"electrs not found at:\n{electrs_path}\n\n"
                                     "Update the Binaries Folder path above.")
                return

            self.electrs_data_path.mkdir(parents=True, exist_ok=True)
            cmd = [
                str(electrs_path),
                "--network",           "bitcoin",
                "--daemon-dir",        str(self.bitcoin_data_path),
                "--db-dir",            str(self.electrs_data_path),
                "--electrum-rpc-addr", "127.0.0.1:50001",
            ]
            self.electrs_start_time = time.time()
            threading.Thread(target=self.run_electrs, args=(cmd,), daemon=True).start()

    def run_bitcoind(self, cmd):
        try:
            self.log_to_terminal("bitcoin", f"Starting: {' '.join(cmd)}")
            self.bitcoind_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            self.root.after(0, self._set_bitcoin_running, True)
            for line in iter(self.bitcoind_process.stdout.readline, ''):
                if line:
                    self.bitcoin_queue.put(line.rstrip())
            self.bitcoind_process.wait()
            self.root.after(0, self._set_bitcoin_running, False)
            self.log_to_terminal("bitcoin", "bitcoind stopped.")
        except Exception as e:
            self.log_to_terminal("bitcoin", f"Error: {e}")
            self.root.after(0, self._set_bitcoin_running, False)

    def run_electrs(self, cmd):
        try:
            self.log_to_terminal("electrs", f"Starting: {' '.join(cmd)}")
            self.electrs_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            self.root.after(0, self._set_electrs_running, True)
            for line in iter(self.electrs_process.stdout.readline, ''):
                if line:
                    stripped = line.rstrip()
                    self.electrs_queue.put(stripped)
                    self._check_electrs_sync_line(stripped)
            self.electrs_process.wait()
            self.root.after(0, self._set_electrs_running, False)
            self.log_to_terminal("electrs", "electrs stopped.")
        except Exception as e:
            self.log_to_terminal("electrs", f"Error: {e}")
            self.root.after(0, self._set_electrs_running, False)

    def _check_electrs_sync_line(self, line):
        lower = line.lower()
        if any(p in lower for p in [
            "finished full compaction",
            "electrs running",
            "waiting for new block",
        ]):
            self.root.after(0, self._set_electrs_synced, True)

    # ── Thread-safe state setters ─────────────────────────────────────────────

    def _set_bitcoin_running(self, value: bool):
        self.bitcoin_running = value
        if not value:
            self.bitcoin_synced       = False
            self.current_block_height = 0
            self.update_block_height_display()
        self.update_indicators()

    def _set_electrs_running(self, value: bool):
        self.electrs_running = value
        if not value:
            self.electrs_synced = False
        self.update_indicators()

    def _set_electrs_synced(self, value: bool):
        self.electrs_synced = value
        self.update_indicators()

    # ── Terminal ──────────────────────────────────────────────────────────────

    def log_to_terminal(self, terminal_type, message):
        if terminal_type == "bitcoin":
            self.bitcoin_queue.put(message)
        else:
            self.electrs_queue.put(message)

    def update_terminals(self):
        for q, terminal in [
            (self.bitcoin_queue, self.bitcoin_terminal),
            (self.electrs_queue, self.electrs_terminal),
        ]:
            try:
                while True:
                    msg = q.get_nowait()
                    terminal.config(state=tk.NORMAL)
                    terminal.insert(tk.END, msg + "\n")
                    terminal.see(tk.END)
                    terminal.config(state=tk.DISABLED)
            except queue.Empty:
                pass
        self.root.after(100, self.update_terminals)

    # ── Indicators ───────────────────────────────────────────────────────────

    def update_indicators(self):
        self._set_dot(self.bitcoin_running_indicator, self.bitcoin_running)
        self._set_dot(self.bitcoin_synced_indicator,  self.bitcoin_synced)
        self._set_dot(self.bitcoin_ready_indicator,   self.bitcoin_running and self.bitcoin_synced)
        self._set_dot(self.electrs_running_indicator, self.electrs_running)
        self._set_dot(self.electrs_synced_indicator,  self.electrs_synced)
        self._set_dot(self.electrs_ready_indicator,   self.electrs_running and self.electrs_synced)

    def _set_dot(self, indicator, active: bool):
        canvas, dot = indicator
        canvas.itemconfig(dot, fill=IND_GREEN if active else IND_OFF)

    def update_block_height_display(self):
        if self.current_block_height > 0:
            self.block_height_label.config(text=f"{self.current_block_height:,}")
        else:
            self.block_height_label.config(text="Connecting…")

    # ── Monitoring ────────────────────────────────────────────────────────────

    def start_monitoring(self):
        self.update_terminals()
        threading.Thread(target=self.monitor_bitcoin_rpc,     daemon=True).start()
        threading.Thread(target=self.monitor_electrs_process, daemon=True).start()

    def monitor_bitcoin_rpc(self):
        while True:
            try:
                if self.bitcoin_running:
                    info = self.rpc_call("getblockchaininfo")
                    if info:
                        blocks   = info.get("blocks",               0)
                        headers  = info.get("headers",              0)
                        progress = info.get("verificationprogress", 0.0)

                        def _update(b=blocks, h=headers, p=progress):
                            self.current_block_height = b
                            self.update_block_height_display()
                            self.bitcoin_synced = (h > 0) and (b >= h - 1) and (p > 0.9999)
                            self.update_indicators()

                        self.root.after(0, _update)
                time.sleep(5)
            except Exception:
                time.sleep(10)

    def monitor_electrs_process(self):
        while True:
            try:
                if self.electrs_process is not None:
                    if self.electrs_process.poll() is not None and self.electrs_running:
                        self.root.after(0, self._set_electrs_running, False)
                time.sleep(5)
            except Exception:
                time.sleep(10)

    # ── RPC ───────────────────────────────────────────────────────────────────

    def rpc_call(self, method, params=None):
        user, password = self._get_rpc_auth()
        if not user or not password:
            return None
        try:
            r = requests.post(
                f"http://127.0.0.1:{self.rpc_port}/",
                json={"jsonrpc": "1.0", "id": "nm", "method": method, "params": params or []},
                headers={'content-type': 'application/json'},
                auth=(user, password),
                timeout=5
            )
            if r.status_code == 200:
                return r.json().get('result')
        except requests.exceptions.RequestException:
            pass
        return None

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown_both(self):
        if not messagebox.askyesno("Confirm", "Shutdown both Bitcoin and Electrs?"):
            return
        self._terminate_electrs()
        if self.bitcoin_running:
            self.log_to_terminal("bitcoin", "Sending stop via RPC…")
            threading.Thread(target=self._stop_bitcoind_rpc, daemon=True).start()

    def shutdown_electrs_only(self):
        if not messagebox.askyesno("Confirm", "Shutdown Electrs?"):
            return
        self._terminate_electrs()

    def _terminate_electrs(self):
        if self.electrs_process and self.electrs_process.poll() is None:
            self.log_to_terminal("electrs", "Terminating electrs…")
            self.electrs_process.terminate()
            try:
                self.electrs_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.electrs_process.kill()
            self.root.after(0, self._set_electrs_running, False)

    def _stop_bitcoind_rpc(self):
        self.rpc_call("stop")
        if self.bitcoind_process:
            try:
                self.bitcoind_process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.log_to_terminal("bitcoin", "bitcoind did not stop in time — killing.")
                self.bitcoind_process.kill()
        self.root.after(0, self._set_bitcoin_running, False)

    # ── Binary update ─────────────────────────────────────────────────────────

    def update_binaries(self):
        downloads_path = Path.home() / "Downloads" / "bitcoin_builds"
        if not downloads_path.exists():
            bitforge = Path("/Applications/BitForge.app")
            if bitforge.exists():
                if messagebox.askyesno("BitForge Found",
                                       "No bitcoin_builds folder found.\n\nOpen BitForge.app?"):
                    subprocess.Popen(["open", str(bitforge)])
            else:
                messagebox.showinfo("BitForge Not Found",
                                    "Download BitForge from:\n"
                                    "https://github.com/csd113/BitForge-Python")
            return

        binaries_src = downloads_path / "binaries"
        if not binaries_src.exists():
            messagebox.showerror("Error", f"No 'binaries' sub-folder in:\n{downloads_path}")
            return

        btc_ver = self._find_latest_version(binaries_src, "bitcoin")
        etr_ver = self._find_latest_version(binaries_src, "electrs")

        if not btc_ver and not etr_ver:
            messagebox.showinfo("Nothing Found", "No bitcoin-X.Y.Z or electrs-X.Y.Z folders found.")
            return

        self.binaries_path.mkdir(parents=True, exist_ok=True)
        updated = []
        if btc_ver:
            if self._copy_binaries(binaries_src / btc_ver,
                                   ["bitcoind", "bitcoin-cli", "bitcoin-tx", "bitcoin-util"]):
                updated.append(f"Bitcoin ({btc_ver})")
        if etr_ver:
            if self._copy_binaries(binaries_src / etr_ver, ["electrs"]):
                updated.append(f"Electrs ({etr_ver})")

        if updated:
            messagebox.showinfo("Success", "Updated:\n" + "\n".join(updated))
        else:
            messagebox.showwarning("Warning", "No binaries were updated.")

    def _find_latest_version(self, path, prefix):
        pattern  = re.compile(rf"^{re.escape(prefix)}-(\d+(?:\.\d+)*)$")
        versions = []
        try:
            for item in path.iterdir():
                if item.is_dir():
                    m = pattern.match(item.name)
                    if m:
                        versions.append(
                            (tuple(int(x) for x in m.group(1).split('.')), item.name))
        except OSError:
            return None
        return versions and sorted(versions, reverse=True)[0][1]

    def _copy_binaries(self, src_dir, names):
        copied = False
        for name in names:
            src = src_dir / name
            if src.exists():
                dst = self.binaries_path / name
                try:
                    shutil.copy2(src, dst)
                    os.chmod(dst, 0o755)
                    copied = True
                    self.log_to_terminal("bitcoin", f"Copied {name} → {dst}")
                except Exception as e:
                    messagebox.showerror("Copy Error", f"Failed to copy {name}:\n{e}")
        return copied

    # ── Window close ──────────────────────────────────────────────────────────

    def on_closing(self):
        if messagebox.askyesno("Quit", "Shutdown nodes and exit?"):
            self._terminate_electrs()
            if self.bitcoin_running:
                self.rpc_call("stop")
                if self.bitcoind_process:
                    try:
                        self.bitcoind_process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        self.bitcoind_process.kill()
            self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _acquire_instance_lock():
    """
    Try to acquire an exclusive lock on a temp file.
    Returns the open file object (lock held) or None (lock not available).
    The caller must keep the file object alive for the lock to persist.
    """
    if not _HAVE_FCNTL:
        return None  # non-Unix — skip the guard

    lock_path = Path("/tmp") / f"{APP_NAME}.lock"
    try:
        fh = open(lock_path, 'w')
        _fcntl.flock(fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh          # caller holds this to keep lock alive
    except OSError:
        return None        # another instance already holds the lock


def main():
    # ── Single-instance guard ────────────────────────────────────────────────
    # Acquire the lock BEFORE creating any Tk window.  If we can't get it,
    # a duplicate instance is already running — exit immediately and silently.
    _lock_fh = _acquire_instance_lock()
    if _lock_fh is None and _HAVE_FCNTL:
        # Lock unavailable — duplicate launch, just quit
        sys.exit(0)

    # ── Also call freeze_support for PyInstaller / multiprocessing safety ────
    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass

    # ── Create and show the window ───────────────────────────────────────────
    root = tk.Tk()
    root.withdraw()   # hide until fully built — eliminates the empty-window flash
    try:
        NodeManagerGUI(root)
        root.mainloop()
    except Exception as e:
        msg = f"Startup error:\n\n{e}\n\n{traceback.format_exc()}"
        print(msg, file=sys.stderr)
        try:
            messagebox.showerror("Startup Error", msg)
        except Exception:
            pass
        sys.exit(1)
    finally:
        # Release the lock on clean exit so the app can be relaunched
        if _lock_fh is not None:
            try:
                _fcntl.flock(_lock_fh, _fcntl.LOCK_UN)
                _lock_fh.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
