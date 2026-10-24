# UI behavior

What each kind of thing in the panel does: how a page is composed, what a panel
is allowed to do, when an edit takes effect, and which idiom a new screen
reuses. Colours, button tiers and the meaning of the glow are
[visual.md](visual.md); the strings themselves are [ui_text.md](ui_text.md).

Each entry is the panel as it already behaves. An interaction none of them
covers is the last section.

## The page

The page is the largest unit and the only thing with an `<h1>`. It is composed
of panels, and it holds no state of its own beyond which panel is selected.

A page reads top-down in one order:

| Position | What goes there |
| --- | --- |
| First | What is happening now — mode, status, the diagram, live activity |
| Middle | What a person changes |
| Last | Rarely-touched plumbing — which interfaces answer, which port the panel is on |

`network_page.tsx` is the reference: the mode panel, then the topology diagram,
then the per-interface form, then routing behavior, then exposure, then the
panel's own ports and the agent port. Before an agent port change is
saved, the panel's apply bar warns with `ui.network.agent_port_offline_warning
{clients, agents}`, the counts `SettingsView` holds: those peers lose the
hub and join again with a new link ([protocol.md](protocol.md), "Three
ports, two audiences"). While Direct is on, the bar adds
`ui.network.agent_port_direct_warning`: the router's port forward and
Direct's public port change with the agent port. While SakuraFrp or OpenFrp
has a tunnel picked, its `tunnel_id` not empty, the bar adds
`ui.network.agent_port_frp_warning {vendor}` once for each.

**A page carries no controls that belong to a panel** — no apply, no reset, no
save. Its header may carry an action that belongs to no single panel and starts
something the whole page is about: `Scan LAN`, `New terminal`, `Open Gitea`.
Those sit in `page_actions`, and a page with none is the normal case.

## The panel

A panel is the container of one concern, framed as a `card` or a
`settings_group`. It does one of two things, never both:

- **Visualizing** — read-only, refreshes itself, carries no apply. The topology
  diagram, the usage tables, `device_monitor`.
- **Configurable** — stages edits in a draft and carries **its own** apply bar
  and reset.

Two concerns are two panels. What is framed together is applied together, so a
panel that grew a second apply bar was two panels all along, and a change that
must not take another one down gets a frame of its own — a mistake in the Wi-Fi
settings cannot be allowed to drop the wired LAN somebody is connected over.

## The apply bar and the frame it closes

Every configurable panel ends in one `ApplyBar`. There is no auto-save anywhere
and no page-wide apply: applying restarts a daemon, reloads the firewall or
reconfigures an interface, and takes a deliberate press.

The frame lights whenever the bar does — `settings_group--dirty`, or
`card--dirty` on a `card` — and the two answer one question between them
([visual.md](visual.md), "Frames"). The bar's terms are fixed:

| Term | What it says |
| --- | --- |
| `label` | The scope, as a verb: `Apply to enp1s0`, `Apply routing behavior` |
| `hint` | What pressing it does, in one line. With nothing changed: `Nothing changed here.` |
| `warning` | Shown while dirty, before the fact, when applying is disruptive |
| `error` / `notice` | The last attempt's outcome, in place, never as a toast |

Reset returns the draft to what the gateway holds and clears the outcome. Both
buttons are dead while nothing has changed and while an apply is in flight.
A refresh never replaces a dirty draft; the apply bar is what ends a draft.

## Where buttons live

Panels and rows carry buttons; a page carries at most a page-scope action. Which
tier each one takes is [visual.md](visual.md).

A row of records puts its repeated actions on the row itself as ghost buttons —
per-row Remove, Test, Edit — and a panel-scope action (`Add node`, `Test all`)
in the panel's header.

## Status dots and badges

`StatusDot` has four tones. An `ok` dot pulses so a screen left open still reads
as live; every other tone is static.

| Tone | Means |
| --- | --- |
| `ok` | Running, healthy, answering |
| `warn` | Degraded, or a step in flight |
| `error` | Failed, stopped, unreachable |
| `idle` | Not started, nothing to report |

A dot is a tone, not a word. It carries a `label` where nothing beside it says
what it means, and goes bare where the row's own text already does. Either way
the words for one concern are a fixed set, written once at the top of the file:
`reachable` / `unreachable` for a declared service, `answering` /
`not answering` for the AI gateway, `reporting` / `seen` / `offline` for a
device. Never a machine word — a socket's `open` is `live` to a reader.

Badges say one word and report state; they are never pressed.

An interface the hub detects and the configuration does not name
carries `ui.network.unsaved_interface` as an accent badge on the
**Network** page, on its exposure chips and in its summary, the way a
VLAN the next apply creates carries `ui.network.vlan_new_on_apply`.
The page reads it from the interface's `is_unsaved` and works out
nothing itself ([hub_components/network.md](hub_components/network.md), "An
interface the configuration does not name").

A Wi-Fi radio that publishes a network has a **Country code** field
(`ui.network.field_country_code`) beside **Band**: two letters, or empty.
The band picker offers 5 GHz only while the field holds a code, and with
it empty the access point runs on 2.4 GHz
([hub_components/network.md](hub_components/network.md), "The access point's country").

In router mode, a chip turned on for a port whose role is `disabled` carries
the role choice in the same row: `ui.network.role_wan`, and
`ui.network.role_lan` for a wired port, as a two-button picker beside the
chip. **Apply exposure** stays disabled until every such chip has a role
chosen, and the request sends it in `interface_roles`
([hub_components/network.md](hub_components/network.md), "An interface the configuration
does not name").

## Filters

A filter row is single-select chips over a list already in memory, `All` first
and every other chip carrying its count. Filtering never fetches. Where the
chips are derived from the data rather than from a fixed set of states, a chip
with nothing behind it is not rendered.

A search input sits in the same row and narrows the same list. A list narrowed
to nothing says so differently from a list that is empty — `No devices match` /
`Try a different filter or clear the search.` against `No devices yet` /
`Run a LAN scan to discover what is connected.`

## Tables

A table shows activity, or rows the panel does not own — usage per key,
processes on a device. Records somebody manages are rows in a configurable
panel instead, with their own apply.

A table sorts itself on the column that matters, descending. **Column headers
are never buttons**: where the sort is worth choosing it is a `Sort` select in a
control row above the table. A table that can grow gets the rest of that row —
filter chips, a page `Size`, and `Previous` / `Next` reading `n/m`; changing a
filter or the size returns to the first page. A table with a bounded number of
rows carries no controls and shows all of them (`ai_usage_keys.tsx`).

Wide tables scroll inside their own box (`usage_table_scroll`); the page never
scrolls sideways. Numeric columns are right-aligned (`.num`).

A destructive action repeated on every row arms instead of opening a dialog —
`device_monitor`'s kill button turns red on the first click and acts on the
second — because one modal per process is a dialog nobody reads by the third
time.

An action a row shows only on hover sits behind a `⋯` button as well, which is
always there on a touch screen or in a narrow window (`row_menu.tsx`, used by
`device_monitor` and the file browser). The menu lists the row's actions, and
an item that arms keeps the menu open, so the second press acts. A file row at
phone width takes two lines: the icon and the name, then the size and the time.

## Inline forms

A record is added where its list is. `Add node` opens a form in place with a
Cancel beside its save; nothing navigates away to add one thing, and the same
form edits an existing record where the record is editable at all — a
credential is not (see Secrets).

Where a list is a configurable panel, the add is part of the draft: the row
lights the frame and Apply is what makes it real, and a record born that way is
born inert — a new VLAN interface is created `disabled`, so adding it changes
nothing until somebody gives it a role. Where the list is not a draft — a
credential, an exit node, a generated key — the add writes at once, and so does the
remove.

Which of the two a list is, is the panel's answer, not the form's: a list inside
a frame stages, a list without one writes. `node_card.tsx` says it for the case
where both meet — the node's fields stage, and removing the node takes effect at
once.

## Confirmation

`useConfirm` is the only way the panel asks. Never `window.confirm`.

The dialog has three parts: a title naming what is about to happen
(`Delete the pool tank`), a body of one or two sentences saying what it costs
with the mechanism first, and the action's own verb on the button. Escape and
the backdrop cancel.

**The body states the concrete consequence, cascades included.** A delete that
clears references says how many and whose: `2 devices lose this key and will
need a new one`. `credentials_page.tsx` composes these from the reference counts
the API returns.

The confirming button is `button--primary` and wears the action's verb; the red
is spent on the button that opened the dialog, not on the one that closes it.

Settings are not confirmed here. A group of them ends in an apply bar, and the
bar's `warning` is where its cost is stated. Deleting data that cannot be
re-derived asks for more than a press: the name typed back, in a red-bordered
box inside the card rather than in this dialog ([visual.md](visual.md)).

## Drawers and modals

A **drawer** is the detail view of one record from a list. It pins to the right
edge at full height, portals to `document.body` so no stacking context can put
it under the top bar, dismisses on Escape or the backdrop, and defers its own
loading until it opens by passing a null path to `useApiResource`.
`device_drawer.tsx` is the reference, and a list page therefore never navigates
away to show one row.

A drawer is one record, so it saves as one record: sections down the body, one
`button--commit` at the foot, and no apply bars. Actions that are not part of
that record — reboot, wake, install — act at once from their own row, and their
output streams into the log at the bottom.

A **modal** is for one interaction that must finish before anything else: a
confirmation, a terminal session, a file transfer, an install consent. Anything
that is merely detail is a drawer. A QR code in a dialog is an image, an
`<img>` from a PNG data URL, so a long press on a phone and a right click on
a desktop save it; it is drawn at four pixels per module at least and never
under 240 px, so the whole enrolment link scans from a screen, and in a
portrait layout it sits at the bottom of the dialog,
centred, on the desktop and on the phone alike. Every modal closes on Escape, closing only
itself — the layer underneath stays — and one that tells the reader so must
mean it. The exception is a modal that captures the keyboard: a terminal's
Escape belongs to the shell, the way every established terminal works, and its
hint names the close button instead.

A field that takes a directory on a machine has **Browse…** beside it, which
opens the file browser in a modal at the field's path, files greyed, and
writes back the directory chosen (`directory_picker_modal.tsx`).

## Secrets

A secret the hub is **given** is write-only: typed once, listed back as metadata
— name, fingerprint, reference count, when it was last used — and never shown
again. The field for one stands empty behind `PRIVATE_KEY_PLACEHOLDER`, which is
deliberately a template so nothing reads as stored key material.

A secret the hub **generates** is shown to its owner: masked by default, with
`Reveal` / `Hide` and a copy button beside it.

**A credential is never edited** — not its value, not its name. It is added,
referenced, and deleted, the way a token works on GitHub: replacing one is
adding a new credential, pointing its consumers at it, and deleting the old
one, whose dialog words the cascade
([architecture.md](architecture.md), "The credential vault"). A stored value
is never read back into a field for any purpose.

A copy button goes through `copyText`, which falls back to a selection when
the panel is served over plain HTTP, where the clipboard API is absent. It
confirms in place, swapping to a check and `Copied` for a moment, because a copy
that looks like nothing happened gets pressed again.

## Journals and streamed output

Output a person reads goes into the page — a journal panel, or the log at the
bottom of a drawer. Nothing in this panel is announced in a toast and dismissed;
an install is a thing you read.

A journal is a fixed tail of the last 200 lines, fetched only while it is open —
a modules page with eight units pulls no journals until somebody asks for one —
and while open it polls itself and scrolls to the newest line, like every other
live panel. `ai_journal_panel.tsx` is the reference.

A task that is running streams into the same place through `useTaskStream`,
which caps at 2000 lines, replays from line one when the socket comes back, and
gives up after one reconnect. Anything a shell wrote goes through `stripAnsi`
before it is rendered, and so does every journal and every module log box: no
control code reaches the page. A module's log box belongs to the tab that
shows it: switching the tab fetches that module's journal at once and shows
the loading state until it arrives, and the box never holds another module's
text. A module that failed shows the agent's code as
its error line under its state, and an apply that ended in a failure shows
no success notice.

## Empty states and loading

While a page's first load is in flight it shows a `skeleton` roughly the height
of what will land. A `Spinner` is for work somebody started and is waiting on —
inside the button that started it, or beside the row it is working on. A page
never loads behind a spinner.

An empty list is a `placeholder` with two lines: what is missing, then how to
fill it, and the button that fills it where one exists. `No nodes configured` /
`Add one with a share link from your provider.` A list that fills by itself
has one line, in the `No … yet` family, and no second line
([ui_text.md](ui_text.md), "Other controls").

A panel that shares a row with a taller one keeps the row's height whether
it is full or empty, and an empty one lets its `placeholder` grow to fill
it; the dashboard's active exits beside the two traffic charts are the
reference. A panel that shrinks to its empty state leaves a hole where the
page's shape was.

The dashboard's side column, which holds the active exits and the DNS log,
is drawn only when one of them is, and the two traffic charts then take the
full width.

## Notices and errors

A failure renders in place. An inline `notice--error` where an action failed, an
`ErrorPanel` with a Retry where a load failed — never a blank page, because the
panel is most needed exactly when the box is unwell. A failed poll keeps the
last good value on screen and the next tick retries. A load whose request
got no answer at all (the `fetch` itself rejected: the browser cut the
connection when a network interface came or went) is sent once more after
two seconds before the `ErrorPanel` shows; a response with a status is
shown at once.

The backend returns `{code, params}` and the frontend words it, from a map
beside the component that shows it: `device_drawer.tsx` (`ACTION_ERROR_KEYS`)
and `services_page.tsx` (`DECLARED_INVALID_KEYS`) are the shape. An unworded
code drops an optional detail, but never a consequence somebody is being asked
to accept: that one still shows, with the code spelled out, because an unworded
consequence beats a hidden one.

Not every endpoint has a code yet, and `describeError` falls through to the
backend's own sentence where none came. Adding a code is what moves a message
off that path ([ui_text.md](ui_text.md), "Localization"), and what the sentence
says once it is there is the same page.

## Nothing asks for a refresh

No screen in this panel may require a manual page reload, and no panel carries a
refresh button. A panel showing live state polls itself — and does not announce
it: self-refresh is the whole panel's default, and a `live` dot or badge every
panel would wear marks nothing, so none wears one. A pulsing dot belongs only
to a state word that is really being reported (`running`, `answering`, the
strip's own `live` / `connecting` / `offline`). When the process behind the
panel changes, the page reloads itself
([architecture.md](architecture.md), "The panel heals itself").

A Retry on a failed load is not a refresh: it is the way out of an error state,
and it exists only while the error is on screen.

A cadence is a named constant at the top of the file, never a literal at the
call site, and it slows to nothing while the tab is hidden — `document.hidden`
gates the tick, because a background tab polling the gateway every second buys
nobody anything.

| Interval | For |
| --- | --- |
| 15 s (`DEFAULT_POLL_INTERVAL_MS`) | Anything with no reason to be faster |
| 5–10 s | A list or a badge that changes on its own — services, devices, pools |
| 1–3 s | Something a person is watching change right now |
| 500–700 ms | A step in flight with an end: a port move, the setup wizard |
| socket | Where the reading is the point: stats, DNS log, a terminal |

The panel identity probe polls nothing: it reads once each time the event
socket opens, when the tab comes back to the front, when the login page loads
and after a login (`panel_identity.ts`).

## When an effect happens

| Kind | When it acts |
| --- | --- |
| Visualizing panel | On its own, every tick, with no action from anybody |
| Configurable panel | On its apply, never on a keystroke |
| A revocation — deleting a key, a token, a credential, a device | At once; the confirm dialog is the whole of the delay |
| Expensive or rude work — a LAN scan | Only on an explicit press |

A revocation never waits behind an apply bar. What else waits is what a frame
stages, and nothing else does.

## The words live at the top of the file

Every string a person reads is a `const` above the component that shows it —
one `WORDING` table, or named constants where a section owns a family of them
(`ai_page.tsx`, `services_page.tsx`). Nothing user-visible is written inline in
JSX. Several older pages still hold their strings in the markup; moving a
file's copy to the top is part of touching that file, not a separate errand.

Counts and names go in through placeholders — `{healthy} of {total} reachable` —
rather than concatenation, because a sentence assembled from fragments has an
English word order baked into it ([ui_text.md](ui_text.md), "Localization").

## Lists of short values

A list of short values a person types is a `StringListEditor`
(`components/string_list_editor.tsx`): the values as removable chips, then an
input with an **Add** button that appends the typed value as the last row. The
container panel's ports, volumes and environment are the reference, and the
same component is every such list; none gets a table or a second idiom.

| Rule | Reason |
| --- | --- |
| The list is part of its panel's draft: an added or removed row lights the frame, and the apply bar writes the whole list. | A list inside a frame stages, as "Inline forms" states. |
| A row keeps the order it was added in, and that order is the order the backend uses. Reordering is removing a row and adding it again. | The chips have no drag handle, and the order is rarely changed. |
| A blank row or a duplicate is dropped at the add; what the value means is checked by the backend, and its refusal shows on the apply bar. | The editor keeps the list tidy and the backend owns the rules. |
| An editor can have **Browse…** after its **Add**: it opens the path window (`directory_picker_modal.tsx`) on the device, at the folder the input names or at the machine's root, and writes the folder chosen into the input with `:` after it, for the person to finish the row and add it. | A volume is `<folder>:<path in the container>`, and only the first half is a folder of the machine. |
| With **Browse…** the input is at least 16rem wide, and **Add** and **Browse…** move under it together where the row has no room for the three; an editor without **Browse…** keeps one line. | A folder path does not fit in the room two buttons leave in one column of the container editor. |

The container editor's **Volumes** has **Browse…** on every system, and its
placeholder is a volume in the machine's own form,
`ui.containers.volume_placeholder_linux`, `_windows` or `_darwin`
([ui_text.md](ui_text.md), "The Containers tab's words").

Three lists of resolvers use it, each row one address or `<address>:<port>`,
an IPv6 address in brackets when it has a port; the page sends each row as
`{address, port}` with `port` 53 when the row names none:

| List | Where | While empty |
| --- | --- | --- |
| `remote_dns` | the Proxy page, beside the direct list | refused at apply, `resolver_required {field}` |
| `direct_dns` | the Proxy page | `Follows the network's resolvers` / 「跟随网络层的解析器」 |
| `wan.dns` | a static uplink's form on the Network page, under its address, prefix and gateway | `Built-in resolvers: 223.5.5.5, 119.29.29.29` / 「使用内置解析器 223.5.5.5、119.29.29.29」 | <!-- scan: allow -->

A DHCP uplink's form shows no list; in its place a hint line names the
resolvers its lease gives, from `link.lease_dns`.

## Terms before a module opens

A module whose publisher asks for acceptance of its terms opens on a machine
only after the person accepts them for that machine. VS Code is the one such
module, and its tab on the Modules page is the reference:

| Step | What the tab shows |
| --- | --- |
| Not accepted on this machine | One notice, `ui.vscode.terms_notice`, and one `button--primary`, **Open and accept the terms**. Nothing else of the tab is drawn: no state line, no install, no instances. |
| The press | Opens `terms_url` in a new tab (`target="_blank"`, `rel="noreferrer"`) and, in the same press, sends `POST /api/agent/module/vscode/terms/set {device_id, is_accepted: true}`. The press is the acceptance; no dialog follows. |
| Accepted | The notice stays at the top with its button disabled and reading **Terms accepted**, and the tab opens below it as before. |

The record is per machine, `terms_accepted_at` in that machine's
`config/devices/<id>/vscode.json` ([protocol.md](protocol.md),
`/api/agent/module`), so each machine's tab asks once. A failed write
shows in place under the button, which stays live. CloudCLI, Codeg, Gitea
and code-server tabs carry no notice ([ui_text.md](ui_text.md), "Software the
owner installs").

## Finding and adding a device

The Devices page's header holds **Scan LAN** and **Add by address**
(按地址添加). A
scan covers the exposed IPv4 segments in every mode
([protocol.md](protocol.md), `POST /api/hub/device/scan`): a segment of at
most 256 addresses whole, and of a larger one only the /24 that holds the
hub's own address. It scans no IPv6 segment and reads the IPv4 neighbours
alone, so a row's address is always an IPv4 one. **Add by address** opens a
dialog in the style of the **Install agent** dialog, with the same fields:
**Host**, **Port**, **User name**, **Credential**, **SSH key** and **Sudo
password**, the host typed by the person. The dialog's button installs:
one press creates the machine's row, named by its host until it reports,
and starts the install ([protocol.md](protocol.md), `POST
/api/hub/device/add`). It reaches a machine no scan finds, such as one on a
network the hub has no address in.

## The Exposure section on the Network page

The **Exposure** section (开放范围) draws one chip per segment
([hub_components/network.md](hub_components/network.md), "What answers, and
where"), each a switch, in the design it has for an interface. Each
interface the page lists gives two chips, its IPv4 segment and its IPv6
segment, and each names the segment's network and the interface it is on.
Each overlay engine gives one chip. A chip's tag is its interface's role,
`lan` or `wan`; in server mode an interface has no role and its chips carry
no tag. The section has no **+** and takes no network typed by hand. The
hint under it is `ui.network.exposure_hint` ([ui_text.md](ui_text.md), "The
Network page's words"), and the apply bar is **Apply exposure**. Opening the
agent port to every sender is Direct's switch on the **Access** page, below.

## The cards on the Access page

The **Access** page draws the ways in as cards in the engine panel, in this
order: NetBird, EasyTier, SSH relay, Direct, SakuraFrp, OpenFrp. The cards
sit three to a row, two rows of three, in both editions, and one to a row
below 720 px. A page with
no card switched on says nothing about it. Every card is shaped alike: its switch stages into
the engine panel's draft and that panel's apply bar turns it on or off, and
pressing the card shows its section under the panel while the card is on as
applied. A card that is off, or switched on and not yet applied, draws
nothing under the panel, the same for all six; once the relay is applied on,
its section appears with the state it has then, `not_configured` until it is
set up. The engine panel's bar reads **Apply access**
(`ui.overlay.apply_engine`).

An engine section's peer table shows each peer's latency in the same
column whether the path to it is direct or relayed, with the word
`state.relayed` beside the number of a relayed peer. Where the engine gives
no latency for a relayed peer, as NetBird does not, the number is the round
trip the hub measured to the peer's overlay address, one ICMP echo per
peer at the address sampler's interval, `WEB_ADDRESS_SAMPLE_INTERVAL_S`. The
cell is empty while that echo had no answer ([protocol.md](protocol.md),
`GET /api/hub/overlay/netbird`).

EasyTier's apply bar is disabled while **Manual bootstrap peers** is chosen
and no peer is filled in, with no sentence beside it; the hub refuses that
configuration with `easytier_invalid {field: peers}`.

Direct's section is one configurable panel, a `settings_group` with its own
apply bar ([ui_text.md](ui_text.md), "Direct's words"): the switch's
description `ui.overlay.direct_switch_hint`, which says that the switch
opens the hub's connection port to every host that can reach the enabled
interfaces; **Public address** and **Public port**; and **Addresses for
clients**, the `urls` of `GET /api/hub/overlay/direct` in mono, and under
them the sentence its `interface_state` names: none for `added`,
`ui.overlay.direct_addresses_exposed` for `exposed`, and
`ui.overlay.direct_addresses_empty` for `none`. The page words the state
and does not work it out. The bar's label is
**Apply Direct** and its hint `ui.overlay.direct_apply_hint`. The section
shows whether the switch is on or off, so the person states the address
first.

The relay's words are in [ui_text.md](ui_text.md), "The relay's words".

The relay's section holds two panels:

| Panel | Kind | Holds |
| --- | --- | --- |
| Status | visualizing, read from `GET /api/hub/overlay/relay` on the page's 10 s cadence | the state as a `StatusDot` with its word; **Address for clients**, the `url` in mono; **Host key**, the `host_key_fingerprint` in mono with **Forget host key** beside it while one is recorded; `last_error` in mono under the state while it is not empty. No link: the guide page stays in the guide |
| Settings | configurable, a `settings_group` with its own apply bar | **Server**, **SSH port**, **Account**, **Credential** and **Public port**, then the vault picker of the credential chosen. **Credential** is the Devices page's **Install agent** picker, with its words and the hint `ui.overlay.relay_credential_hint`: **SSH key** shows the picker of the vault's SSH keys, **Password** the picker of its logins, and the request names the one picked as `key_id` or `login_id`, as the install's does. No link to the Credentials page. The bar's label is **Apply SSH relay**, its hint `ui.overlay.relay_apply_hint`, and its warning `ui.overlay.relay_apply_warning` while the relay is `connected` |

The state's tone follows "Status dots and badges": `connected` is `ok`,
`connecting` is `warn`, `disabled` and `not_configured` are `idle`, and every
other state is `error`.

**Forget host key** asks through `useConfirm`: the title `Forget the host
key` / 「忘记主机密钥」, the body `The next connection records the key the
server presents.` / 「下次连接时记录服务器出示的密钥。」, and the button
**Forget** / **忘记**. It acts at once, outside the settings draft, the
way a revocation does ("When an effect happens").

SakuraFrp's and OpenFrp's sections are shaped alike, from the words in
[ui_text.md](ui_text.md), "The frp cards' words". Once the card is applied
on, its section appears with the state it has then, `not_signed_in` until
the person signs in. Each holds three panels, top to bottom:

| Panel | Kind | Holds |
| --- | --- | --- |
| Status | visualizing, read from `GET /api/hub/overlay/<vendor>` on the page's 10 s cadence | the state as a `StatusDot` with its word; **Node**, `node_name`; **Address for clients**, the `url` in mono; `last_error` in mono under the state while it is not empty; `ui.overlay.frp_port_mismatch` while `local_port` is not the connection port |
| Account | SakuraFrp: configurable, a `settings_group` with its own apply bar; OpenFrp: buttons that act at once | SakuraFrp: **Access key**, a password field with the hint `ui.overlay.frp_access_key_hint`, the bar **Save access key**, and **Forget access key** while one is stored. OpenFrp: **Log in** while signed out or expired, which opens `login.authorization_url` in a new tab; while `login.state` is `waiting`, `ui.overlay.openfrp_login_waiting` with **Open the login page again**, and the page reads the view every 5 s until the state changes; `timed_out` and `failed` worded under the button; **Log out** while signed in; `ui.overlay.openfrp_login_expired` while `is_login_expired`. Under OpenFrp's panel, always shown, `ui.overlay.openfrp_openapi` and `ui.overlay.openfrp_notice` in the panel's small text |
| Tunnels | configurable, its own apply bar, shown while signed in | one row per tunnel of `GET /api/hub/overlay/<vendor>/tunnel`, read when the section opens and on **Refresh** in the panel's header: a radio mark, the node's name, the region's word and the latency in mono at the right edge, the picked tunnel's row marked; an empty list is `ui.overlay.frp_empty` (`ui.overlay.openfrp_empty` for OpenFrp) with **Open the {vendor} console**, a link to `console_url` in a new tab. The bar's label is **Apply tunnel**, its hint `ui.overlay.frp_apply_hint`, and its warning `ui.overlay.frp_apply_warning` while the state is `connected` |

The state's tone follows "Status dots and badges": `connected` is `ok`,
`connecting` is `warn`, `disabled`, `not_signed_in` and `no_tunnel` are
`idle`, and every other state is `error`. **Log out** and **Forget access
key** ask through `useConfirm`, with the apply warning's sentence as the body
while the state is `connected`.

## The Modules page

The **Modules** page has three panels, top to bottom:

| Panel | Holds |
| --- | --- |
| the machine picker | the managed machines, as before |
| **Global configuration** | the settings of the picked machine that belong to no module; today one part, its AI tools |
| **Module configuration** | a left and right split under the title `ui.modules.tabs_title`: on the left a vertical, scrollable list of the machine's modules, each row the module's icon (`images/icons/modules/<module>.svg`, the generic glyph for a module without one) and its title; on the right the picked module's panels, its output box and its buttons, the buttons aligned to the right edge |

In a window 880 px wide or narrower, or one no wider than it is tall, the
split is one column. The module list is then one row above the picked
module, and that row scrolls sideways.

The module picker opens under the `+` ending the list, and above it when
less than 160 px is free under it and more above. Its greatest height is
the room free on that side, 160 px at least, and a longer list scrolls
inside it.

A module the machine reports `installed`, `stopped` or `running` while
the hub holds no `want` for it, as after a reset or a new join on a machine
that kept its modules, has **Start** live, whatever its state; the press
and an apply of its configuration give it the `want` `running`
([protocol.md](protocol.md), "Taking over a machine").

A module the machine reports `queued` is in transit, as `installing` and
`uninstalling` are: every button of its tab is disabled until the machine
reports another state ([agent.md](agent.md), "One module at a time"). After a
press, the tab's optimistic step holds until the machine reports the module
in a state other than the one it showed at the press, at most two minutes.

A module reported `install_failed` has an `error` dot in the module list.
Its tab reads `state.install_failed` beside the same dot, and shows the
code's words as the error notice a `failed` module shows. **Install** and
**Uninstall** are live, and **Start**, **Stop** and **Configure** are not:
**Install** runs the install again, and **Uninstall** removes what the
install left ([agent.md](agent.md), "An install that fails ends
install_failed"). The output box shows the failed install's lines while the
hub holds its task, and never the module's journal. No module has a
**Cancel** button.

A module reported `installing` with a code shows the code's words as a
notice at the top of its tab, and its buttons stay disabled as for any
module in transit. Its output box keeps the install's lines while the hub
holds the task, with `ui.modules.task_running` beside them, until the
machine reports another state. With `reboot_required` the notice has
**Restart now** (`ui.modules.restart_now`), which asks through `useConfirm`
(`ui.modules.restart_title`, `ui.modules.restart_body`) and sends `POST
/api/hub/device/reboot`. The agent never restarts the machine itself, and
the install goes on after the restart with no press ([agent.md](agent.md),
"Status is typed").

A module whose last report is `failed` keeps the button of what it was
asked for live: **Install** while its `want` is `installed`, **Start** while
it is `running`, **Stop** while it is `stopped`, and **Uninstall** always.
That press tries the same step again ([agent.md](agent.md), "A retry is the
same press again"); there is no other retry button. A module panel's apply
and **Configure** on a refused configuration try again the same way. A
press on a module that did not fail asks for nothing new.

The rows of the module list, each a tab, come in one order, the modules
every system runs first: File share, Terminal, Remote desktop, Gitea, VS
Code, code-server, CloudCLI, Codeg, Containers, ZFS storage. VS Code,
code-server, CloudCLI and Codeg are drawn by one `instances_panel.tsx` from
the hub's description table. A module the machine cannot
run is left out, as before ([agent.md](agent.md), "Which modules each system
runs").

Terminal and Remote desktop are a tab on every managed machine and never in
the picker. Their tab draws the module's state line and its panel, and none
of **Install**, **Start**, **Stop**, **Uninstall**, **Configure** or the
output box, since the agent's package carries them:

| Tab | Its panel | Idiom |
| --- | --- | --- |
| Terminal | **Account**, a picker over the human accounts the machine reported with the agent's own first (`ui.terminal_module.account_agent`); **Shell program**, a text field with **Browse…** beside it, which opens the panel's path window on that machine in its file mode, where a press on a file picks it | one configurable `settings_group` with its own apply bar, `ui.terminal_module.apply`; on a Windows machine **Account** is disabled with the line `ui.terminal_module.account_windows` under it |
| Remote desktop | one switch, `ui.remote_desktop_module.switch`, with its description | one configurable `settings_group` with its own apply bar, `ui.remote_desktop_module.apply`; a failed step is the module's notice with its code's words, and the apply bar's Apply tries again |

The path window is the one Samba's share folders use
(`directory_picker_modal.tsx`); its file mode opens at the field's path, or
at the machine's root, lists files beside folders, and a press on a file
hands its path back. The device drawer's desktop section names the switch
and links to this tab instead of offering a way to share.

A tab whose module the machine reports `unsupported`, an agent older than the
module, keeps its state word `unsupported` and draws its panel with every
field, the switch and the apply bar disabled, and no sentence added.

The Containers tab on Windows and macOS opens with **Run settings**
(`components/containers_run_settings.tsx`), above **Running now**,
**Registry mirrors** and **Declared containers**, as the mode panel opens
the Network page: nothing under it works before the Podman machine runs.
On Linux the tab has no Run settings, since root runs Podman there
([agent/modules/containers.md](agent/modules/containers.md)).

| Control | Idiom |
| --- | --- |
| **Account** | a picker over the human accounts the machine reported, as `instances_panel.tsx` draws one |
| **Windows login for {account}** | on Windows alone, a `VaultPicker` that adds a login in place, with no link to the Credentials page |
| **CPUs**, **Memory (GiB)** | number fields, 0 for Podman's default, `ui.containers.run_default_hint` under them on macOS and `ui.containers.run_default_hint_windows` on Windows |
| **Disk limit (GiB)** | a number field whose least value is the disk's size now, as the machine reported it, and on Windows at least 1, with `ui.containers.run_disk_hint` under it; it follows Podman Desktop's **Edit** form for a machine, where the disk size only grows. On Windows the field starts at 100 while the stored Run settings name no account. The apply bar is disabled, and the field shows the code's words in place of the hint, while the value is below 1 on Windows, `code.machine_disk_invalid`, or above 0 and below the disk's size now, `code.machine_disk_shrink` |

The group is one `settings_group` with its own apply bar,
`ui.containers.run_apply`. While it is dirty, the bar's warning is
`ui.containers.run_restart_warning` when the CPUs, the memory or the disk
changed on a machine that exists, one the report names for the draft's
account (`machine_state.account`), followed on Windows by
`ui.containers.run_wsl_warning`; and `ui.containers.run_account_warning`
when the account changed. Until the stored Run settings name an account,
the three panels under it draw `ui.containers.run_needed` in place of their
content, and their apply bars are disabled.

Each apply bar of the tab, Run settings, mirrors and containers, stays busy
after its press until the machine reports the module where its `want` asks,
at most two minutes, as `instances_panel.tsx` waits. Under `running` that is
`running` or `stopped` on Linux, and on Windows and macOS `running` with the
stored account's machine running; under `stopped` it is `stopped`.
`ui.api.applied` shows only then, and a failure shows as the tab's notice.

The container editor has a **Services** row under its three lists,
**Ports**, **Volumes** and **Environment**, on every system: one line per
host port the draft's **Ports** publishes, in that list's order. A line
holds the port, a picker of **Auto**, **Web** and **Port**, and with **Web**
a choice of **http** or **https**, with **Port** two checkboxes, **TCP** and
**UDP**, at least one checked. **Auto** shows what the machine detected,
`ui.containers.service_detected` with the scheme or `tcp`, or
`ui.containers.service_pending` before the container runs. A line appears
with a port added to **Ports** and goes with a port removed; the row is part
of the editor's draft, and the apply bar writes it with the container
([protocol.md](protocol.md), "The modules section, one entry per module").

The AI tools part follows the client's AI page ([client.md](client.md), "The
AI page") and adds nothing to it:

| Control | Enabled | Does |
| --- | --- | --- |
| **This machine's AI tools use the hub's AI gateway** (a chip) | when the machine's agent is online and no write of this part is in flight; turning it on also needs the gateway to serve a model, else the reason `code.gateway_not_serving` is under the chip | reads on while `is_in_use`, any account still on the gateway, and off only once every account is on its own settings; pressed while on it sends `ai_tool/disable`, while off `ai_tool/enable`, at once, as a module's buttons on this page act ([protocol.md](protocol.md), `/api/agent/module`); so after a switch back that failed it still reads on, and a press tries the switch back again |
| **Configure** | when the machine's agent is online | opens the client's dialog in place, the inline-form idiom with a dirty frame: a picker per tool for its model over the gateway's models and, for Codex, its effort; **Save** sends `ai_tool/set` and **Cancel** closes it |

Under the controls, the line `ui.ai_tools.accounts` names the accounts the
setting acts on, and a row per account follows: its name, the modules it has
an instance in, and its last result as a `StatusDot` with a word (`switched`
`ok`, `switched_back` `idle`, `failed` `error` with the code's words, and
`ui.device_monitor.waiting` `idle` before the machine reported it while the
setting is on; with the setting off, an account the machine does not name
keeps its own settings and reads as `switched_back`, since no report of it
will come). With no
such account the line is `ui.ai_tools.no_accounts` and no row is drawn; the
chip can be turned on all the same, and an account gained later is switched
then.

## Account sign-in on the AI page

An account sign-in runs in a dialog on the **AI** page's **Accounts**
surface ([hub_components/ai.md](hub_components/ai.md), "What each panel surface owns"),
which the page polls with `GET /api/hub/ai/gateway/account_login` until the
gateway reports the flow `complete` or `failed`.

| Rule | Reason |
| --- | --- |
| When the hub's session for the flow ends before the gateway reports either, the route returns `login_expired`, and the dialog stays open on the screen it was showing, with the code's words under it. It never resets to its first screen. | A person who sees the first screen again cannot tell a timeout from a click that did nothing. |
| A flow that ends `failed` shows the gateway's own reason, the view's `message`, under the code's words when the gateway sent one. | The gateway's reason names the provider's refusal, which the code alone cannot. |

## An interaction this document does not cover

Before designing one, establish that it is not generic. **Where an established
website or app already has this feature, follow its logic** rather than
inventing another, and name the app you followed in the summary of the change.
Most interactions somebody reaches for here — a filter row, a detail drawer, a
masked secret, a confirm-before-delete — already exist above, and a third idiom
for a thing that has one is worse than a plain copy of it.

Only a genuinely novel interaction is a decision, and it is the user's: ask
before building it, not after.
