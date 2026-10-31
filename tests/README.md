# Tests

Unit tests cover pure helpers (formatting, text cleaning, deduplication,
configuration defaults, palette integrity) and the Telegram guard paths.
They do not open a window, sample the desktop, or touch the network.

```bash
python -m unittest discover -s tests -v
```

Tests must never read or write real activity data. Use temporary directories
if a test ever needs disk access.
