# Guide screenshots

This directory holds the guide's shot table and the tool that captures it. Each
image the guide shows has one entry in `shots.json`, and every captured image
lands in `images/guide/<language>/<name>.png`. The docs build turns each png
into the webp the pages reference.

## Files

| File | What it holds |
| --- | --- |
| `shots.json` | One entry per image: file, language directory, page, source, viewport, element, what to wait for, the state the hub must be in, and the manual step when one is needed. |
| `redact.json` | The patterns and literal strings replaced inside the page before each shot. |
| `redact.local.json` | Optional, ignored by git: more `literals` in the same shape, for names you do not commit. |
| `capture.py` | Signs in to the panel, takes the panel and client shots, and prints what it replaced in each. |
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

1. Change to this directory with `cd packaging/integration/screenshots`.
1. Export the panel password as `NEUTRINO_PANEL_PASSWORD`, or type it when the tool prompts.
1. Run `python3 capture.py --panel https://<hub-address>:<panel-port> --ignore-https-errors`, where the address and port are the panel's.
1. For an entry with a `manual` step, bring the opened browser window to the state it names, then press Enter in the terminal.
1. Read the report printed after each shot, and look at each image for anything the rules missed.

`--only <name> ...` takes the named shots only, `--language en` or `--language zh`
one language, and `--source client` the client window's shots, which need no
panel.

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
hex fingerprints, MAC addresses, `etk_` tokens, `sk-` keys, e-mail addresses,
NetBird peer names, and IPv4 addresses outside the private, shared, loopback and
link-local ranges. The literal strings replace host and account names. Text
drawn on a canvas, such as a QR code or a chart, is left as it is.
