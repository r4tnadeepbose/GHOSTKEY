# Keybindings

| Keys | Action | Scope |
|------|--------|-------|
| `F9` | Start or stop the session | Global |
| `F5` | Flush + send a digest | Global |
| `Ctrl+K` | Focus the trace filter | Global |
| `Esc` | Clear the trace filter | Global |
| `Double-click` | Filter trace by the selected process | Runtime table |

Notes:

- `F5` only works while a session is running.
- `F9` while finalizing is ignored until the previous stop completes.
- The filter is case-insensitive and matches against the full rendered line,
  including the timestamp.
