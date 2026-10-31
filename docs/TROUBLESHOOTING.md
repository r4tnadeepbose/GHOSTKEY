# Troubleshooting

## The dashboard does not open

- Confirm Python 3.10+ and Tkinter: `python -c "import tkinter; print('ok')"`.
- Linux: install `python3-tk` and run inside a graphical session.
- Windows: run from Command Prompt or PowerShell, not a service session.
- If the window is off-screen, delete `"geometry"` from
  `~/.ghostkey/config.json`.

## Tracking stays on STARTING

1. Bring a normal application window to the foreground.
2. Wait one polling interval (default 1 s).
3. Check the trace for `[worker]` errors.
4. Linux: verify `xdotool` is installed and `DISPLAY` is set. Native Wayland
   windows are not visible.
5. Lock screen or desktop-only foreground returns an empty sample, which is
   expected.

## No rows in the runtime table

The table refreshes every two ticks. If the session was just started, wait a
moment. If the table is empty for a long time, tracking is not receiving
foreground data — see above.

## Telegram message not received

1. **Test TG** and read the exact error in the trace.
2. Verify the token and chat ID belong to the same bot/chat.
3. Send `/start` to the bot from the destination account.
4. For groups, ensure the bot is a member and check group privacy settings.
5. Confirm internet access; corporate proxies can block `api.telegram.org`.
6. Check `buffer.txt` — failed reports are stored there.

## “requests not installed”

```bash
python -m pip install requests
```

The status bar and trace warn at startup. Local logging still works.

## Stop seems to hang

Stop waits (off the UI thread) for the tracker to exit and for delivery to
finish. Network calls have bounded timeouts, but a slow network can take a few
seconds. Controls stay disabled until finalization completes.

## Report is empty

A session where no foreground window could be sampled still produces a final
report stating that no events were captured. If you expected data, check the
platform limitations.

## Clear/reset did not delete old logs

`[ ▤ CLEAR ]` resets in-memory counters only. Delete files under
`~/.ghostkey` to remove history.

## High CPU or UI stutter

- Increase the checkpoint interval in Settings.
- Keep the filter empty during heavy logging.
- Very high-frequency foreground switching generates many events by design.

## Reporting a bug

Run:

```bash
python scripts/check_env.py
```

Include the output plus a sanitized trace excerpt. Remove tokens, chat IDs, and
window titles first.
