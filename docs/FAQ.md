# FAQ

**Does Ghostkey record keystrokes?**
No. It samples the foreground process name and the visible window title. The
name is historical; the tool does not hook the keyboard.

**Does it capture screenshots or clipboard?**
No.

**Is it a full browser history?**
No. It sees the window title of the selected tab at sampling time. It cannot
enumerate tabs, read the address bar, or capture page content.

**Does it start automatically?**
Only if you enable “start tracing automatically when the app opens” in Settings.

**Does it run in the background after closing?**
No. There is no service, tray icon, or scheduled task.

**Where is data stored?**
`~/.ghostkey` (`%USERPROFILE%\.ghostkey` on Windows). See
[DATA_LAYOUT.md](DATA_LAYOUT.md).

**Is data encrypted?**
No. Protect the directory with OS account permissions.

**When is data sent anywhere?**
Only when you press Stop (final report), Flush (manual), or Test. Telegram is
the only network destination, and only when configured.

**Can I use it on Linux?**
The UI runs; active-window tracking needs `xdotool` and an X11 session, and
native Wayland windows are invisible. Windows is the supported target.

**What happens if Telegram fails?**
The report is kept locally and appended to `buffer.txt`. The trace shows the
error. You can press RESEND later.

**Is there a CLI or headless mode?**
No. The application is a desktop dashboard.

**Can I redistribute or modify it?**
Yes, under the MIT License. Keep the copyright notice.

**Is it legal to use at work or school?**
That depends on your jurisdiction and policies. The operator is responsible for
authorization, notice, and consent. See the notice in the README.
