# Changelog

All notable changes to Ghostkey are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed

- **UI** — restyled the dashboard as a muted vintage-terminal console:
  warm charcoal surfaces, amber phosphor accent, corner-ticked panels,
  shell-prompt section headers, bracketed control labels, session ID and
  clock readouts in the header.
- **UI** — status strip now uses semantic colors (dim idle, amber starting,
  green active, red failure) instead of a single alarm color.
- **Docs** — added repository scaffolding: license, contributing guide,
  code of conduct, security and privacy policies, architecture and design
  notes, scripts, tests, and CI workflows.

### Added

- Unit tests for formatting and helper functions.
- `Makefile`, `pyproject.toml`, dev requirements, pre-commit config.
- GitHub issue/PR templates, CI and CodeQL workflows, Dependabot config.
- Package/setup scripts for Windows and POSIX shells.

---

## [1.0.0] — 2026-10-29

### Added

- Foreground application and window-title sampling with transition tracking.
- Per-application runtime table with share bars and sortable columns.
- Live trace pane with text filtering.
- Local checkpoint log, session digest generation on Stop.
- Optional Telegram delivery of the final session report.
- Settings tab for checkpoint interval, autostart, and data-directory actions.
- Telegram tab with token/chat configuration and connectivity test.
- Export, copy, resend, and open-log actions.

### Notes

- Telemetry is approximate and sampled; brief foreground changes can be missed.
- Windows is the supported tracking platform. Linux relies on `xdotool`
  for X11/XWayland windows and does not see native Wayland applications.
