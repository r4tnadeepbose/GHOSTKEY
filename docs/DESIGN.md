# Interface Design

Ghostkey borrows the *feel* of an old terminal without turning into a neon
screensaver: warm charcoal paper, one amber phosphor accent, monospace type,
and quiet rules. Surfaces stay flat; texture comes from spacing and corner
ticks, not glow.

---

## Principles

1. **One accent.** Amber marks interactive and active elements. Green, amber,
   and red appear only as semantic status colors.
2. **Flat, edge-lit panels.** No gradients, no shadows. A 1 px border plus
   eight-pixel corner ticks frame each panel.
3. **Type does the work.** Consolas/Cascadia, uppercase tracking for labels,
   lowercase for prose. Numerals are tabular so counters do not jitter.
4. **Terminal grammar.** Section headers read as shell prompts
   (`$ tail -f trace.log`), controls use brackets (`[ ▶ START ]`), the status
   strip leads with `»`.
5. **Quiet motion.** A single blinking cursor and a pulsing status dot. No
   scanlines, no glitch effects, no animated borders.

## Palette

| Token | Hex | Use |
|-------|-----|-----|
| `bg` | `#0a0908` | Window background |
| `panel` | `#12100d` | Card and tab surfaces |
| `panel2` | `#191611` | Buttons, headings, alternating rows |
| `panel3` | `#221e17` | Hover and selection fills |
| `border` | `#2d2820` | Quiet rules and panel outline |
| `border2` | `#4a4132` | Emphasized outlines |
| `fg` | `#e9e0cf` | Primary text (warm off-white) |
| `fg_mid` | `#c6bba6` | Secondary text and trace body |
| `dim` | `#8b806d` | Labels, helper copy |
| `dimmer` | `#5d5546` | Footer, timestamps, disabled |
| `accent` | `#e0a458` | Amber phosphor: prompts, values, active tab |
| `accent2` | `#6b4e26` | Deep amber for pressed/edge states |
| `accent_soft` | `#7a6238` | Panel corner ticks |
| `accent_ink` | `#1a1206` | Text on solid amber buttons |
| `green` | `#93b56e` | Active session, successful relay |
| `warn` | `#d8bd77` | Starting and finalizing |
| `red` | `#cf6f5e` | Errors, close events |
| `red_hover` | `#b85a49` | Destructive hover |

Contrast: `fg` on `bg` ≈ 12:1, `dim` on `panel` ≈ 4.9:1, amber on `panel`
≈ 7:1. All primary text meets WCAG AA.

## Typography

| Role | Face | Size |
|------|------|------|
| Brand | Cascadia Mono → Consolas | 20 bold |
| Stat value | same | 12 bold |
| Body / trace | same | 9 |
| Labels / meta | same | 8 |

The app prefers `Cascadia Mono`, `Cascadia Code`, `JetBrains Mono`, then
`Consolas` (see `pick_fonts`).

## Layout

```
┌ header ─ brand · cursor · clock · SID · status ┐
│ thin warm rule                                 │
│ stat cards ×5 (corner-ticked)                  │
│ active strip          last digest » hh:mm:ss   │
│ [ ▶ START ] [ ■ STOP ] [ ➤ FLUSH ] …   [ ▣ LOG ]│
│ ┌ tabs: 01·trace 02·output 03·telegram 04·settings
│ │ prompt header                                 │
│ │ content                                       │
│ └───────────────────────────────────────────────┘
│ [F9] …                    metadata note · data dir
```

- Minimum window 1100 × 720; default 1440 × 900.
- Five stat cards share the row equally; the active strip spans full width.
- Trace tab splits vertically: live stream above, app runtime table below.

## Components

**Stat card** — icon left, `:: LABEL` above a large amber value. Uptime is the
only live-updating value; others change on events.

**Active strip** — one line of state: `» ACTIVE | process — title`. Color
encodes state, text carries the detail. Last digest timestamp sits right.

**Control bar** — primary action is solid amber ink-on-amber; other actions are
outlined charcoal that warm to amber on hover; stop uses a dim red treatment
only while armed.

**Trace pane** — timestamped lines, color-coded by tag (`open`, `close`,
`digest`, `err`). Filter is an inline grep with a live `hits/total` readout.

**Runtime table** — sortable rank / app / window / time / share columns.
Share uses a 10-cell `▰▱` bar so proportions read at a glance.

**Digest view** — monospace report with amber headers and dim separators.

## Interaction states

| State | Treatment |
|-------|-----------|
| Idle | dim status dot, dim active strip |
| Starting | amber status, `» STARTING` |
| Active | green pulsing dot, green strip |
| Finalizing | amber strip, controls disabled |
| Error | red strip/status, message box |

## What to avoid

- Saturated cyan/magenta or glow shadows (breaks the muted brief).
- More than one accent hue for non-semantic elements.
- Emoji in the chrome; the report payload may contain them for legibility in
  Telegram, but the dashboard stays ASCII/box-drawing.
