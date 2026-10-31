# Linux Notes

The dashboard itself is portable (Tkinter). Active-window tracking is only
partially supported.

---

## What works

| Environment | Active window | Notes |
|-------------|---------------|-------|
| Windows | ✅ Supported | Win32 API, primary target |
| X11 desktops | ⚠️ Via `xdotool` | Install `xdotool` |
| XWayland apps | ⚠️ Sometimes | Visible to `xdotool` |
| Native Wayland apps | ❌ Not visible | Compositor sandboxing |

Ghostkey does not attempt to bypass Wayland's restrictions.

## Dependencies

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-tk xdotool

# Fedora
sudo dnf install -y python3 python3-pip python3-tkinter xdotool

# Arch
sudo pacman -Syu python python-pip tk xdotool
```

## Running

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scan.py
```

The app warns in the trace when:

- `xdotool` is missing,
- `DISPLAY` is unset (no X session),
- or Wayland is detected (native apps will be invisible).

## Wayland

Global active-window queries are intentionally restricted by compositors.
Workarounds generally require desktop-specific extensions or portals and are
not implemented here. If you need reliable Linux tracking, contribute a
backend for your compositor with tests.

## Known display issues

- If the window does not open, confirm you are in a graphical session and that
  `python3-tk` is installed.
- On HiDPI setups, geometry is stored in physical pixels; delete the `geometry`
  key in `config.json` if the window opens off-screen.
