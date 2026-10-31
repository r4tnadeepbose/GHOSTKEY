# Contributing to Ghostkey

Thanks for taking the time to contribute. Ghostkey is a small, privacy-sensitive desktop utility. Please read this document before opening a pull request.

---

## Ground rules

1. **Only monitor devices you own or are authorized to monitor.** Contributions that make covert monitoring, credential theft, or stealth installation easier will be rejected.
2. **Never include real activity data.** Issues, logs, screenshots, and pull requests must not contain live bot tokens, chat IDs, window titles from real sessions, or personal data.
3. **Keep the tool honest.** The dashboard and README must not overstate what Ghostkey collects or guarantees.
4. **Prefer minimal, reviewable changes.** A focused patch is easier to review than a wide rewrite.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Development setup

```bash
git clone https://github.com/r4tnadeepbose/GHOSTKEY.git
cd GHOSTKEY

python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# Linux / macOS
# source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Run the app:

```bash
python scan.py
```

Run checks:

```bash
python -m ruff check .
python -m unittest discover -s tests -v
python -m py_compile scan.py
```

Optional: install the git hooks with `pre-commit install`.

---

## What to work on

- Good first issues are labelled `good first issue`.
- UI work lives in `GhostkeyApp._build_ui`, the `_tab_*` methods, and the `T` palette near the top of [scan.py](scan.py).
- Tracking backends live in `_get_foreground_windows` and `_get_foreground_linux`.
- Docs live in [docs/](docs/).

If you plan a large change, open an issue first so the design can be discussed.

---

## Code style

- Python 3.10+, 4-space indentation, lines up to ~110 characters.
- Standard library first; the only runtime dependency is `requests`.
- Keep Tk work on the UI thread. Background work must publish callbacks through `ui_queue`.
- Never log credentials. Use `clean_text` when writing window titles to the UI.
- New UI colors go through the `T` palette — no one-off hex literals in widget calls.
- Keep comments for *why*, not *what*.

---

## Privacy requirements for changes

Any change touching collection, storage, or delivery must answer:

- What new data is captured, and where does it go?
- Is it written to disk, and for how long?
- Can it be exported or transmitted off-device?
- Does the README still describe the behavior accurately?

Update [readme.md](readme.md) and [PRIVACY.md](PRIVACY.md) when behavior changes.

---

## Commit messages

Use short imperative subjects, optionally scoped:

```
ui: add amber phosphor palette
tracker: ignore empty foreground samples
docs: document telegram message splitting
```

Explain the *why* in the body when it is not obvious.

---

## Pull request checklist

- [ ] Change is scoped and described.
- [ ] `ruff check` and unit tests pass.
- [ ] UI changes were launched and exercised manually.
- [ ] No tokens, chat IDs, or real activity data are included.
- [ ] Docs updated if behavior changed.
- [ ] Legal/privacy implications considered.

---

## Reporting bugs safely

Include OS, Python version, Ghostkey commit, reproduction steps, expected/actual behavior, and a **sanitized** traceback. Redact tokens, chat IDs, and window titles before posting.
