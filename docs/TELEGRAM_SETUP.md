# Telegram Setup

Ghostkey can send the final session report to a chat you control. Delivery is
optional; without credentials everything stays local.

---

## 1. Create a bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram.
2. Send `/newbot` and follow the prompts.
3. Copy the **bot token** (format `123456789:ABC…`).

## 2. Start a conversation with the bot

A bot cannot message a chat that has never contacted it. Open your new bot and
press **Start** (or send `/start`).

## 3. Find the chat ID

- Message [@userinfobot](https://t.me/userinfobot) for your numeric user ID.
- For a group, add the bot to the group and check the group ID (usually a
  negative number).

## 4. Configure Ghostkey

1. Open the **03 · telegram** tab.
2. Paste the bot token and chat ID.
3. Press **`[ SAVE ]`**.
4. Press **`[ TEST ]`** and confirm the sample message arrives.

Credentials are written to `~/.ghostkey/config.json` in plain text.

## 5. Verify delivery

Run a short session, press **Stop**, and watch for:

```
[tg] sent (… chars, final)
```

or

```
[tg] final report delivery failed; report retained locally: …
```

The report is always saved locally first.

---

## Behavior

- **When:** one report on Stop; optionally one per manual Flush; Test sends a
  fixed sample.
- **No recurring digest.** Checkpoints are local-only.
- **Size:** messages are split into 4,000-character chunks. Very long title
  histories may produce several messages.
- **Failure:** failed reports are appended to `buffer.txt`; use **RESEND** or
  inspect the trace.

## Security

- The token is a password. Anyone with it can control the bot.
- Use a dedicated bot and a private chat.
- Do not commit `config.json` or paste tokens into issues.
- If leaked, revoke the token with `/revoke` in @BotFather and reconfigure.
- Telegram is a third-party service; reports leave your device and are subject
  to Telegram's terms and retention.
