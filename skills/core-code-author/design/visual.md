# Visual style

The panel is dark, dense, and mostly monochrome so that the few coloured
things mean something. These are the rules that keep that true.

## The glow is for the committing action

A cyan glow (`box-shadow: 0 0 20px -8px var(--color-accent)`) marks **the one
action a page or section exists to perform** — the Apply that commits a form,
the Save that ends an edit. It is what lets someone find that button without
reading the page.

Everything else drawn in the accent is drawn **without** it:

- toggles and switches — they report a setting, they are not the point of the
  page
- icon pickers and other selections — being chosen is not being urgent
- secondary actions in a row: Activate, Wake-on-LAN, Open terminal, Test
- inputs on focus, and the keyboard focus ring, which is a ring
  (`0 0 0 1px`), not a halo

Spending the glow on every accent-coloured control leaves nothing for the
committing action, and the page stops having an obvious next step.

In practice: `.button--primary` carries the accent; the glow comes from
sitting in `.page_actions`, `.apply_bar` or `.settings_group_actions`, or
from `.button--commit` where a footer's save button needs it by name.

## Colour carries one meaning each

- **accent (cyan)** — what this page is for, and what is currently selected
- **ok (green)** — installed, running, healthy; also the affirmative half of
  a destructive pair (`button--ok` beside `button--danger`)
- **warn (amber)** — a step in flight, unsaved changes, a refusal that can be
  overridden
- **error (red)** — failed, stopped, and the destructive action itself

A button that removes something is red-outlined whether it says Uninstall,
Deactivate or Delete. A button with no outline reads as one that cannot be
pressed, so only disabled controls lose theirs.

## Motion is for what is happening now

Pulsing and flowing dashes mean live: a device reporting, traffic moving, a
lockout counting down. Nothing decorative moves.

## Buttons come in three tiers

- `button--primary` — the action a section exists for. This is the tier the
  glow above belongs to.
- `button` (bordered) — standalone secondary actions: Re-enroll, Join, Add
  container, Activate.
- `button--ghost` (borderless) — repeated row-level actions where borders
  would be noise: a per-row Remove, a Journal toggle, the Close on a task
  log, and the Reset or Cancel sitting beside a primary in the same row.

Never a borderless button for a standalone action: it reads as text until
hovered. A borderless control reads as one that cannot be pressed, so a
disabled button is the other thing allowed to lose its border.

## Frames

- One framed group (`settings_group`) per unit of change, closed by one apply
  bar. Anything unapplied lights the frame (`settings_group--dirty`).
- **The frame and its apply bar answer one question**: is there something here
  that has not been applied. A lit bar over an unlit frame is a box telling two
  stories, and it happens wherever the bar has a term the frame does not — a
  change written straight through with no draft behind it, a staged password.
  The bar may be the *stricter* of the two, staying dark on a value that is not
  valid yet, but never the more generous.
- Surface ramp: page background → `--color-surface` for the unit of change →
  `--color-bg` for its contents → `--color-elevated` for emphasis.
- Destructive confirmation is a red-bordered box inside the card, and deleting
  data requires typing the name back.

## Text and values

- `--font-mono` for addresses, names, units and counts; Inter for prose.
- Badges say one word: `serving`, `declared`, `not joined`.
- Status dots pulse only for something running right now.

## Live sections

A section showing live state carries the pulsing `live` badge and polls
itself; it never has a manual reload button beside it.
