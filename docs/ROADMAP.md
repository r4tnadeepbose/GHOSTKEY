# Roadmap

Direction is deliberately narrow: a trustworthy local session dashboard with a
quiet, readable interface.

---

## Near term

- [ ] Extract the palette/theme into a small `theme` module so alternate
      phosphor variants (green, paper-white) can be added without touching layout.
- [ ] Persist column widths and window split position.
- [ ] Add a session summary card on the Output tab (top apps, transitions).
- [ ] Improve the empty state on the runtime table with a one-line hint.

## Later

- [ ] Optional Linux backend for common compositors (with tests).
- [ ] CSV export alongside the text digest.
- [ ] Configurable polling rate in Settings.
- [ ] Accessibility pass: focus rings, screen-reader labels, keyboard-only tab flow.

## Non-goals

These will not be added:

- Keystroke logging, clipboard capture, screenshots, or audio.
- Stealth mode, process hiding, or detection evasion.
- Silent auto-install, persistence, or telemetry to the author.
- Any off-device transmission that is not user-triggered Telegram delivery.
- A guaranteed browser-history reconstruction.

## Design guardrails

- One accent color, warm neutrals, monospace type.
- Flat surfaces with corner ticks; no gradients or glow.
- Every data flow documented in the README and [PRIVACY.md](../PRIVACY.md).
