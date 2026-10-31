# Security Model

A short, practical view of what Ghostkey protects and what it does not.

---

## Trust boundaries

| Boundary | Trust |
|----------|-------|
| Local account and filesystem | Trusted, but other users on the device may read files if permissions allow |
| Telegram Bot API | Third party; reports leave the device once sent |
| Foreground window titles | Untrusted input; may contain arbitrary Unicode and misleading text |
| Network | Untrusted; requests use HTTPS with bounded timeouts |

## Controls in place

- No inbound sockets, no listening ports, no remote control surface.
- TLS via `requests` for Telegram delivery.
- Operator-supplied credentials only; no embedded secrets.
- Append-only local logs; no execution of captured strings.
- UI text is inserted into Tk widgets as data, not evaluated.
- Reports are size-limited by chunking (4,000 characters per message).

## Not provided

- Encryption at rest.
- Tamper detection or signed logs.
- Multi-user isolation beyond OS file permissions.
- Role-based access control.
- Compliance certification.

## Operator responsibilities

1. Restrict the data directory to the intended account.
2. Use a dedicated bot and private chat.
3. Review reports before sharing; redact titles.
4. Define a retention period and delete logs accordingly.
5. Verify authorization before monitoring any device or person.

## Incident response

- **Token exposed:** revoke in @BotFather, issue a new token, update config,
  inspect recent chat messages.
- **Logs exposed:** delete and re-evaluate retention; notify affected people if
  required by policy or law.
- **Suspected code vulnerability:** follow [SECURITY.md](../SECURITY.md) and
  report privately.
