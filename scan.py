"""ghostkey :: activity telemetry + telegram relay (vintage amber console).

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
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

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

APP_NAME = "Ghostkey"
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

# ---- Ghostkey vintage telemetry palette (warm charcoal + amber phosphor) ----
T = {
    "bg":         "#0a0908",
    "panel":      "#12100d",
    "panel2":     "#191611",
    "panel3":     "#221e17",
    "border":     "#2d2820",
    "border2":    "#4a4132",
    "fg":         "#e9e0cf",
    "fg_mid":     "#c6bba6",
    "dim":        "#8b806d",
    "dimmer":     "#5d5546",
    "accent":     "#e0a458",
    "accent2":    "#6b4e26",
    "accent_soft":"#7a6238",
    "accent_ink": "#1a1206",
    "green":      "#93b56e",
    "warn":       "#d8bd77",
    "red":        "#cf6f5e",
    "red_hover":  "#b85a49",
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


def _get_foreground_windows():
    """Return (window title, process name) using native Windows APIs."""
    if wintypes is None:
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


def _get_foreground_linux():
    """Get the active X11/XWayland window using xdotool or wmctrl.

    Native Wayland compositors intentionally restrict global active-window
    inspection. This method does not bypass those restrictions.
    """
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return "", ""

    xdotool = shutil.which("xdotool")
    if xdotool and os.environ.get("DISPLAY"):
        try:
            wid = subprocess.run(
                [xdotool, "getactivewindow"], capture_output=True, text=True,
                timeout=1.0, check=True
            ).stdout.strip()
            title = subprocess.run(
                [xdotool, "getwindowname", wid], capture_output=True, text=True,
                timeout=1.0, check=True
            ).stdout.strip()
            pid_text = subprocess.run(
                [xdotool, "getwindowpid", wid], capture_output=True, text=True,
                timeout=1.0, check=True
            ).stdout.strip()
            proc = ""
            if pid_text.isdigit():
                proc_path = Path("/proc") / pid_text
                try:
                    proc = (proc_path / "comm").read_text(encoding="utf-8").strip()
                except OSError:
                    try:
                        proc = Path(os.readlink(proc_path / "exe")).name
                    except OSError:
                        proc = ""
            return title, proc
        except (subprocess.SubprocessError, OSError, ValueError):
            pass

    return "", ""


def get_foreground():
    if sys.platform == "win32":
        return _get_foreground_windows()
    if sys.platform.startswith("linux"):
        return _get_foreground_linux()
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


class RoundedPanel(tk.Frame):
    """Framed panel with optional corner ticks; child widgets go in .content."""
    def __init__(self, master, *, bg, border, radius=14, border_width=1,
                 accent=None, **kwargs):
        super().__init__(master, bg=bg, bd=0, highlightthickness=0, **kwargs)
        self._panel_bg = bg
        self._border = border
        self._radius = radius
        self._border_width = border_width
        self._accent = accent
        self._canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.content = tk.Frame(self, bg=bg, bd=0, highlightthickness=0)
        self.content.place(x=border_width + 5, y=border_width + 4,
                           relwidth=1, relheight=1,
                           width=-(2 * (border_width + 5)),
                           height=-(2 * (border_width + 4)))
        self.bind('<Configure>', self._draw, add='+')

    def _draw(self, _event=None):
        """Draw a crisp rectangular panel border plus corner ticks."""
        try:
            self._canvas.delete('rounded-panel')
            w, h = max(2, self.winfo_width()), max(2, self.winfo_height())
            self._canvas.create_rectangle(
                1, 1, w - 1, h - 1,
                fill=self._panel_bg,
                outline=self._border,
                width=self._border_width,
                tags='rounded-panel',
            )
            if self._accent:
                tick = 8
                x1, y1, x2, y2 = 1, 1, w - 1, h - 1
                for xa, ya, xb, yb in (
                    (x1, y1, x1 + tick, y1), (x1, y1, x1, y1 + tick),
                    (x2, y1, x2 - tick, y1), (x2, y1, x2, y1 + tick),
                    (x1, y2, x1 + tick, y2), (x1, y2, x1, y2 - tick),
                    (x2, y2, x2 - tick, y2), (x2, y2, x2, y2 - tick),
                ):
                    self._canvas.create_line(xa, ya, xb, yb,
                                             fill=self._accent, width=1,
                                             tags='rounded-panel')
            self._canvas.tag_lower('rounded-panel')
        except tk.TclError:
            pass


class GhostkeyApp:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        pick_fonts(root)

        self.root.title("Ghostkey :: activity telemetry")
        geometry = self.cfg.get("geometry") or "1440x900"
        try:
            self.root.geometry(geometry)
        except tk.TclError:
            self.root.geometry("1440x900")
        self.root.minsize(1100, 720)
        self.root.configure(bg=T["bg"])

        self.session_id = f"0x{int(time.time()) & 0xFFFFFF:06X}"
        self.running = False
        self.stopping = False
        self.worker = None
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        # Tk widgets are only touched by the main thread. Background workers
        # publish callbacks to this queue; the UI drains it on a timer.
        self.ui_queue = queue.Queue(maxsize=5000)
        self.io_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ghostkey-io")
        self._closing = False
        self.start_time = None

        self.current = None
        self.current_since = None
        self.app_seconds = {}
        self.app_titles = {}
        # Per-process window-title timeline. Browser titles commonly identify the
        # currently selected tab/page; this is not keystroke or full browser-history capture.
        self.title_history = {}
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
        self._ui_tick_count = 0

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
        self.root.after(40, self._drain_ui_queue)
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
                    bordercolor=T["border2"], lightcolor=T["border2"],
                    darkcolor=T["border2"], borderwidth=1, relief="solid",
                    padding=(12, 7), font=T["font_s"])
        s.map("TButton",
              background=[("active", T["panel3"]), ("disabled", T["bg"])],
              foreground=[("active", T["accent"]), ("disabled", T["dimmer"])],
              bordercolor=[("active", T["accent"])])

        s.configure("Accent.TButton", background=T["accent"], foreground=T["accent_ink"],
                    bordercolor=T["accent"], lightcolor=T["accent"],
                    darkcolor=T["accent2"], borderwidth=1, relief="solid",
                    padding=(14, 8), font=(FONT_FAMILY, 9, "bold"))
        s.map("Accent.TButton",
              background=[("active", "#f0bd72"), ("disabled", T["panel2"])],
              foreground=[("active", T["accent_ink"]), ("disabled", T["dimmer"])])

        s.configure("Danger.TButton", background="#6e2a22", foreground="#f6ded7",
                    bordercolor="#a84a3c", lightcolor="#a84a3c",
                    darkcolor="#4d1b16", borderwidth=1, relief="solid",
                    padding=(12, 7), font=T["font_s"])
        s.map("Danger.TButton",
              background=[("active", T["red_hover"]), ("disabled", T["panel2"])],
              foreground=[("active", "#fff4f0"), ("disabled", T["dimmer"])],
              bordercolor=[("active", T["red"])])
        s.configure("Stop.TButton", background=T["panel2"], foreground=T["fg"],
                    bordercolor=T["border2"], lightcolor=T["border2"],
                    darkcolor=T["border2"], borderwidth=1, relief="solid",
                    padding=(12, 7), font=T["font_s"])
        s.map("Stop.TButton", background=[("active", T["panel3"]), ("disabled", T["bg"])],
              foreground=[("active", T["accent"]), ("disabled", T["dimmer"])])

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
        header = tk.Frame(self.root, bg=T["bg"], height=72)
        header.pack(fill="x", padx=24, pady=(12, 0))
        header.pack_propagate(False)

        left = tk.Frame(header, bg=T["bg"])
        left.pack(side="left", fill="y")
        brand = tk.Frame(left, bg=T["bg"])
        brand.pack(anchor="w", pady=(7, 0))
        text_col = tk.Frame(brand, bg=T["bg"])
        text_col.pack(side="left", anchor="n")
        word = tk.Frame(text_col, bg=T["bg"])
        word.pack(anchor="w")
        tk.Label(word, text="Ghostkey", bg=T["bg"], fg=T["fg"],
                 font=(FONT_FAMILY, 20, "bold")).pack(side="left")
        self.cursor_lbl = tk.Label(word, text="█", bg=T["bg"], fg=T["accent"],
                                   font=(FONT_FAMILY, 15, "bold"))
        self.cursor_lbl.pack(side="left", padx=(3, 0))
        tk.Label(text_col, text="activity telemetry  //  local console", bg=T["bg"],
                 fg=T["dim"], font=T["font_xs"]).pack(anchor="w")

        right = tk.Frame(header, bg=T["bg"])
        right.pack(side="right", fill="y")
        self.status_lbl = tk.Label(right, text="● IDLE", bg=T["bg"], fg=T["fg_mid"],
                                   font=(FONT_FAMILY, 9))
        self.status_lbl.pack(side="right", pady=(27, 0))
        tk.Label(right, text="│", bg=T["bg"], fg=T["border2"],
                 font=T["font_s"]).pack(side="right", padx=12, pady=(25, 0))
        self.clock_lbl = tk.Label(right, text="", bg=T["bg"], fg=T["dim"],
                                  font=T["font_xs"])
        self.clock_lbl.pack(side="right", pady=(27, 0))
        self.sid_lbl = tk.Label(right, text=f"SID {self.session_id}", bg=T["bg"],
                                fg=T["dimmer"], font=T["font_xs"])
        self.sid_lbl.pack(side="right", padx=(0, 12), pady=(27, 0))

        rule = tk.Frame(self.root, bg=T["border"], height=1)
        rule.pack(fill="x", padx=24, pady=(10, 0))

        self._build_stats()
        self._build_active_strip()
        self._build_controls()

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=24, pady=(12, 0))
        self._tab_trace()
        self._tab_output()
        self._tab_telegram()
        self._tab_settings()

        footer = tk.Frame(self.root, bg=T["bg"], height=26)
        footer.pack(fill="x", padx=24, pady=(2, 10))
        footer.pack_propagate(False)
        tk.Label(footer, text="[F9] start/stop   [F5] flush   [^K] filter   [ESC] clear",
                 bg=T["bg"], fg=T["dimmer"], font=T["font_xs"]).pack(side="left", pady=5)
        tk.Label(footer, text=f"» {DATA_DIR}", bg=T["bg"], fg=T["dimmer"],
                 font=T["font_xs"]).pack(side="right", pady=5)
        tk.Label(footer, text="foreground metadata only · no keystrokes",
                 bg=T["bg"], fg=T["dimmer"], font=T["font_xs"]).pack(
                     side="right", padx=(0, 18), pady=5)

    def _section_prompt(self, parent, command, bg):
        """Shell-style section header: `$ command` with an amber prompt."""
        row = tk.Frame(parent, bg=bg)
        tk.Label(row, text="$", bg=bg, fg=T["accent"],
                 font=T["font_xs"]).pack(side="left", padx=(0, 6))
        tk.Label(row, text=command, bg=bg, fg=T["dim"],
                 font=T["font_xs"]).pack(side="left")
        return row

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
            card = RoundedPanel(row, bg=T["panel"], border=T["border2"], radius=14,
                                border_width=1, accent=T["accent_soft"], height=76)
            card.pack(side="left", fill="both", expand=True, padx=(0, 12))
            card.pack_propagate(False)
            icon_lbl = tk.Label(card.content, text=icon, bg=T["panel"], fg=T["accent"],
                                font=(FONT_FAMILY, 20, "bold"), width=3)
            icon_lbl.pack(side="left", padx=(8, 2))
            body = tk.Frame(card.content, bg=T["panel"])
            body.pack(side="left", fill="both", expand=True, pady=10)
            tk.Label(body, text=f":: {label}", bg=T["panel"], fg=T["dim"],
                     font=T["font_xs"]).pack(anchor="w")
            value = tk.Label(body, text="—", bg=T["panel"], fg=T["accent"],
                             font=T["font_stat"])
            value.pack(anchor="w", pady=(2, 0))
            self.stat_values[key] = value

    def _build_active_strip(self):
        strip = RoundedPanel(self.root, bg=T["panel"], border=T["border2"], radius=12,
                             border_width=1, accent=T["accent_soft"], height=38)
        strip.pack(fill="x", padx=24, pady=(12, 0))
        self.active_lbl = tk.Label(strip.content, text="»  SESSION IDLE   |   press [START] to begin", bg=T["panel"],
                                   fg=T["dim"], font=T["font_s"], anchor="w")
        self.active_lbl.pack(side="left", padx=6, pady=4)
        self.last_lbl = tk.Label(strip.content, text="last digest » —", bg=T["panel"],
                                 fg=T["dimmer"], font=T["font_xs"])
        self.last_lbl.pack(side="right", padx=10)

    def _build_controls(self):
        bar = tk.Frame(self.root, bg=T["bg"])
        bar.pack(fill="x", padx=24, pady=(12, 0))
        self.start_btn = ttk.Button(bar, text="[ ▶ START ]", style="Accent.TButton",
                                    command=self.start)
        self.start_btn.pack(side="left", padx=(0, 4))
        self.stop_btn = ttk.Button(bar, text="[ ■ STOP ]", style="Stop.TButton", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.flush_btn = ttk.Button(bar, text="[ ➤ FLUSH ]", command=self.flush_now,
                                    state="disabled")
        self.flush_btn.pack(side="left", padx=4)
        ttk.Button(bar, text="[ ↗ TEST TG ]", command=self.test_telegram).pack(side="left", padx=4)
        ttk.Button(bar, text="[ ⇩ EXPORT ]", command=self.export_digest).pack(side="left", padx=4)
        ttk.Button(bar, text="[ ▤ CLEAR ]", command=self.clear_state).pack(side="left", padx=4)
        ttk.Button(bar, text="[ ▣ OPEN LOG ]", command=self.open_digest_log).pack(
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
        self.nb.add(tab, text=" 01 · trace ")

        filt = ttk.Frame(tab)
        filt.pack(fill="x", pady=(0, 8))
        ttk.Label(filt, text="$ grep", style="Dim.TLabel").pack(side="left", padx=(0, 8))
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

        log_card = RoundedPanel(paned, bg=T["panel"], border=T["border2"], radius=14,
                                border_width=1, accent=T["accent_soft"])
        head = tk.Frame(log_card.content, bg=T["panel"])
        head.pack(fill="x", padx=10, pady=(6, 0))
        self._section_prompt(head, "tail -f trace.log", T["panel"]).pack(side="left")
        self.live_log = scrolledtext.ScrolledText(
            log_card.content, wrap="char", font=T["font_s"],
            bg=T["panel"], fg=T["fg_mid"], insertbackground=T["accent"],
            selectbackground=T["panel3"], selectforeground=T["accent"],
            relief="flat", borderwidth=0, padx=10, pady=6)
        self.live_log.pack(fill="both", expand=True, padx=1, pady=(4, 1))
        self.live_log.configure(state="disabled")
        for tag, color in {"info": T["fg_mid"], "open": T["accent"], "close": T["red"],
                           "digest": T["warn"], "err": T["red"]}.items():
            self.live_log.tag_config(tag, foreground=color)
        self._style_scrollbar(self.live_log)

        table_card = RoundedPanel(paned, bg=T["panel"], border=T["border2"], radius=14,
                                  border_width=1, accent=T["accent_soft"])
        head = tk.Frame(table_card.content, bg=T["panel"])
        head.pack(fill="x", padx=10, pady=(6, 0))
        self._section_prompt(head, "ps --sort=time", T["panel"]).pack(side="left")

        wrap = tk.Frame(table_card.content, bg=T["panel"])
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
        self.nb.add(tab, text=" 02 · output ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="[ ➤ FLUSH ]", command=self.flush_now).pack(side="left", padx=(0, 4))
        ttk.Button(bar, text="[ ⇩ EXPORT ]", command=self.export_digest).pack(side="left", padx=4)
        ttk.Button(bar, text="[ COPY ]", command=self.copy_digest).pack(side="left", padx=4)
        ttk.Button(bar, text="[ RESEND ]", command=self.resend_last).pack(side="left", padx=4)

        card = RoundedPanel(tab, bg=T["panel"], border=T["border2"], radius=14,
                            border_width=1, accent=T["accent_soft"])
        card.pack(fill="both", expand=True)
        head = tk.Frame(card.content, bg=T["panel"])
        head.pack(fill="x", padx=10, pady=(7, 0))
        self._section_prompt(head, "cat last-digest.txt", T["panel"]).pack(side="left")
        self.digest_meta = tk.Label(head, text="—", bg=T["panel"], fg=T["dimmer"],
                                    font=T["font_xs"])
        self.digest_meta.pack(side="right")

        self.output = scrolledtext.ScrolledText(
            card.content, wrap="none", font=T["font_s"],
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
        self.nb.add(tab, text=" 03 · telegram ")

        ttk.Label(tab, text="$ cat ~/.ghostkey/config.json  // credentials",
                  style="Dim.TLabel").pack(anchor="w")
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
        ttk.Button(btns, text="[ SAVE ]", style="Accent.TButton",
                   command=self.save_telegram).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="[ TEST ]", command=self.test_telegram).pack(side="left")

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=20)
        ttk.Label(tab, text="$ status", style="Dim.TLabel").pack(anchor="w")
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
        self.nb.add(tab, text=" 04 · settings ")

        ttk.Label(tab, text="$ ghostkey --delivery", style="Dim.TLabel").pack(anchor="w")
        ttk.Label(tab, text="The detailed Telegram report is generated only when you press Stop.",
                  style="Dim.TLabel").pack(anchor="w", pady=(4, 8))

        interval_row = ttk.Frame(tab)
        interval_row.pack(fill="x", pady=(2, 10))
        ttk.Label(interval_row, text="Local checkpoint interval (seconds)",
                  style="Dim.TLabel").pack(side="left")
        self.interval_var = tk.IntVar(value=self.interval_seconds())
        ttk.Spinbox(interval_row, from_=5, to=3600, increment=5, width=8,
                    textvariable=self.interval_var).pack(side="left", padx=(12, 0))
        ttk.Label(tab, text="Records a local checkpoint at this interval; it does not send a Telegram message.",
                  style="Dim.TLabel", font=T["font_s"]).pack(anchor="w", pady=(0, 10))

        self.autostart_var = tk.BooleanVar(value=bool(self.cfg.get("start_on_launch")))
        ttk.Checkbutton(tab, text="start tracing automatically when the app opens",
                        variable=self.autostart_var).pack(anchor="w", pady=(4, 12))

        ttk.Button(tab, text="[ SAVE ]", style="Accent.TButton",
                   command=self.save_settings).pack(anchor="w")

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=18)
        ttk.Label(tab, text="$ man ghostkey", style="Dim.TLabel").pack(anchor="w")
        info = (
            "foreground window at ~1 Hz:\n"
            "  · process name + visible window title changes\n"
            "  · browser tab/page titles when visible in the title bar\n"
            "  · open / close transitions + time per app\n"
            "  · final report generated only on Stop\n"
            "  · local logs + Telegram report if configured\n"
            "\n"
            "no keystrokes · no page-content capture · no full browser history"
        )
        ttk.Label(tab, text=info, style="Dim.TLabel", font=T["font_s"],
                  justify="left").pack(anchor="w", pady=(6, 0))

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=18)
        ttk.Label(tab, text="$ ls ~/.ghostkey", style="Dim.TLabel").pack(anchor="w")
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
            self.cursor_lbl.configure(fg=T["accent"] if self._blink_on else T["bg"])
            self.clock_lbl.configure(text=time.strftime("%Y.%m.%d  %H:%M:%S"))
            self.root.after(600, self._blink)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ trace
    def _post_ui(self, callback):
        """Queue a UI callback safely from any thread without calling Tk there."""
        if self._closing:
            return
        try:
            self.ui_queue.put_nowait(callback)
        except queue.Full:
            # Drop the oldest pending UI callback to keep memory bounded.
            try:
                self.ui_queue.get_nowait()
                self.ui_queue.put_nowait(callback)
            except (queue.Empty, queue.Full):
                pass

    def _drain_ui_queue(self):
        if self._closing:
            return
        # Bound work per frame so a burst of log events cannot freeze rendering.
        for _ in range(200):
            try:
                callback = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except tk.TclError:
                if self._closing:
                    return
            except Exception as exc:
                try:
                    self._trace_ui(f"[ui] callback error: {exc}", "err")
                except Exception:
                    pass
        try:
            self.root.after(40, self._drain_ui_queue)
        except tk.TclError:
            pass

    def _trace(self, text, tag="info"):
        self._post_ui(lambda t=text, g=tag: self._trace_ui(t, g))

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
            current = self.current
            ok, fail = self.tg_ok, self.tg_fail
        self.stat_values["uptime"].configure(
            text=time.strftime("%H:%M:%S", time.gmtime(max(0, uptime))) if self.running else "—")
        self.stat_values["apps"].configure(text=str(apps))
        self.stat_values["events"].configure(text=str(events))
        self.stat_values["tg"].configure(text=f"{ok}/{fail}")
        if self.running:
            self.stat_values["next"].configure(text="ON STOP")
        else:
            self.stat_values["next"].configure(text="—")

        if self.running and current:
            proc, title = current
            active = f"{proc} — {clean_text(title, 78)}" if title else proc
            self.active_lbl.configure(text=f"»  ACTIVE   |   {active}", fg=T["green"])
        elif self.running:
            self.active_lbl.configure(text="»  STARTING   |   waiting for foreground window…", fg=T["warn"])
        else:
            self.active_lbl.configure(text="»  SESSION IDLE   |   press [START] to begin", fg=T["dim"])
        last = self.last_digest_time.strftime("%H:%M:%S") if self.last_digest_time else "—"
        self.last_lbl.configure(text=f"last digest » {last}")
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
        if self.running or self.stopping:
            return
        self.running = True
        self.stopping = False
        self.stop_event.clear()
        self.start_time = time.time()
        self.session_id = f"0x{int(time.time()) & 0xFFFFFF:06X}"
        now = time.time()
        with self.lock:
            self.current = None
            self.current_since = None
            self.app_seconds = {}
            self.app_titles = {}
            self.title_history = {}
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
        self.status_lbl.configure(text="● STARTING", fg=T["accent"])
        self.sid_lbl.configure(text=f"SID {self.session_id}")
        self.active_lbl.configure(text="»  STARTING   |   waiting for foreground window…", fg=T["warn"])
        self._event_file("SESSION", self.session_id, "started")
        self._trace("[trace] session started — foreground polling enabled", "info")
        if sys.platform.startswith("linux"):
            if not shutil.which("xdotool"):
                self._trace("[linux] xdotool not found; install it (sudo apt install xdotool) for X11/XWayland tracking", "err")
            elif not os.environ.get("DISPLAY"):
                self._trace("[linux] DISPLAY is unset; active-window tracking may be unavailable in this session", "err")
            elif os.environ.get("WAYLAND_DISPLAY"):
                self._trace("[linux] Wayland detected; xdotool sees XWayland windows only, not every native Wayland app", "info")
        self._refresh_stats()
        try:
            self.worker = threading.Thread(target=self._worker_loop, name="ghostkey-tracker", daemon=True)
            self.worker.start()
        except Exception as exc:
            self.running = False
            self.stop_event.set()
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.flush_btn.configure(state="disabled")
            self.status_lbl.configure(text="● ERROR", fg=T["red"])
            self.active_lbl.configure(text=f"»  START FAILED   |   {clean_text(exc, 100)}", fg=T["red"])
            self._trace(f"[start] failed: {exc}", "err")
            messagebox.showerror("Ghostkey", f"Could not start tracking:\n{exc}")
            return
        self._tick()

    def stop(self):
        """Request a stop without blocking Tk, then report only after tracking exits."""
        if not self.running or self.stopping:
            return

        # Immediately prevent more samples and prevent a second click from
        # starting a competing finalization sequence.
        self.stopping = True
        self.running = False
        self.stop_event.set()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        self.flush_btn.configure(state="disabled")
        self.status_lbl.configure(text="● FINALIZING", fg=T["warn"])
        self.active_lbl.configure(
            text="»  FINALIZING  |  compiling session report and sending to telegram…",
            fg=T["warn"])
        self._trace("[trace] stop requested — waiting for final sample", "digest")

        worker = self.worker
        # Joining and report delivery must never run on Tk's UI thread.
        threading.Thread(
            target=self._finish_stop, args=(worker,),
            name="ghostkey-finalizer", daemon=True
        ).start()

    def _finish_stop(self, worker):
        """Wait for the sampler to exit, snapshot all events, then queue delivery."""
        try:
            if worker is not None and worker is not threading.current_thread():
                # The worker checks stop_event immediately after each OS sample;
                # join here is safe because this function is not the UI thread.
                worker.join()

            now = time.time()
            with self.lock:
                # Account for the final interval since the last completed sample.
                if self.current and self.last_tick:
                    self.app_seconds[self.current[0]] = (
                        self.app_seconds.get(self.current[0], 0.0)
                        + max(0.0, now - self.last_tick)
                    )
                if self.current:
                    self._close_app_locked(now)
                # Compose/save the final report and enqueue Telegram delivery.
                # This is the only automatic report send; no timed digest runs.
                delivery_future = self._flush_locked("final", now)
                self.worker = None

            # Wait off the UI thread for Telegram delivery to finish so Stop has
            # a truthful final state. Network requests have bounded timeouts.
            if delivery_future is not None:
                delivery_future.result(timeout=45)
            self._post_ui(self._stop_ui_complete)
        except Exception as exc:
            self._post_ui(lambda e=str(exc): self._stop_ui_failed(e))

    def _stop_ui_complete(self):
        if self._closing:
            return
        self.stopping = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.flush_btn.configure(state="disabled")
        self.status_lbl.configure(text="● IDLE", fg=T["dim"])
        if not self.cfg.get("bot_token", "").strip() or not self.cfg.get("chat_id", "").strip():
            result_text = "Final report saved locally; Telegram is not configured"
        elif self.last_tg_ok is True:
            result_text = "Final report saved and delivered to Telegram"
        elif self.last_tg_ok is False:
            result_text = "Final report saved locally; Telegram delivery failed"
        else:
            result_text = "Final report saved locally"
        self.active_lbl.configure(text=f"»  SESSION IDLE  |  {result_text}", fg=T["fg_mid"])
        self._trace(f"[trace] session stopped — {result_text.lower()}", "digest")
        self._refresh_stats()
        self._refresh_table()

    def _stop_ui_failed(self, error):
        if self._closing:
            return
        self.stopping = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.flush_btn.configure(state="disabled")
        self.status_lbl.configure(text="● STOP ERROR", fg=T["red"])
        self.active_lbl.configure(text=f"»  STOP FAILED  |  {clean_text(error, 100)}", fg=T["red"])
        self._trace(f"[stop] finalization failed: {error}", "err")
        messagebox.showerror("Ghostkey", f"Could not finish the session report:\n{error}")

    def _tick(self):
        if not self.running:
            return
        self._refresh_stats()
        # Rebuilding every row every second is unnecessary and can cause UI churn.
        self._ui_tick_count += 1
        if self._ui_tick_count % 2 == 0:
            self._refresh_table()
        self.root.after(1000, self._tick)

    def _worker_loop(self):
        poll = max(0.5, float(self.cfg.get("poll", 1.0)))
        first_sample = True
        while not self.stop_event.is_set():
            if not first_sample and self.stop_event.wait(poll):
                break
            first_sample = False
            if self._closing:
                break
            try:
                now = time.time()
                title, proc = get_foreground()
                # Stop wins over a sample that was in flight when the user clicked.
                if self.stop_event.is_set() or self._closing:
                    break
                with self.lock:
                    if self.last_tick:
                        delta = max(0.0, now - self.last_tick)
                        if self.current:
                            self.app_seconds[self.current[0]] = (
                                self.app_seconds.get(self.current[0], 0.0) + delta)
                    self.last_tick = now
                    # An empty sample means the active window could not be read
                    # (for example, desktop/lock screen). Close the previous app
                    # instead of silently leaving it marked active forever.
                    if not title and not proc:
                        if self.current:
                            self._close_app_locked(now)
                        continue
                    if self.current is None:
                        self._open_app_locked((proc or "unknown-process", title), now)
                    elif (proc or "?") != self.current[0]:
                        self._close_app_locked(now)
                        self._open_app_locked((proc or "?", title), now)
                    elif title != self.current[1]:
                        proc_name = self.current[0]
                        self.current = (proc_name, title)
                        self.app_titles[proc_name] = title or self.app_titles.get(proc_name, "")
                        if title:
                            history = self.title_history.setdefault(proc_name, [])
                            if not history or history[-1][1] != title:
                                history.append((datetime.now(), title))
                                # Bound memory in long sessions while keeping a useful report.
                                if len(history) > 500:
                                    del history[:len(history) - 500]
                                self._event_file("TITLE", proc_name, clean_text(title, 180))
                                self._trace(f"[title] {proc_name} — {clean_text(title, 150)}", "open")
                    # Periodic checkpoints are local-only. Keep session transitions
                    # intact so the Stop report includes the complete session.
                    if self.next_digest and now >= self.next_digest:
                        self._write_checkpoint_locked(now)
                        self.next_digest = now + self.interval_seconds()
            except Exception as exc:
                # A transient OS/process/API error should not terminate tracking.
                self._trace(f"[worker] recoverable error: {exc}", "err")
                self.stop_event.wait(0.5)

    def _write_checkpoint_locked(self, now):
        """Append a compact local checkpoint without clearing session data."""
        try:
            ensure_dir()
            elapsed = max(0, int(now - (self.start_time or now)))
            current = self.current[0] if self.current else "(none)"
            ranked = sorted(self.app_seconds.items(), key=lambda item: item[1], reverse=True)[:10]
            lines = [
                f"{datetime.now():%Y-%m-%d %H:%M:%S}  CHECKPOINT  session={self.session_id}",
                f"  elapsed={fmt_secs(elapsed)}  active_app={clean_text(current, 100)}",
            ]
            lines.extend(f"  app={clean_text(proc, 100)}  time={fmt_secs(seconds)}"
                         for proc, seconds in ranked)
            with open(EVENTS_FILE, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            self._trace(f"[checkpoint] local activity checkpoint written ({self.interval_seconds()}s interval)", "info")
        except OSError as exc:
            self._trace(f"[checkpoint] could not write local checkpoint: {exc}", "err")

    def _open_app_locked(self, new, now):
        proc, title = new
        self.current = new
        self.current_since = now
        self.opened.append(proc)
        self.events_session += 1
        self.events_window += 1
        if title:
            self.app_titles[proc] = title
            history = self.title_history.setdefault(proc, [])
            if not history or history[-1][1] != title:
                history.append((datetime.now(), title))
        else:
            self.app_titles.setdefault(proc, "")
        self._event_file("OPEN", proc, clean_text(title, 180))
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
        if not self.app_seconds and not self.opened and not self.closed and not self.title_history:
            return ""
        started = self.start_time or self.window_start or now
        duration = int(max(0.0, now - started))
        total = sum(self.app_seconds.values()) or 1.0
        ranked = sorted(self.app_seconds.items(), key=lambda kv: kv[1], reverse=True)
        if self.current:
            active = self.current[0]
            if self.current[1]:
                active = f"{active} — {clean_text(self.current[1], 110)}"
        else:
            active = "(none — session stopped)"

        lines = [
            "🟢 GHOSTKEY  |  SESSION ACTIVITY REPORT",
            f"🗓️  Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"🧩 Session ID: {self.session_id}",
            f"⏱️  Duration: {fmt_secs(duration)}",
            f"📍 Last active window: {active}",
            f"📊 Window events: {self.events_window}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📈 APPLICATION USAGE",
        ]
        if ranked:
            for idx, (proc, secs) in enumerate(ranked[:20], 1):
                pct = secs / total * 100
                lines.append(f"{idx}. {proc} — {fmt_secs(secs)} ({pct:.1f}%)")
        else:
            lines.append("No application time recorded.")

        lines.extend(["", "🧭 OBSERVED WINDOW / TAB TITLES"])
        if self.title_history:
            for proc, entries in sorted(self.title_history.items(),
                                        key=lambda kv: sum(self.app_seconds.get(kv[0], 0) for _ in [0]),
                                        reverse=True):
                lines.append("")
                lines.append(f"▸ {proc}")
                # Include all recorded unique title transitions up to the per-app cap.
                for stamp, title in entries:
                    lines.append(f"  • {stamp:%H:%M:%S} — {clean_text(title, 220)}")
        else:
            lines.append("No window titles captured.")

        lines.extend(["", "🔁 SESSION TRANSITIONS"])
        lines.append("Opened: " + dedupe_join(self.opened, limit=30))
        lines.append("Closed: " + dedupe_join(self.closed, limit=30))
        lines.extend([
            "",
            "🛡️ COLLECTION NOTES",
            "• Captures foreground application names and visible window titles at polling intervals.",
            "• Browser titles may identify the selected tab/page (for example, YouTube or LinkedIn).",
            "• This does not capture typed text, page contents, or complete browser history; brief title changes between polls may be missed.",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📨 Delivery: {'Local log + Telegram' if self.cfg.get('bot_token') and self.cfg.get('chat_id') else 'Local log only (Telegram not configured)'}",
        ])
        return "\n".join(lines)

    def _flush_locked(self, reason, now=None):
        now = now or time.time()
        text = self._compose_digest_locked(now)
        self.opened = []
        self.closed = []
        self.events_window = 0
        self.window_start = now
        if not text and reason == "final":
            # A Stop click always produces a final report, even if no foreground
            # window could be sampled during this session.
            started = self.start_time or now
            text = "\n".join([
                "🟢 GHOSTKEY  |  SESSION ACTIVITY REPORT",
                f"🗓️  Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
                f"🧩 Session ID: {self.session_id}",
                f"⏱️  Duration: {fmt_secs(now - started)}",
                "🔴 No foreground application events were captured in this session.",
                "🛡️ Window-title polling does not capture keystrokes, page contents, or complete browser history.",
                f"📨 Delivery: {'Local log + Telegram' if self.cfg.get('bot_token') and self.cfg.get('chat_id') else 'Local log only (Telegram not configured)'}",
            ])
        if not text:
            self._post_ui(lambda: self._trace("[digest] nothing to flush", "info"))
            return None
        try:
            ensure_dir()
            with open(DIGESTS_FILE, "a", encoding="utf-8") as f:
                f.write(text + "\n\n")
        except Exception:
            pass
        self.digests += 1
        self.last_digest = text
        self.last_digest_time = datetime.now()
        self._post_ui(lambda t=text, r=reason: self._show_digest(t, r))
        return self.io_pool.submit(self._deliver_telegram, text, reason)

    def _deliver_telegram(self, text, reason):
        tok = self.cfg.get("bot_token", "").strip()
        chat = self.cfg.get("chat_id", "").strip()
        if not tok or not chat:
            with self.lock:
                self.last_tg_ok = None
            self._post_ui(lambda: self._trace("[tg] skipped — not configured", "info"))
            return
        ok, err = send_telegram(tok, chat, text)
        if ok:
            with self.lock:
                self.tg_ok += 1
                self.last_tg_ok = True
            self._post_ui(lambda: self._trace(
                f"[tg] sent ({len(text)} chars, {reason})", "digest"))
        else:
            with self.lock:
                self.tg_fail += 1
                self.last_tg_ok = False
            try:
                with open(BUFFER_FILE, "a", encoding="utf-8") as f:
                    f.write(text + "\n\n")
            except Exception:
                pass
            self._post_ui(lambda e=err: self._trace(f"[tg] failed: {e}", "err"))
        self._post_ui(self._refresh_stats)
        if reason == "final":
            if ok:
                self._post_ui(lambda: self._trace("[tg] final session report delivered successfully", "digest"))
            else:
                self._post_ui(lambda e=err: self._trace(
                    f"[tg] final report delivery failed; report retained locally: {e}", "err"))

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
        self.io_pool.submit(self._deliver_telegram, self.last_digest, "resend")

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
                self._post_ui(lambda: self._trace("[tg] test ok", "digest"))
                self._post_ui(lambda: messagebox.showinfo("telegram", "test message sent."))
            else:
                self._post_ui(lambda: self._trace(f"[tg] test failed: {err}", "err"))
                self._post_ui(lambda e=err: messagebox.showerror("telegram", f"failed:\n{e}"))
        self.io_pool.submit(_w)

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
        self._trace(f"[cfg] saved · local checkpoint every {value}s · final Telegram report on Stop", "info")
        messagebox.showinfo(APP_NAME, "Settings saved. Local checkpoints use the selected interval; the detailed Telegram report is sent only when you press Stop.")

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
        if self._closing:
            return
        # Signal workers first and close the UI without waiting on network I/O.
        self._closing = True
        self.running = False
        self.stopping = False
        self.stop_event.set()
        try:
            self._event_file("GUI", APP_NAME, "closed")
        except Exception:
            pass
        try:
            self.cfg["geometry"] = self.root.geometry()
            save_config(self.cfg)
        except Exception:
            pass
        try:
            self.io_pool.shutdown(wait=False, cancel_futures=True)
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
