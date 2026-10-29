"""ghostkey :: activity telemetry + telegram relay (minimal black/grey).

Tracks the foreground window (process + title), open/close transitions
and time per application. Writes digests to a local log and sends them
to Telegram if a bot token + chat id are configured.

- No keystroke content.
- No auto-start, no OS hooks.
- Token/chat supplied by user (source constants or TELEGRAM tab).

Data dir: ~/.ghostkey
"""

import ctypes
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, scrolledtext, messagebox, filedialog

try:
    from ctypes import wintypes
except ImportError:
    wintypes = None

try:
    import requests
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False

# ---------- FILL THESE IN (or use the TELEGRAM tab in the app) ----------
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""
# -----------------------------------------------------------------------

APP_NAME = "ghostkey"
DATA_DIR = Path.home() / ".ghostkey"
CONFIG_FILE = DATA_DIR / "config.json"
EVENTS_FILE = DATA_DIR / "events.log"
DIGESTS_FILE = DATA_DIR / "digests.log"
BUFFER_FILE = DATA_DIR / "buffer.txt"

DEFAULT_CONFIG = {
    "interval": 30,
    "poll": 1.0,
    "start_on_launch": False,
    "geometry": "",
    "bot_token": TELEGRAM_TOKEN,
    "chat_id": TELEGRAM_CHAT_ID,
}

FONT_FAMILY = "Consolas"

# ---- Ghostkey dark telemetry palette (cyan accent) ----
T = {
    "bg":         "#080d11",
    "panel":      "#0e151b",
    "panel2":     "#172129",
    "panel3":     "#202d36",
    "border":     "#2a3b46",
    "border2":    "#3b5361",
    "fg":         "#e3edf5",
    "fg_mid":     "#a4b7c7",
    "dim":        "#8298aa",
    "dimmer":     "#536777",
    "accent":     "#35e0e8",
    "accent2":    "#00b9c7",
    "green":      "#48df88",
    "warn":       "#ffc857",
    "red":        "#ff7777",
    "font":       ("Consolas", 10),
    "font_s":     ("Consolas", 9),
    "font_xs":    ("Consolas", 8),
    "font_title": ("Consolas", 11, "bold"),
    "font_stat":  ("Consolas", 16, "bold"),
}

def pick_fonts(root):
    global FONT_FAMILY
    try:
        available = set(tkfont.families(root))
        for name in ("Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas"):
            if name in available:
                FONT_FAMILY = name
                break
    except Exception:
        pass
    T["font"] = (FONT_FAMILY, 10)
    T["font_s"] = (FONT_FAMILY, 9)
    T["font_xs"] = (FONT_FAMILY, 8)
    T["font_title"] = (FONT_FAMILY, 11, "bold")
    T["font_stat"] = (FONT_FAMILY, 12, "bold")


def ensure_dir():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def load_config():
    ensure_dir()
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    ensure_dir()
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def fmt_secs(sec):
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def clean_text(value, width=None):
    text = " ".join(str(value or "").split())
    if width and len(text) > width:
        text = text[: width - 1] + "…"
    return text


def dedupe_join(items, limit=12):
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    if not seen:
        return "(none)"
    if len(seen) > limit:
        return ", ".join(seen[:limit]) + f" (+{len(seen) - limit})"
    return ", ".join(seen)


def get_foreground():
    if sys.platform != "win32" or wintypes is None:
        return "", ""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = (buf.value or "").strip()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = ""
        for access in (0x1000, 0x0400):
            handle = kernel32.OpenProcess(access, False, pid)
            if handle:
                pbuf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(handle, 0, pbuf, ctypes.byref(size)):
                    proc = Path(pbuf.value).name
                kernel32.CloseHandle(handle)
                break
        return title, proc
    except Exception:
        return "", ""


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def send_telegram(token, chat_id, message, timeout=15):
    if not HAVE_REQUESTS:
        return False, "requests not installed (pip install requests)"
    if not token or not chat_id:
        return False, "no token/chat configured"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in [message[i:i + 4000] for i in range(0, len(message), 4000)]:
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": chunk},
                              timeout=timeout)
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:
            return False, str(exc)
    return True, ""


class GhostkeyApp:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        pick_fonts(root)

        self.root.title("ghostkey")
        geometry = self.cfg.get("geometry") or "1440x900"
        try:
            self.root.geometry(geometry)
        except tk.TclError:
            self.root.geometry("1440x900")
        self.root.minsize(1100, 720)
        self.root.configure(bg=T["bg"])

        self.session_id = f"0x{int(time.time()) & 0xFFFFFF:06X}"
        self.running = False
        self.worker = None
        self.lock = threading.RLock()
        self.start_time = None

        self.current = None
        self.current_since = None
        self.app_seconds = {}
        self.app_titles = {}
        self.last_tick = None

        self.opened = []
        self.closed = []
        self.events_session = 0
        self.events_window = 0
        self.digests = 0
        self.tg_ok = 0
        self.tg_fail = 0
        self.last_tg_ok = None
        self.window_start = None
        self.next_digest = None
        self.last_digest = ""
        self.last_digest_time = None

        self.sort_key = "time"
        self.sort_desc = True
        self._trace_data = []
        self._blink_on = True

        self._apply_theme()
        self._build_ui()
        self._bind_shortcuts()
        self._heartbeat_line()
        self._trace("[init] ghostkey online", "info")
        if not HAVE_REQUESTS:
            self._trace("[warn] requests not installed · telegram disabled", "err")
        if self.cfg.get("bot_token") and self.cfg.get("chat_id"):
            self._trace(f"[tg] relay armed · chat {self.cfg['chat_id']}", "info")
        else:
            self._trace("[tg] no credentials · local only", "info")
        self.root.after(480, self._blink)
        self._refresh_stats()
        self._refresh_table()

        if self.cfg.get("start_on_launch"):
            self.root.after(800, self.start)

    # ------------------------------------------------------------ theme
    def _apply_theme(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass

        s.configure(".", background=T["bg"], foreground=T["fg"],
                    fieldbackground=T["panel"], font=T["font"])
        s.configure("TFrame", background=T["bg"])
        s.configure("TLabel", background=T["bg"], foreground=T["fg"])
        s.configure("Dim.TLabel", background=T["bg"], foreground=T["dim"])

        s.configure("TButton", background=T["panel2"], foreground=T["fg"],
                    bordercolor=T["border"], lightcolor=T["border"],
                    darkcolor=T["border"], borderwidth=1, relief="flat",
                    padding=(10, 5), font=T["font_s"])
        s.map("TButton",
              background=[("active", T["panel3"]), ("disabled", T["bg"])],
              foreground=[("active", T["accent"]), ("disabled", T["dimmer"])],
              bordercolor=[("active", T["border2"])])

        s.configure("Accent.TButton", background=T["accent2"], foreground="#061216",
                    bordercolor=T["accent"], lightcolor=T["accent"],
                    darkcolor=T["accent2"], borderwidth=1, relief="flat",
                    padding=(14, 7), font=T["font_s"])
        s.map("Accent.TButton",
              background=[("active", T["accent"]), ("disabled", T["panel2"])],
              foreground=[("active", "#061216"), ("disabled", T["dimmer"])])

        s.configure("Danger.TButton", background=T["panel2"], foreground=T["fg_mid"],
                    bordercolor=T["border"], lightcolor=T["border"],
                    darkcolor=T["border"], borderwidth=1, relief="flat",
                    padding=(10, 5), font=T["font_s"])
        s.map("Danger.TButton",
              background=[("active", T["panel3"])],
              foreground=[("active", T["accent"])])

        s.configure("TNotebook", background=T["bg"], borderwidth=0, tabmargins=(0, 8, 0, 0))
        s.configure("TNotebook.Tab", background=T["bg"], foreground=T["dim"],
                    padding=(18, 9), borderwidth=0, font=T["font_s"])
        s.map("TNotebook.Tab",
              background=[("selected", T["panel"]), ("active", T["panel2"])],
              foreground=[("selected", T["accent"]), ("active", T["fg"])],
              expand=[("selected", (0, 0, 0, 0))])

        s.configure("TEntry", fieldbackground=T["panel"], foreground=T["fg"],
                    insertcolor=T["accent"], bordercolor=T["border"],
                    lightcolor=T["border"], darkcolor=T["border"], padding=6)
        s.map("TEntry", bordercolor=[("focus", T["border2"])])

        s.configure("TSpinbox", fieldbackground=T["panel"], foreground=T["fg"],
                    background=T["panel"], arrowcolor=T["dim"],
                    bordercolor=T["border"], padding=4)
        s.map("TSpinbox", bordercolor=[("focus", T["border2"])])

        s.configure("TCheckbutton", background=T["bg"], foreground=T["fg"],
                    focuscolor=T["bg"], font=T["font_s"])
        s.map("TCheckbutton",
              background=[("active", T["bg"])],
              foreground=[("active", T["accent"])],
              indicatorcolor=[("selected", T["accent"]), ("!selected", T["panel"])])

        s.configure("Treeview", background=T["panel"], fieldbackground=T["panel"],
                    foreground=T["fg"], rowheight=29, borderwidth=0,
                    font=T["font_s"])
        s.configure("Treeview.Heading", background=T["panel2"], foreground=T["fg_mid"],
                    font=T["font_s"], relief="flat", borderwidth=0, padding=(6, 5))
        s.map("Treeview",
              background=[("selected", T["panel3"])],
              foreground=[("selected", T["accent"])])
        s.map("Treeview.Heading", background=[("active", T["panel3"])])

        s.configure("Vertical.TScrollbar", background=T["panel2"], troughcolor=T["bg"],
                    bordercolor=T["border"], arrowcolor=T["dim"])
        s.configure("TSeparator", background=T["border"])

    # ------------------------------------------------------------ ui
    def _build_ui(self):
        header = tk.Frame(self.root, bg=T["bg"], height=56)
        header.pack(fill="x", padx=18, pady=(14, 0))
        header.pack_propagate(False)

        left = tk.Frame(header, bg=T["bg"])
        left.pack(side="left", fill="y")
        brand = tk.Frame(left, bg=T["bg"])
        brand.pack(anchor="w")
        tk.Label(brand, text="♧", bg=T["bg"], fg=T["accent"],
                 font=(FONT_FAMILY, 25, "bold")).pack(side="left", padx=(0, 10))
        brand_text = tk.Frame(brand, bg=T["bg"])
        brand_text.pack(side="left", pady=(0, 1))
        tk.Label(brand_text, text="ghostkey", bg=T["bg"], fg=T["fg"],
                 font=(FONT_FAMILY, 21, "bold")).pack(anchor="w")
        tk.Label(brand_text, text="activity telemetry", bg=T["bg"], fg=T["dim"],
                 font=T["font_xs"]).pack(anchor="w")

        right = tk.Frame(header, bg=T["bg"])
        right.pack(side="right", fill="y")
        self.status_lbl = tk.Label(right, text="● IDLE", bg=T["bg"], fg=T["fg_mid"],
                                   font=(FONT_FAMILY, 9))
        self.status_lbl.pack(side="right", pady=14)

        self._build_stats()
        self._build_active_strip()
        self._build_controls()

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=24, pady=(12, 0))
        self._tab_trace()
        self._tab_output()
        self._tab_telegram()
        self._tab_settings()

        footer = tk.Frame(self.root, bg=T["bg"], height=24)
        footer.pack(fill="x", padx=24, pady=(2, 10))
        footer.pack_propagate(False)
        tk.Label(footer, text="f9 start/stop   f5 flush", bg=T["bg"], fg=T["dimmer"],
                 font=T["font_xs"]).pack(side="left", pady=4)
        tk.Label(footer, text=str(DATA_DIR), bg=T["bg"], fg=T["dimmer"],
                 font=T["font_xs"]).pack(side="right", pady=4)

    def _build_stats(self):
        row = tk.Frame(self.root, bg=T["bg"])
        row.pack(fill="x", padx=24, pady=(12, 0))
        self.stat_values = {}
        cells = [
            ("uptime", "◷", "UPTIME"),
            ("apps", "▦", "APPS"),
            ("events", "▤", "EVENTS"),
            ("next", "◴", "NEXT DIGEST"),
            ("tg", "➤", "TELEGRAM"),
        ]
        for key, icon, label in cells:
            card = tk.Frame(row, bg=T["panel"], highlightbackground=T["border"],
                            highlightthickness=1, height=76)
            card.pack(side="left", fill="both", expand=True, padx=(0, 12))
            card.pack_propagate(False)
            icon_lbl = tk.Label(card, text=icon, bg=T["panel"], fg=T["accent"],
                                font=(FONT_FAMILY, 22, "bold"), width=3)
            icon_lbl.pack(side="left", padx=(8, 2))
            body = tk.Frame(card, bg=T["panel"])
            body.pack(side="left", fill="both", expand=True, pady=10)
            tk.Label(body, text=label, bg=T["panel"], fg=T["dim"],
                     font=T["font_xs"]).pack(anchor="w")
            value = tk.Label(body, text="—", bg=T["panel"], fg=T["accent"],
                             font=T["font_stat"])
            value.pack(anchor="w", pady=(2, 0))
            self.stat_values[key] = value

    def _build_active_strip(self):
        strip = tk.Frame(self.root, bg=T["panel"], highlightbackground=T["border"],
                         highlightthickness=1)
        strip.pack(fill="x", padx=24, pady=(12, 0))
        self.active_lbl = tk.Label(strip, text="●  ACTIVE   |   Session idle", bg=T["panel"],
                                   fg=T["green"], font=T["font_s"], anchor="w")
        self.active_lbl.pack(side="left", padx=10, pady=5)
        self.last_lbl = tk.Label(strip, text="last digest —", bg=T["panel"],
                                 fg=T["dimmer"], font=T["font_xs"])
        self.last_lbl.pack(side="right", padx=10)

    def _build_controls(self):
        bar = tk.Frame(self.root, bg=T["bg"])
        bar.pack(fill="x", padx=24, pady=(12, 0))
        self.start_btn = ttk.Button(bar, text="▶  Start", style="Accent.TButton",
                                    command=self.start)
        self.start_btn.pack(side="left", padx=(0, 4))
        self.stop_btn = ttk.Button(bar, text="■  Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.flush_btn = ttk.Button(bar, text="➤  Flush + Send", command=self.flush_now,
                                    state="disabled")
        self.flush_btn.pack(side="left", padx=4)
        ttk.Button(bar, text="↗  Test TG", command=self.test_telegram).pack(side="left", padx=4)
        ttk.Button(bar, text="⇩  Export", command=self.export_digest).pack(side="left", padx=4)
        ttk.Button(bar, text="▤  Clear", style="Danger.TButton",
                   command=self.clear_state).pack(side="left", padx=4)
        ttk.Button(bar, text="▣  Open Log", command=self.open_digest_log).pack(
            side="right", padx=(4, 0))

    def _style_scrollbar(self, scrolled):
        try:
            scrolled.vbar.configure(bg=T["panel2"], troughcolor=T["bg"],
                                    activebackground=T["border2"], borderwidth=0,
                                    highlightthickness=0, width=10)
        except Exception:
            pass

    def _tab_trace(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text="▤  Trace")

        filt = ttk.Frame(tab)
        filt.pack(fill="x", pady=(0, 8))
        ttk.Label(filt, text="FILTER", style="Dim.TLabel").pack(side="left", padx=(0, 8))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._refilter())
        self.filter_entry = ttk.Entry(filt, textvariable=self.filter_var)
        self.filter_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(filt, text="×", width=3,
                   command=self._clear_filter).pack(side="left", padx=(6, 0))
        self.match_lbl = tk.Label(filt, text="", bg=T["bg"], fg=T["dimmer"],
                                  font=T["font_xs"])
        self.match_lbl.pack(side="left", padx=8)

        paned = tk.PanedWindow(tab, orient="vertical", bg=T["bg"], bd=0,
                               sashwidth=6, sashrelief="flat", showhandle=False)
        paned.pack(fill="both", expand=True)

        log_card = tk.Frame(paned, bg=T["panel"], highlightbackground=T["border"],
                            highlightthickness=1)
        head = tk.Frame(log_card, bg=T["panel"])
        head.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(head, text="LIVE TRACE  /  EVENT STREAM", bg=T["panel"], fg=T["dim"],
                 font=T["font_xs"]).pack(side="left")
        self.live_log = scrolledtext.ScrolledText(
            log_card, wrap="char", font=T["font_s"],
            bg=T["panel"], fg=T["fg_mid"], insertbackground=T["accent"],
            selectbackground=T["panel3"], selectforeground=T["accent"],
            relief="flat", borderwidth=0, padx=10, pady=6)
        self.live_log.pack(fill="both", expand=True, padx=1, pady=(4, 1))
        self.live_log.configure(state="disabled")
        for tag, color in {"info": T["fg_mid"], "open": T["accent"], "close": T["red"],
                           "digest": T["warn"], "err": T["red"]}.items():
            self.live_log.tag_config(tag, foreground=color)
        self._style_scrollbar(self.live_log)

        table_card = tk.Frame(paned, bg=T["panel"], highlightbackground=T["border"],
                              highlightthickness=1)
        head = tk.Frame(table_card, bg=T["panel"])
        head.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(head, text="▮  APP RUNTIME", bg=T["panel"], fg=T["dim"],
                 font=T["font_xs"]).pack(side="left")

        wrap = tk.Frame(table_card, bg=T["panel"])
        wrap.pack(fill="both", expand=True, padx=1, pady=(4, 1))
        self.table = ttk.Treeview(wrap, columns=("rank", "app", "title", "time", "share"),
                                  show="headings")
        for key, width, anchor in [("rank", 42, "center"), ("app", 190, "w"),
                                   ("title", 560, "w"), ("time", 100, "e"),
                                   ("share", 190, "w")]:
            self.table.heading(key, command=lambda k=key: self._sort_by(k))
            self.table.column(key, width=width, anchor=anchor, stretch=(key == "title"))
        self.table.tag_configure("odd", background=T["panel"])
        self.table.tag_configure("even", background=T["panel2"])
        self.table.tag_configure("empty", foreground=T["dimmer"])

        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.bind("<Double-1>", self._table_double)
        self._update_headings()

        paned.add(log_card, stretch="always", minsize=140)
        paned.add(table_card, stretch="never", minsize=150)
        self.root.after(120, lambda: paned.sash_place(0, 0, max(200, paned.winfo_height() - 220)))

    def _tab_output(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text="▣  Output")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="➤  Flush + Send", command=self.flush_now).pack(side="left", padx=(0, 4))
        ttk.Button(bar, text="⇩  Export", command=self.export_digest).pack(side="left", padx=4)
        ttk.Button(bar, text="copy", command=self.copy_digest).pack(side="left", padx=4)
        ttk.Button(bar, text="resend", command=self.resend_last).pack(side="left", padx=4)

        card = tk.Frame(tab, bg=T["panel"], highlightbackground=T["border"],
                        highlightthickness=1)
        card.pack(fill="both", expand=True)
        head = tk.Frame(card, bg=T["panel"])
        head.pack(fill="x", padx=10, pady=(7, 0))
        tk.Label(head, text="LAST DIGEST", bg=T["panel"], fg=T["dim"],
                 font=T["font_xs"]).pack(side="left")
        self.digest_meta = tk.Label(head, text="—", bg=T["panel"], fg=T["dimmer"],
                                    font=T["font_xs"])
        self.digest_meta.pack(side="right")

        self.output = scrolledtext.ScrolledText(
            card, wrap="none", font=T["font_s"],
            bg=T["panel"], fg=T["fg"], relief="flat", borderwidth=0,
            padx=10, pady=8)
        self.output.pack(fill="both", expand=True, padx=1, pady=(4, 1))
        self.output.configure(state="disabled")
        self.output.tag_config("hdr", foreground=T["accent"],
                               font=(FONT_FAMILY, 9, "bold"))
        self.output.tag_config("sep", foreground=T["dimmer"])
        self.output.tag_config("key", foreground=T["dim"])
        self.output.tag_config("body", foreground=T["fg"])
        self.output.tag_config("num", foreground=T["fg_mid"])
        self._style_scrollbar(self.output)

    def _tab_telegram(self):
        tab = ttk.Frame(self.nb, padding=16)
        self.nb.add(tab, text="➤  Telegram")

        ttk.Label(tab, text="credentials", style="Dim.TLabel").pack(anchor="w")
        r1 = ttk.Frame(tab)
        r1.pack(fill="x", pady=(4, 6))
        ttk.Label(r1, text="bot token", width=14, style="Dim.TLabel").pack(side="left")
        self.token_var = tk.StringVar(value=self.cfg.get("bot_token", ""))
        self.token_entry = ttk.Entry(r1, textvariable=self.token_var, show="•")
        self.token_entry.pack(side="left", fill="x", expand=True)
        self._show_token = False
        ttk.Button(r1, text="show", width=5,
                   command=self._toggle_token_vis).pack(side="left", padx=(6, 0))

        r2 = ttk.Frame(tab)
        r2.pack(fill="x", pady=6)
        ttk.Label(r2, text="chat id", width=14, style="Dim.TLabel").pack(side="left")
        self.chat_var = tk.StringVar(value=self.cfg.get("chat_id", ""))
        ttk.Entry(r2, textvariable=self.chat_var).pack(side="left", fill="x", expand=True)

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="save", style="Accent.TButton",
                   command=self.save_telegram).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="test", command=self.test_telegram).pack(side="left")

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=20)
        ttk.Label(tab, text="status", style="Dim.TLabel").pack(anchor="w")
        self.tg_status = tk.Label(tab, text=self._tg_status_text(), bg=T["bg"],
                                  fg=T["fg"], font=T["font_s"], justify="left")
        self.tg_status.pack(anchor="w", pady=(4, 16))

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=(0, 16))
        info = (
            "getting credentials:\n"
            "  1. open @BotFather in telegram\n"
            "  2. /newbot → follow prompts → copy token\n"
            "  3. message your bot once (/start)\n"
            "  4. get chat id from @userinfobot\n"
            "  5. paste both fields, save, then test"
        )
        ttk.Label(tab, text=info, style="Dim.TLabel",
                  font=T["font_xs"], justify="left").pack(anchor="w")

    def _tab_settings(self):
        tab = ttk.Frame(self.nb, padding=16)
        self.nb.add(tab, text="⚙  Settings")

        ttk.Label(tab, text="digest interval", style="Dim.TLabel").pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(4, 6))
        self.interval_var = tk.IntVar(value=self.interval_seconds())
        ttk.Spinbox(row, from_=5, to=3600, textvariable=self.interval_var,
                    width=8).pack(side="left")
        ttk.Label(row, text="seconds between automatic summaries",
                  style="Dim.TLabel").pack(side="left", padx=10)

        self.autostart_var = tk.BooleanVar(value=bool(self.cfg.get("start_on_launch")))
        ttk.Checkbutton(tab, text="start tracing automatically when the app opens",
                        variable=self.autostart_var).pack(anchor="w", pady=(4, 12))

        ttk.Button(tab, text="save", style="Accent.TButton",
                   command=self.save_settings).pack(anchor="w")

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=18)
        ttk.Label(tab, text="what is recorded", style="Dim.TLabel").pack(anchor="w")
        info = (
            "foreground window at 1 Hz:\n"
            "  · process name + window title\n"
            "  · open / close transitions\n"
            "  · time spent per application\n"
            "  · local: events.log + digests.log\n"
            "  · remote: telegram if configured\n"
            "\n"
            "no keystrokes · no OS hooks · no auto-start"
        )
        ttk.Label(tab, text=info, style="Dim.TLabel", font=T["font_s"],
                  justify="left").pack(anchor="w", pady=(6, 0))

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=18)
        ttk.Label(tab, text="data", style="Dim.TLabel").pack(anchor="w")
        ttk.Label(tab, text=str(DATA_DIR), style="Dim.TLabel",
                  font=T["font_s"]).pack(anchor="w", pady=(2, 8))
        row2 = ttk.Frame(tab)
        row2.pack(anchor="w")
        ttk.Button(row2, text="open data dir",
                   command=self.open_data_dir).pack(side="left", padx=(0, 6))
        ttk.Button(row2, text="paths", command=self.show_paths).pack(side="left", padx=6)

    # ------------------------------------------------------------ actions
    def _toggle_token_vis(self):
        self._show_token = not self._show_token
        self.token_entry.configure(show="" if self._show_token else "•")

    def _tg_status_text(self):
        tok = self.cfg.get("bot_token", "")
        chat = self.cfg.get("chat_id", "")
        if not tok or not chat:
            return "not configured — local only"
        ok = self.last_tg_ok
        last = "never sent" if ok is None else ("last send ok" if ok else "last send failed")
        return f"chat {chat} · {last} · ok={self.tg_ok} fail={self.tg_fail}"

    def _bind_shortcuts(self):
        self.root.bind("<F9>", lambda e: self.stop() if self.running else self.start())
        self.root.bind("<F5>", lambda e: self.flush_now())
        self.root.bind("<Control-k>", lambda e: self.filter_entry.focus_set())
        self.root.bind("<Escape>", lambda e: self._clear_filter())

    def _blink(self):
        self._blink_on = not self._blink_on
        try:
            if self.running:
                self.status_lbl.configure(text="● TRACING" if self._blink_on else "○ TRACING",
                                          fg=T["green"] if self._blink_on else T["dim"])
            else:
                self.status_lbl.configure(text="● IDLE", fg=T["dim"])
            self.root.after(600, self._blink)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ trace
    def _trace(self, text, tag="info"):
        self.root.after(0, lambda: self._trace_ui(text, tag))

    def _trace_ui(self, text, tag):
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        self._trace_data.append((line, tag))
        needle = self.filter_var.get().lower() if hasattr(self, "filter_var") else ""
        if needle and needle not in line.lower():
            self._update_match_label()
            return
        self.live_log.configure(state="normal")
        self.live_log.insert("end", line + "\n", tag)
        self.live_log.see("end")
        self.live_log.configure(state="disabled")
        self._update_match_label()

    def _refilter(self):
        needle = self.filter_var.get().lower()
        self.live_log.configure(state="normal")
        self.live_log.delete("1.0", "end")
        for line, tag in self._trace_data:
            if not needle or needle in line.lower():
                self.live_log.insert("end", line + "\n", tag)
        self.live_log.configure(state="disabled")
        self._update_match_label()

    def _update_match_label(self):
        needle = self.filter_var.get().strip()
        if not needle:
            self.match_lbl.configure(text="")
            return
        hits = sum(1 for line, _ in self._trace_data if needle.lower() in line.lower())
        self.match_lbl.configure(text=f"{hits}/{len(self._trace_data)}")

    def _clear_filter(self):
        if hasattr(self, "filter_var"):
            self.filter_var.set("")

    def _heartbeat_line(self):
        try:
            ensure_dir()
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  GUI   ghostkey opened\n")
        except Exception:
            pass

    def _event_file(self, kind, proc, detail=""):
        try:
            ensure_dir()
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {kind:<5}  {proc}  {detail}\n")
        except Exception:
            pass

    def interval_seconds(self):
        try:
            return max(5, int(self.cfg.get("interval", 30)))
        except Exception:
            return 30

    # ------------------------------------------------------------ stats
    def _refresh_stats(self):
        with self.lock:
            uptime = time.time() - (self.start_time or time.time())
            apps = len(self.app_seconds)
            events = self.events_session
            nxt = self.next_digest
            current = self.current
            ok, fail = self.tg_ok, self.tg_fail
        self.stat_values["uptime"].configure(
            text=time.strftime("%H:%M:%S", time.gmtime(max(0, uptime))) if self.running else "—")
        self.stat_values["apps"].configure(text=str(apps))
        self.stat_values["events"].configure(text=str(events))
        self.stat_values["tg"].configure(text=f"{ok}/{fail}")
        if self.running and nxt:
            left = max(0, int(nxt - time.time()))
            self.stat_values["next"].configure(text=time.strftime("%H:%M:%S", time.gmtime(left)))
        else:
            self.stat_values["next"].configure(text="—")

        if self.running and current:
            proc, title = current
            active = f"{proc} — {clean_text(title, 78)}" if title else proc
            self.active_lbl.configure(text=f"●  ACTIVE   |   {active}", fg=T["green"])
        else:
            self.active_lbl.configure(text="●  SESSION IDLE   |   No active window", fg=T["dim"])
        last = self.last_digest_time.strftime("%H:%M:%S") if self.last_digest_time else "—"
        self.last_lbl.configure(text=f"last digest {last}")
        if hasattr(self, "tg_status"):
            self.tg_status.configure(text=self._tg_status_text())

    def _refresh_table(self):
        with self.lock:
            rows = [(proc, self.app_titles.get(proc, ""), secs,
                     secs / (sum(self.app_seconds.values()) or 1.0) * 100.0)
                    for proc, secs in self.app_seconds.items()]
        reverse = self.sort_desc
        if self.sort_key in ("app", "title"):
            idx = 0 if self.sort_key == "app" else 1
            rows.sort(key=lambda r: (r[idx] or "").lower(), reverse=reverse)
        else:
            rows.sort(key=lambda r: r[2], reverse=reverse)
        self.table.delete(*self.table.get_children())
        if not rows:
            self.table.insert("", "end", values=("—", "—", "No activity recorded yet", "", ""),
                              tags=("empty",))
            return
        for i, (proc, title, secs, pct) in enumerate(rows[:50]):
            blocks = max(1, min(10, round(pct / 10)))
            bar = "▰" * blocks + "▱" * (10 - blocks)
            self.table.insert("", "end", values=(
                i + 1, clean_text(proc, 26), clean_text(title, 62) or "—",
                fmt_secs(secs), f"{pct:.0f}%  {bar}"),
                tags=("even" if i % 2 else "odd",))

    def _update_headings(self):
        names = {"rank": "#", "app": "APP", "title": "ACTIVE WINDOW",
                 "time": "TIME", "share": "SHARE"}
        for key, label in names.items():
            arrow = (" ↓" if self.sort_desc else " ↑") if key == self.sort_key else ""
            self.table.heading(key, text=f"{label}{arrow}")

    def _sort_by(self, key):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key in ("time", "share")
        self._update_headings()
        self._refresh_table()

    def _table_double(self, _event):
        sel = self.table.selection()
        if not sel:
            return
        values = self.table.item(sel[0], "values")
        if values and len(values) > 1 and values[1] not in ("—", ""):
            self.filter_var.set(values[1])
            self.filter_entry.focus_set()

    def _copy(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(text))
            self._trace(f"[copy] {clean_text(text, 50)}", "info")
        except Exception:
            pass

    # ------------------------------------------------------------ tracking
    def start(self):
        if self.running:
            return
        self.running = True
        self.start_time = time.time()
        self.session_id = f"0x{int(time.time()) & 0xFFFFFF:06X}"
        now = time.time()
        with self.lock:
            self.current = None
            self.current_since = None
            self.app_seconds = {}
            self.app_titles = {}
            self.last_tick = now
            self.opened = []
            self.closed = []
            self.events_session = 0
            self.events_window = 0
            self.digests = 0
            self.window_start = now
            self.next_digest = now + self.interval_seconds()
            self.last_digest = ""
            self.last_digest_time = None
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.flush_btn.configure(state="normal")
        self._event_file("SESSION", self.session_id, "started")
        self._trace("[trace] session started", "info")
        self._refresh_stats()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()
        self._tick()

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.worker:
            self.worker.join(timeout=2.0)
            self.worker = None
        now = time.time()
        with self.lock:
            if self.current and self.last_tick:
                self.app_seconds[self.current[0]] = (
                    self.app_seconds.get(self.current[0], 0.0)
                    + max(0.0, now - self.last_tick))
            if self.current:
                self._close_app_locked(now)
            self._flush_locked("final", now)
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.flush_btn.configure(state="disabled")
        self._trace("[trace] session stopped", "info")
        self._event_file("SESSION", self.session_id, "stopped")
        self._refresh_stats()
        self._refresh_table()

    def _tick(self):
        if not self.running:
            return
        self._refresh_stats()
        self._refresh_table()
        self.root.after(1000, self._tick)

    def _worker_loop(self):
        poll = max(0.5, float(self.cfg.get("poll", 1.0)))
        while self.running:
            time.sleep(poll)
            if not self.running:
                break
            now = time.time()
            title, proc = get_foreground()
            if not title and not proc:
                continue
            with self.lock:
                if self.last_tick:
                    delta = max(0.0, now - self.last_tick)
                    if self.current:
                        self.app_seconds[self.current[0]] = (
                            self.app_seconds.get(self.current[0], 0.0) + delta)
                self.last_tick = now
                if self.current is None:
                    self._open_app_locked((proc or "?", title), now)
                elif (proc or "?") != self.current[0]:
                    self._close_app_locked(now)
                    self._open_app_locked((proc or "?", title), now)
                elif title != self.current[1]:
                    self.current = (self.current[0], title)
                    self.app_titles[self.current[0]] = title or self.app_titles.get(
                        self.current[0], "")
                if self.next_digest and now >= self.next_digest:
                    self._flush_locked("auto", now)
                    self.next_digest = now + self.interval_seconds()

    def _open_app_locked(self, new, now):
        proc, title = new
        self.current = new
        self.current_since = now
        self.opened.append(proc)
        self.events_session += 1
        self.events_window += 1
        if title:
            self.app_titles[proc] = title
        else:
            self.app_titles.setdefault(proc, "")
        self._event_file("OPEN", proc, clean_text(title, 70))
        self._trace(f"[open]  {proc} — {clean_text(title, 70)}" if title
                    else f"[open]  {proc}", "open")

    def _close_app_locked(self, now):
        if not self.current:
            return
        proc, title = self.current
        spent = max(0.0, now - (self.current_since or now))
        self.closed.append(proc)
        self.events_session += 1
        self.events_window += 1
        self._event_file("CLOSE", proc, f"{clean_text(title, 60)}  ({fmt_secs(spent)})")
        self._trace(f"[close] {proc} · {fmt_secs(spent)}", "close")
        self.current = None
        self.current_since = None

    # ------------------------------------------------------------ digest
    def _compose_digest_locked(self, now):
        if not self.app_seconds and not self.opened and not self.closed:
            return ""
        window = int(max(0.0, now - (self.window_start or now)))
        total = sum(self.app_seconds.values()) or 1.0
        top = sorted(self.app_seconds.items(), key=lambda kv: kv[1], reverse=True)[:8]
        if self.current:
            active = self.current[0]
            if self.current[1]:
                active = f"{active} — {clean_text(self.current[1], 70)}"
        else:
            active = "(none)"
        lines = [
            f"ghostkey digest  {datetime.now():%Y-%m-%d %H:%M:%S}",
            "─" * 50,
            f"session  : {self.session_id}",
            f"window   : {window}s",
            f"active   : {active}",
            f"opened   : {clean_text(dedupe_join(self.opened), 90)}",
            f"closed   : {clean_text(dedupe_join(self.closed), 90)}",
            f"events   : {self.events_window}",
            "─" * 50,
            "app time",
        ]
        for proc, secs in top:
            lines.append(f"  {clean_text(proc, 26):<26} {fmt_secs(secs):>9}  "
                         f"{secs / total * 100:5.1f}%")
        has_tg = bool(self.cfg.get("bot_token") and self.cfg.get("chat_id"))
        lines.extend([
            "─" * 50,
            f"digests: {self.digests + 1}  ·  "
            + ("local+telegram" if has_tg else "local"),
        ])
        return "\n".join(lines)

    def _flush_locked(self, reason, now=None):
        now = now or time.time()
        text = self._compose_digest_locked(now)
        self.opened = []
        self.closed = []
        self.events_window = 0
        self.window_start = now
        if not text:
            if reason != "auto":
                self.root.after(0, lambda: self._trace("[digest] nothing to flush", "info"))
            return
        try:
            ensure_dir()
            with open(DIGESTS_FILE, "a", encoding="utf-8") as f:
                f.write(text + "\n\n")
        except Exception:
            pass
        self.digests += 1
        self.last_digest = text
        self.last_digest_time = datetime.now()
        self.root.after(0, lambda t=text, r=reason: self._show_digest(t, r))
        threading.Thread(target=self._deliver_telegram, args=(text, reason),
                         daemon=True).start()

    def _deliver_telegram(self, text, reason):
        tok = self.cfg.get("bot_token", "").strip()
        chat = self.cfg.get("chat_id", "").strip()
        if not tok or not chat:
            self.root.after(0, lambda: self._trace(
                "[tg] skipped — not configured", "info"))
            return
        ok, err = send_telegram(tok, chat, text)
        if ok:
            self.tg_ok += 1
            self.last_tg_ok = True
            self.root.after(0, lambda: self._trace(
                f"[tg] sent ({len(text)} chars, {reason})", "digest"))
        else:
            self.tg_fail += 1
            self.last_tg_ok = False
            try:
                with open(BUFFER_FILE, "a", encoding="utf-8") as f:
                    f.write(text + "\n\n")
            except Exception:
                pass
            self.root.after(0, lambda e=err: self._trace(f"[tg] failed: {e}", "err"))
        self.root.after(0, self._refresh_stats)

    def _show_digest(self, text, reason):
        self._render_digest(text)
        self.digest_meta.configure(
            text=f"{self.last_digest_time:%H:%M:%S} · {reason} · {len(text.splitlines())} lines")
        self._trace(f"[digest] {reason} · {len(text.splitlines())} lines", "digest")
        self._refresh_stats()
        self._refresh_table()

    def _render_digest(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        keys = ("session", "window", "active", "opened", "closed", "events", "digests")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("ghostkey digest"):
                tag = "hdr"
            elif set(stripped) <= {"─"} and stripped:
                tag = "sep"
            elif line.startswith("  ") and "%" in line:
                tag = "num"
            elif ":" in line and line.split(":", 1)[0].strip() in keys:
                tag = "key"
            elif line == "app time":
                tag = "key"
            else:
                tag = "body"
            self.output.insert("end", line + "\n", tag)
        self.output.configure(state="disabled")

    # ------------------------------------------------------------ actions
    def flush_now(self):
        if not self.running:
            self._trace("[digest] start a trace first", "info")
            return
        with self.lock:
            self._flush_locked("manual")

    def resend_last(self):
        if not self.last_digest:
            self._trace("[tg] no digest to resend", "info")
            return
        threading.Thread(target=self._deliver_telegram,
                         args=(self.last_digest, "resend"), daemon=True).start()

    def test_telegram(self):
        tok = self.token_var.get().strip()
        chat = self.chat_var.get().strip()
        if not tok or not chat:
            messagebox.showerror("telegram", "enter bot token and chat id first.")
            return
        self._trace("[tg] test send…", "digest")

        def _w():
            sample = ("ghostkey digest  " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n"
                      + "─" * 50 + "\n"
                      "session  : 0xTEST\nwindow   : 0s\n"
                      "active   : ghostkey — test\nopened   : (none)\n"
                      "closed   : (none)\nevents   : 0\n"
                      + "─" * 50 + "\napp time\n  (none)\n"
                      + "─" * 50 + "\ndigests: 0  ·  local+telegram")
            ok, err = send_telegram(tok, chat, sample)
            if ok:
                self.root.after(0, lambda: self._trace("[tg] test ok", "digest"))
                self.root.after(0, lambda: messagebox.showinfo(
                    "telegram", "test message sent."))
            else:
                self.root.after(0, lambda: self._trace(f"[tg] test failed: {err}", "err"))
                self.root.after(0, lambda e=err: messagebox.showerror(
                    "telegram", f"failed:\n{e}"))
        threading.Thread(target=_w, daemon=True).start()

    def save_telegram(self):
        self.cfg["bot_token"] = self.token_var.get().strip()
        self.cfg["chat_id"] = self.chat_var.get().strip()
        save_config(self.cfg)
        self._trace("[tg] credentials saved", "info")
        self._refresh_stats()
        messagebox.showinfo("telegram", "saved.")

    def copy_digest(self):
        if not self.last_digest:
            self._trace("[copy] no digest yet", "info")
            return
        self._copy(self.last_digest)

    def export_digest(self):
        with self.lock:
            text = self.last_digest or self._compose_digest_locked(time.time())
        if not text:
            messagebox.showinfo(APP_NAME, "nothing to export yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"ghostkey_{datetime.now():%Y%m%d_%H%M%S}.txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(text + "\n", encoding="utf-8")
            self._trace(f"[export] {path}", "info")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def clear_state(self):
        if not messagebox.askyesno(APP_NAME, "reset session counters and clear the trace?"):
            return
        with self.lock:
            self.app_seconds = {}
            self.app_titles = {}
            self.opened = []
            self.closed = []
            self.events_session = 0
            self.events_window = 0
            self.digests = 0
            self.last_digest = ""
            self.last_digest_time = None
            self.window_start = time.time()
            if self.running:
                self.next_digest = time.time() + self.interval_seconds()
        self._trace_data = []
        self.live_log.configure(state="normal")
        self.live_log.delete("1.0", "end")
        self.live_log.configure(state="disabled")
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self.digest_meta.configure(text="—")
        self._refresh_stats()
        self._refresh_table()
        self._update_match_label()

    def save_settings(self):
        try:
            value = int(self.interval_var.get())
        except Exception:
            value = 30
        value = max(5, min(3600, value))
        self.interval_var.set(value)
        self.cfg["interval"] = value
        self.cfg["start_on_launch"] = bool(self.autostart_var.get())
        save_config(self.cfg)
        if self.running:
            with self.lock:
                self.next_digest = time.time() + value
        self._trace(f"[cfg] saved · interval={value}s", "info")
        messagebox.showinfo(APP_NAME, f"saved.\ninterval: {value}s")

    def open_digest_log(self):
        ensure_dir()
        try:
            if not DIGESTS_FILE.exists():
                DIGESTS_FILE.write_text("", encoding="utf-8")
            if sys.platform == "win32":
                os.startfile(DIGESTS_FILE)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(DIGESTS_FILE)])
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def open_data_dir(self):
        ensure_dir()
        try:
            if sys.platform == "win32":
                os.startfile(DATA_DIR)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(DATA_DIR)])
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def show_paths(self):
        messagebox.showinfo(
            "paths",
            f"data dir : {DATA_DIR}\n"
            f"config   : {CONFIG_FILE}\n"
            f"events   : {EVENTS_FILE}\n"
            f"digests  : {DIGESTS_FILE}\n"
            f"buffer   : {BUFFER_FILE}\n")

    def on_close(self):
        if self.running:
            self.stop()
        try:
            self.cfg["geometry"] = self.root.geometry()
            save_config(self.cfg)
        except Exception:
            pass
        self.root.destroy()


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    app = GhostkeyApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()