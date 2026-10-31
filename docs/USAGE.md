# Usage

Ghostkey is a manual session recorder. It does nothing until you press **Start**,
and it produces its final report when you press **Stop**.

---

## First run

```bash
python scan.py
```

The dashboard opens in an idle state. The footer shows the data directory
(`~/.ghostkey` or `%USERPROFILE%\.ghostkey`).

## Starting a session

1. Press **`[ ▶ START ]`** (or `F9`).
2. The status dot turns green and the active strip shows the current process
   and window title once the first sample lands.
3. Use applications normally. Events appear in the trace pane within a second.
4. Local checkpoints are written at the configured interval (default 30 s).
   They are **local only** — no message is sent.

## Stopping a session

Press **`[ ■ STOP ]`** (or `F9`).

Ghostkey:

1. Stops sampling.
2. Accounts for the final in-flight interval.
3. Composes the session report and appends it to `digests.log`.
4. Sends it to Telegram **if** credentials are configured.
5. Shows the delivery outcome in the active strip.

Delivery can fail (network, credentials, Telegram limits). The report is always
kept locally; check the trace for `[tg]` lines.

## The tabs

### 01 · trace

Live event stream plus the runtime table.

- Filter with the `$ grep` field (`Ctrl+K` to focus, `Esc` to clear).
- Double-click a row to filter the trace by that process name.
- Click table headings to sort; click again to reverse.
- `OPEN` in amber, `CLOSE` in red, digests in warm yellow, errors in red.

### 02 · output

The most recent digest, rendered read-only.

- **FLUSH** — compose and send a report mid-session without stopping.
- **EXPORT** — save the digest to a `.txt` file.
- **COPY** — copy the digest to the clipboard.
- **RESEND** — send the last digest to Telegram again.

### 03 · telegram

Bot token and chat ID fields, plus **SAVE** and **TEST**.

- The token is masked; use *show* to verify it.
- `TEST` sends a small sample message and reports the result.
- See [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md).

### 04 · settings

- Local checkpoint interval (5–3600 s).
- Start tracing automatically on launch.
- Save settings.
- Open the data directory or show file paths.

## Reading the runtime table

| Column | Meaning |
|--------|---------|
| `#` | Rank by current sort |
| `APP` | Process image name (`chrome.exe`) |
| `ACTIVE WINDOW` | Last observed title for that process |
| `TIME` | Approximate foreground time |
| `SHARE` | Percentage of recorded time + bar |

Time is approximate: sampling, not a stopwatch. Switching windows quickly can
lose short intervals.

## Clearing state

`[ ▤ CLEAR ]` resets counters and empties the trace after confirmation. It does
**not** delete files in the data directory.

## Closing the app

Closing the window stops tracking and saves window geometry. An active session
is **not** finalized or sent on close; stop the session first if you need a
report.

## Privacy reminders

- The trace and reports contain window titles. They can reveal documents,
  sites, and account names.
- Do not share screenshots or logs without redacting `config.json` values.
- Only run Ghostkey on devices you own or are authorized to monitor.
