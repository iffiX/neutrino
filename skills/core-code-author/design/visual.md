# Visual style

The panel is dense and mostly monochrome, in a dark palette or a light one,
so that the few coloured things mean something. These are the rules that keep
that true in both.

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

## Two palettes on one token contract

A theme is one file, `hub/frontend/src/themes/<name>.css`, holding one fixed
set of colour tokens under `[data-theme="<name>"]` and never under `:root`.
The token names are the contract: `light.css` answers every token `dark.css`
answers, in the same order, so a diff shows one a theme forgot. `<html
data-theme>` carries the palette the page is drawn in; a subtree that pins its
own (`setup_page.tsx`, always dark) sets the attribute on its root, and every
token under it resolves from that file.

- A derived colour is a `color-mix` of a token:
  `color-mix(in srgb, var(--color-accent) 45%, transparent)`. A colour literal
  outside `themes/` is a bug, with two exceptions that are not token meanings:
  the login lockout's alarm grid and the setup wizard's brand gradient, both on
  surfaces pinned dark.
- A token that references another token (the washes, the chart aliases) is
  declared on `[data-theme]`, not `:root`: a custom property resolves its
  `var()` where it is declared, and a pinned subtree mixes them from its own
  accents.
- A token that carries text reaches 4.5:1 on `--color-surface` and on its own
  12% wash. That is what sets the light accents: cyan-700, emerald-700,
  amber-700 and rose-700, one step darker than the neon they stand in for.
- A colour that carries no text is a token of its own and may sit brighter
  than the accent that does: `--color-chart-down` / `--color-chart-up` for the
  curves, `--color-signal-ok` / `-warn` / `-error` for the status dots. On dark
  they are the accents themselves; on light they are a step lighter.
- The committing button's glow is `--shadow-commit`, drawn by each theme: the
  accent lit on dark, a tinted drop shadow with a top-edge highlight on light,
  where a halo of a dark accent reads as a smudge.
- Nothing outside CSS owns a colour. Recharts props take `var(--color-accent)`,
  and `terminalTheme()` resolves the terminal tokens through `themeToken()`
  when a terminal is created and again on a theme change.
- Component stylesheets enter the page after `theme.css` and the theme files,
  and override a base rule by their order, never by a longer selector.
- The client window's `style.css` uses the same token names and values, in two
  blocks of its own.

The choice between the palettes is `system`, `dark` or `light`, kept on the
box beside the language and applied from the Appearance card in Settings;
`system` follows the browser's scheme.

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

## One picker for every choice

A control that offers a list to choose from is the picker `picker.tsx` draws,
whatever the list holds: a credential, a machine's MAC address, an account on
a machine, a credential kind, a sort order, a theme. The browser's own
`<select>` and `<datalist>` are never used: each browser draws them in its own
style, and a page then shows three menus that do not match. `vault_picker.tsx`
is the picker with the vault's rows and the row that stores one more.

The picker is a control shaped like an input (`.select`, the caret at its
right) over a panel fixed to the viewport, so no scrolling container clips it:

- the panel carries the ground, border and radius of `.input`, the
  `--color-shadow` drop and the `fade_in_up` entrance; it is as wide as the
  control, and flips above it when there is no room below;
- a row is 34px in `--font-mono` at 12px: the name at the left, and at the
  right in `--color-text-faint` the detail that tells two rows apart (a
  fingerprint, a machine's name and address, a port);
- the row under the cursor and the row already chosen lift to
  `--color-elevated` and take the accent as text, as the panel's other lists
  mark one;
- a row that creates an entry rather than picking one (Add SSH key) sits
  last under a top border, with the accent as its text and never as a fill;
- five rows show at once and the rest by scrolling;
- arrows move, Enter picks, Escape closes the list before anything holding
  the picker (a modal) sees it, Tab closes it.

A field that takes typed text and also offers choices (an account name, a MAC
address) is the same picker with an input as its control: the rows filter as
the person types, and what they typed stays when no row is chosen.

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
