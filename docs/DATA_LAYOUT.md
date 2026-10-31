# Data Layout

Everything Ghostkey writes lives in one directory:

| Platform | Path |
|----------|------|
| Windows | `%USERPROFILE%\.ghostkey` |
| Linux / macOS | `~/.ghostkey` |

The directory is created on first launch. Files are plain UTF-8; nothing is
encrypted.

---

## Files

| File | Format | Contents |
|------|--------|----------|
| `config.json` | JSON | Settings plus bot token and chat ID (plain text) |
| `events.log` | text lines | `OPEN`, `CLOSE`, `TITLE`, `SESSION`, `CHECKPOINT`, `GUI` records |
| `digests.log` | text blocks | One report per flush/stop, separated by blank lines |
| `buffer.txt` | text blocks | Reports that failed to deliver via Telegram |

### `config.json`

```json
{
  "interval": 30,
  "poll": 1.0,
  "start_on_launch": false,
  "geometry": "1440x900+120+80",
  "bot_token": "…",
  "chat_id": "…"
}
```

### `events.log` sample

```
2026-10-31 14:22:05  GUI   ghostkey opened
2026-10-31 14:22:11  SESSION  0x1A2B3C  started
2026-10-31 14:22:13  OPEN   chrome.exe  Inbox — mail.example
2026-10-31 14:23:48  TITLE  chrome.exe  Pull request #42
2026-10-31 14:24:02  CLOSE  chrome.exe  Inbox — mail.example  (01:49)
2026-10-31 14:24:30  CHECKPOINT  session=0x1A2B3C
```

### `digests.log` sample

```
GHOSTKEY  |  SESSION ACTIVITY REPORT
Generated: 2026-10-31 14:30:00
Session ID: 0x1A2B3C
Duration: 00:07:49
...
```

## Growth

- `events.log` grows with every observed transition and checkpoint. At a 30 s
  checkpoint interval, expect a few hundred lines per hour of active use.
- `digests.log` grows by one report per flush and per stop.
- `buffer.txt` only grows when delivery fails.

## Sensitivity

Window titles can include email subjects, document names, URLs, account names,
and search queries visible in a title bar. Treat every file in this directory as
sensitive personal data.

## Retention

Delete files when they are no longer needed and when deletion is permitted by
your retention obligations:

```powershell
# remove individual logs
Remove-Item "$env:USERPROFILE\.ghostkey\events.log"
```

```bash
rm ~/.ghostkey/events.log
```

To remove everything, delete the directory. Revoke the bot token if
`config.json` may have been exposed.

## Backups

If you back up the directory, exclude `config.json` unless the backup target is
encrypted and access-controlled. Never sync the data directory to a public or
shared cloud folder.
