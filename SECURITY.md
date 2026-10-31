# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ |
| < 1.0   | ❌ |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report privately through GitHub Security Advisories on the repository
(Security → Advisories → *Report a vulnerability*), or contact the maintainer
listed in [pyproject.toml](pyproject.toml).

Include:

- Affected version or commit.
- Operating system and Python version.
- Steps to reproduce.
- Impact and any suggested mitigation.
- Whether real credentials or activity data were exposed (never paste them).

You can expect an acknowledgement within a few days. Fixes are coordinated
privately before disclosure.

---

## Threat model

Ghostkey is a local activity dashboard, not a hardened monitoring product.

**In scope**

- Leakage of the Telegram bot token or chat ID from local files or the UI.
- Delivery of reports to an unintended chat due to configuration handling.
- Local file permission issues exposing activity logs to other users on the device.
- Crashes or hangs caused by malformed window titles or network failures.
- Injection or escape issues in UI rendering of captured text.

**Out of scope**

- Detection evasion, stealth installation, or making the tool harder to notice.
- Bypassing operating-system monitoring consent or access controls.
- Attacks requiring an already-compromised machine or administrator privileges.
- Availability of the Telegram platform itself.

---

## Credential handling

- Treat the bot token like a password. Anyone with it can control the bot.
- Credentials are stored in `~/.ghostkey/config.json` in plain text. Protect the
  file with OS account permissions; do not sync the data directory to public cloud storage.
- Never commit `config.json`, tokens, chat IDs, or exported reports.
- If a token leaks, revoke it via [@BotFather](https://t.me/BotFather) and issue a new one.

## Hardening checklist

- [ ] Use a dedicated bot and a private chat.
- [ ] Restrict the data directory to your user account.
- [ ] Keep Python and `requests` up to date.
- [ ] Review the source before running forks or third-party builds.
- [ ] Delete `events.log`, `digests.log`, and `buffer.txt` when no longer needed.

## Known limitations

- Window titles may contain sensitive text; reports inherit that sensitivity.
- Delivery is best-effort and depends on network and Telegram availability.
- The application is not tamper-proof and does not provide an audit trail.
