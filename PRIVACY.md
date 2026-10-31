# Privacy Notice

Ghostkey runs locally. It does not contain analytics, crash reporting, or any
phone-home channel to the author. Data leaves the device only when you configure
Telegram and trigger a send.

This notice describes what the software does; it does not make any deployment
lawful. The operator is responsible for notice, consent, and compliance.

---

## What is collected

While a session is running, Ghostkey samples the foreground window at roughly
1 Hz and records:

| Data | Example | Where it is stored |
|------|---------|--------------------|
| Timestamp | `2026-10-31 14:22:05` | `events.log`, `digests.log` |
| Process name | `chrome.exe` | `events.log`, `digests.log` |
| Visible window title | `Inbox — mail.example` | `events.log`, `digests.log` |
| Open/close transitions | `OPEN chrome.exe` | `events.log`, `digests.log` |
| Approximate foreground time | `chrome.exe 00:14:32` | `digests.log` |

Window titles can reveal document names, account identifiers, website tabs, and
other sensitive text. Treat every report as sensitive.

## What is not collected

- Keystrokes or typed text.
- Clipboard contents.
- Screenshots, audio, or camera input.
- Page contents or complete browser history.
- Files, passwords, or credentials.

Brief title changes between samples can be missed, and browser titles describe
only the selected tab.

## Local storage

All data lives in `~/.ghostkey` (`%USERPROFILE%\.ghostkey` on Windows):

- `config.json` — settings and, if configured, the Telegram bot token and chat ID.
- `events.log` — append-only event stream and checkpoints.
- `digests.log` — session reports.
- `buffer.txt` — reports that failed to deliver via Telegram.

Nothing in that directory is encrypted. Protect it with OS account permissions
and avoid syncing it to shared or public storage.

## Third parties

When Telegram delivery is configured, the final session report is sent to the
Telegram Bot API, operated by Telegram. That message is subject to Telegram's
terms, retention, and account settings. Ghostkey does not control Telegram.

No other network requests are made by the application.

## Retention and deletion

You decide how long data is kept. To remove everything:

```bash
# Windows PowerShell
Remove-Item -Recurse -Force "$env:USERPROFILE\.ghostkey"

# Linux / macOS
rm -rf ~/.ghostkey
```

Revoke the bot token through BotFather if it may have been exposed.

## Children and workplace use

Do not deploy Ghostkey on shared, school, client, or employee devices without
the approvals, notice, and consent required by applicable law and policy.

## Contact

Open a private security advisory for privacy-relevant defects. Do not attach
real activity data.
