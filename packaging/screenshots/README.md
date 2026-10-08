# Guide screenshots

This directory holds the guide's shot table and the tool that captures it. Each
image the guide shows has one entry in `shots.json`, and every captured image
lands in `images/guide/<language>/<name>.png`. The docs build turns each png
into the webp the pages reference. An entry with `pages` serves every page it
lists from one image.

## Files

| File | What it holds |
| --- | --- |
| `shots.json` | One entry per image: file, language directory, page or `pages`, source, viewport, element, what to wait for, the state the hub must be in, `press`, the steps run before the shot, `scroll_to`, the element put at the top before a viewport shot, the manual step when one is still needed, `redraw_qr`, the stand-in text a shot's QR code is redrawn from, and `hide`, the CSS selectors hidden before the shot. |
| `redact.json` | The patterns and literal strings replaced inside the page before each shot. |
| `redact.local.json` | Optional, ignored by git: more `literals` in the same shape, for names you do not commit. |
| `capture.py` | Signs in to the panel, takes the panel, client and console shots, and prints what it replaced in each. |
| `client_window.py` | Serves the desktop client's window page from `client_state.json`, for the client shots. |
| `client_state.json` | The state the client window draws, with made-up hubs, addresses and names. |
| `check_shots.py` | Fails when a page uses an image the table does not name, or the table names an image no page uses. `npm run check` in `docs/guide` runs it. |

## Set up the tool

Run from the repository root:

```bash
pip install -e "hub[screenshots]"
python3 -m playwright install chromium
```

## Capture the panel and client shots

Before you start, the hub must be in the state each entry's `state` names, and
its panel must be reachable from this machine. The tool switches the panel's
language for each language's shots and sets it back at the end.

1. Change to this directory with `cd packaging/screenshots`.
1. Export the panel password as `NEUTRINO_PANEL_PASSWORD`, or type it when the tool prompts.
1. Run `python3 capture.py --panel https://<hub-address>:<panel-port> --ignore-https-errors`, where the address and port are the panel's.
1. For an entry with a `manual` step, bring the opened browser window to the state it names, then press Enter in the terminal. The panel entries have none; their steps are in `press`.
1. Read the report printed after each shot, and look at each image for anything the rules missed.

`--only <name> ...` takes the named shots only, `--language en` or `--language zh`
one language, `--source client` the client window's shots, which need no
panel, and `--source console` the console shots.

## Capture the console shots

The `console` entries are pages of the NetBird and EasyTier consoles, saved as
`images/guide/console/<name>.png` and shown on both language pages. They are
taken from a browser profile that stays signed in between runs. The profile is
the directory `NEUTRINO_CONSOLE_PROFILE` names, or
`~/.cache/neutrino/screenshots/console_profile` when the variable is not set;
the tool creates it with mode 700, outside the repository. Delete the directory
when the shots are done.

1. Run `python3 capture.py --console-login <console-url>`, with the address of each console you need in place of `<console-url>`.
1. Sign in to each console in the window that opens.
1. Press Enter in the terminal, and the window closes with the sign-in kept.
1. Run `python3 capture.py --source console`. Each shot opens in a visible window, and an entry with a `manual` step stops until you press Enter, as for the panel shots.
1. Read the report, and look at each image for anything the rules missed.

An entry's `hide` lists the CSS selectors of what the rules cannot reach, such
as an avatar or an account menu; each match is hidden before the rules run and
keeps its place in the layout.

## Capture the Android shots

The `app` entries come from the Android emulator. Set the emulator's system
language to the shot's language, open the screen the entry's `state` names, and
run, for each image:

```bash
adb exec-out screencap -p > images/guide/en/app_hub.png
```

The tool does not touch these images. The app must be joined to a hub whose
names and addresses are fit to publish.

## Capture the OS shots

The `os` entries are system dialogs, taken by hand on that system and saved as
`images/guide/os/<name>.png`. They appear on both language pages.

## What is replaced

`redact.json` replaces, in text, form values, `title` and `aria-label`:
enrolment links, NetBird setup keys, EasyTier console addresses, WireGuard
keys, hex fingerprints, MAC addresses, NetBird keys shown masked, `etk_`
tokens, `sk-` keys, e-mail addresses, NetBird peer names, and IPv4 addresses
outside the private, shared, loopback and link-local ranges. The literal
strings replace host and account names, and `redact.local.json` holds the
ones you do not commit. A shot with `redraw_qr` has its `.qr_code` image
replaced by the tool with a code of that stand-in text before the rules run,
and a shot with `hide` has its listed elements hidden. Other drawn content,
such as a chart, is left as it is.

## Entries that open something first

An entry may carry `press`, the steps run in order once the page has loaded and before `wait_for`. A step that is a selector is clicked (a device chip, a tab, a button that opens a dialog), and `{"fill": "<selector>", "text": "<text>"}` types the text into that field. `scroll_to` names an element put at the top of the page once the `wait_for` element is there, for a viewport shot of a section further down. `{ui.key}` placeholders are resolved in them as in `element`. A click that finds nothing within 15 seconds is reported and skipped, so a step may name something that is only sometimes there. A shot that fails is reported and the run goes on to the next; the tool exits 1 when any failed.

The setup entries are written from the wizard's source and carry `_todo` until a run against a box before setup confirms them; on a set-up hub they fail and the run goes on.
