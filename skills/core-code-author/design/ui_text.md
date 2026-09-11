# The words the panel says

Every string a person reads in the panel: switch labels and descriptions,
field hints, button text, error messages, empty states. Prose in `docs/` is
governed by [../../doc-author/](../../doc-author/SKILL.md); this page governs the
interface itself, where the reader is doing something rather than reading.

The difference is the budget. A documentation page has as many sentences as
its subject needs; a switch has one line, read at a glance, next to the thing
it changes. Almost every rule here follows from that.

## A switch's description begins "Whether"

One shape, everywhere, because a switch has one meaning and the reader should
not have to work out which half of the sentence applies to them:

```text
Whether <what is true while it is on>.
```

Not what happens when it is off; not an instruction; not a consequence. The
control already shows its state, so the description only has to name what the
state *is*.

```text
# BAD — describes the off position, so the on position is left to inference
Off leaves clients to configure themselves; the gateway still answers DNS.

# BAD — two sentences before the reader learns what the switch does
The box itself, tailscaled included, in any network mode and independently
of the LAN switch. This is the way back in when Tailscale cannot reach its
control plane over the local link.

# GOOD
Whether this network hands out addresses.

# GOOD
Whether name resolution and connections from Neutrino Hub itself go through
the proxy.
```

A consequence worth stating goes in a **second sentence**, after the first has
answered the question:

```text
Whether devices on one of the gateway's networks can reach devices on
another. Every network reaches the internet and the overlay either way.
```

Two sentences is the ceiling. A switch needing three is a switch whose page
needs a paragraph above it instead.

**Name products only where the product is the point.** A description that
names one VPN as *the* reason for a switch is wrong the day a second is
supported, and it was already wrong for anyone not running the first. Say what
the switch does to traffic; the reader knows what they run.

## Other controls

| Control | Shape | Example |
| --- | --- | --- |
| Switch | `Whether …` | `Whether this container starts with the box.` |
| Text field hint | what the field takes | `xray rule syntax: geoip:cn, geoip:private, 10.0.0.0/8.` |
| Button | the verb, imperative | `Apply nodes`, `Add node`, `Forget` |
| Empty state | what is missing, then how to fill it | `No nodes configured` / `Add one with a share link from your provider.` |
| Error | what happened, in the terms the reader used | `port 8080 is already in use on this box` |

A button says what pressing it does, never what state the system is in — and
never the same word for two different actions on one page.

## The rules that apply to everything

**No narrated reasoning.** The panel says what is, not why the code does it.
Rationale belongs in `docs/`. This is the same rule the comments obey
([../coding_style/comment_style.md](../coding_style/comment_style.md)), and it
is broken most often in descriptions that start explaining the implementation.

**Sentence case, and a full stop on a sentence.** `Send LAN traffic through
the proxy`, not `Send LAN Traffic Through The Proxy`. A label is a fragment
and takes no full stop; a description is a sentence and takes one.

**One name per thing, everywhere.** The mode is `side gateway` in every string
that names it, never `side-gateway` in one place and `Side Gateway` in
another. The config key may be `side_gateway`; what the reader sees is not the
key.

**The reader's vocabulary, not the implementation's.** `exit node`, not
`outbound`; `this network`, not `the LAN interface with the lan role`. Where a
technical term is the honest one — `VLAN`, `DHCP`, `SOCKS5` — use it plainly
rather than inventing a friendlier word nobody else uses.

**Numbers and units are half-width, with a space**: `12 devices`, `443 ms`,
`8 MB`. A count of one still reads as a count: `1 device`.

**No em dash inside a sentence.** `The saved login is gone; enter it again`,
never `The saved login is gone — enter it again`. As a plain separator
between two values it is fine — `leastPing — lowest latency wins`, a `—`
placeholder for a missing reading — the ban is on splicing prose with it.

**States, not mechanics; progress, not sentences.** A surface says where a
thing stands (`mounting…`, `shared`), never how the system will get there
(`the machine answers on its next heartbeat`). While something is under way
the control that asked shows it is busy; when it lands, the row itself is
the answer, and no `done` sentence follows it.

**Never announce what the product does not do.** `The password stays on this
machine; the hub is never told it` explains an implementation boundary
nobody asked about. Security properties live in `docs/`; the surface shows
the controls that exist and omits the reassurance.

## Localization

The panel and the client page speak English and Simplified Chinese; the
command lines stay English. Every word a surface shows comes from a catalog,
never from a literal in a component.

**One catalog format on both surfaces.** A flat JSON object per language,
keys `ui.<area>.<thing>`, `state.<token>` and `code.<code>`, values whole
sentences or labels with `{name}` placeholders. The hub keeps one file per
page group under `hub/frontend/src/locales/<language>/`; the client keeps
`client/frontend/locales/<language>.json`. `t(key, params)` reads the current
language, falls back to English, then to the key itself. A key set differing
between the two languages, a key used in the source but absent from English,
or a backend code with no `code.<code>` entry fails the tests.

**Where the language is chosen.** The hub's is a setting in
`config/web/settings.json`, asked first by `nhub setup` and by the web setup
page, changed later on the Settings page, and read before login through
`GET /api/language`. The client's is a preference in its store, taken from the
system locale on the first start and changed on its own page. Nothing is per
browser.

**The backend returns codes, not sentences.** An error a person reads is
composed in the frontend from an identifier the API returned; a backend that
returns `"port 8080 is already in use on this box"` has made itself the
translation surface, and no amount of frontend work can undo that.

**A translation is not a port of the structure.** Each language follows its own
typographic authority, exactly as `docs/` does: Google's developer
documentation style guide for English, 中文文案排版指北 for Chinese. Never
translate sentence by sentence — the `Whether …` shape is an English shape, and
the Chinese rendering of a switch description is whatever that guide says a
switch description is.

**What cannot be translated must not be assembled.** A string built by joining
fragments (`"port " + n + " is already in use"`) has an English word order
baked into it. Whole sentences with named placeholders survive translation;
concatenation does not.

**Interface terms keep their English beside the Chinese on first use**, the way
the Xray documentation does it, because the config keys, the upstream tools and
this standard are all English.
