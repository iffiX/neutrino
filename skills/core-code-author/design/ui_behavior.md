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
something the whole page is about: `Add over SSH`, `Declare a service`, `New
Web share link`. Those sit in `page_actions`, and a page with none is the
normal case.

A header action that adds a record (**Add by link**, **Add over SSH**, **New
client link**, **New Web share link**, **Declare a service**) opens a dialog in the style of the install
dialog (`install_agent_modal.tsx`). The dialog holds the form, the link or the
QR it produces, and the output of the task it starts; the page itself never
shows an add form or a produced link inline. A header add wears
`button--primary`, and `page_actions` gives it the glow ([visual.md](visual.md),
"Buttons come in three tiers"). The other shape, the add of one
entry inside a panel, is the inline form below, and which of the two an add
takes is decided by where its button sits.

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
in the panel's header. Inside a panel one button is `button--primary`: the one
at its foot that commits, the apply bar's button or the save of its inline
form. Every other action of a panel, its header's add included (`Add
provider`, `Sign in`, `Add key`), is the bordered `button`: a page holds many
panels, and an accent on each of their adds leaves the apply nowhere to be
found.

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
to nothing says so differently from a list that is empty: `No matches` with
`Try a different filter or clear the search.`, against the list's own empty
state ("Empty states and loading").

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
`device_monitor`). The menu lists the row's actions, and an item that arms
keeps the menu open, so the second press acts.

## Inline forms

A record of a panel is added where its list is. The panel's own add (`Add
node`, `Add key`, `Add login`) opens a form in place, as the Proxy page's node
form does: the entry being added or edited is an `inline_form`, the accent
frame in cyan, and every other entry keeps its plain frame. The amber frame,
`settings_group--dirty` or `card--dirty`, is the whole panel's outer frame
alone, lit with its apply bar while the panel holds something unapplied, and
is never on an entry. A Cancel sits beside its save; nothing navigates away
to add one thing, and the same form edits an existing record where the record
is editable at all; a credential is not (see Secrets). An add from the page
header is not this form but a dialog (The page, above).

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
(`Delete the container web`), a body of one or two sentences saying what it costs
with the mechanism first, and the action's own verb on the button. Escape and
the backdrop cancel.

**The body states the concrete consequence, cascades included.** A delete that
clears references says how many and whose: `2 devices lose this key and will
need a new one`. `credentials_page.tsx` composes these from the reference counts
the API returns.

The confirming button is `button--primary` and wears the action's verb; the red
is spent on the button that opened the dialog, not on the one that closes it.
A module's **Uninstall** whose data goes with it is the one exception: its
line is red and its confirming button is `button--danger` ("The machine
page").

Settings are not confirmed here. A group of them ends in an apply bar, and the
bar's `warning` is where its cost is stated. Deleting data that cannot be
re-derived asks for more than a press: the name typed back, in a red-bordered
box inside the card rather than in this dialog ([visual.md](visual.md)). A
module's uninstall asks in the dialog alone, the same dialog for every module.

## Modals, and where a record's detail lives

The panel has no drawer: nothing pins to the right edge over a list, and a
list page has no second level. A record with sections of its own is a page:
a managed machine's monitor, its modules and its agent are `/agents/<id>`,
one entry per machine in the sidebar's agent group ("The machine page"). A
record edited in one or two fields is edited in its row: a device's name and
icon on the Agents page,
a client's name and permission on the Clients page, the row lit as the inline
form is while the edit is open. A setting that belongs to a whole panel, the
clients' default permission, is a dialog from the panel's header.

Actions that are not part of a record, reboot, wake, install, act at once from
their own row, and the output of a task they start streams into the dialog
that started it or into the row's own log line.

A **modal** is for one interaction that must finish before anything else: a
confirmation, a terminal session, a file transfer, an install consent, an add
from a page header. A QR code in a dialog is an image, an
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
`Reveal` / `Hide` and a copy button beside it. Each **Reveal** and each copy
is a request the hub writes to its journal, naming the secret and the panel
session's address ("The Credentials page").

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
bottom of the dialog that started the task. Nothing in this panel is announced
in a toast and dismissed; an install is a thing you read.

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
text. The box shows the module's own journal in every state, the lines its
program writes once it runs, and reads empty for a program that has not
written yet. It never shows the lines of the module's task: the
`step <i>/<n>` lines, the failure's code and the install commands' output
stay in the hub's task record and the agent's own log. A module that failed
shows the agent's code as its error line under its state, and an apply that
ended in a failure shows no success notice.

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
beside the component that shows it: `devices_page.tsx` (`ACTION_ERROR_KEYS`)
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
| 5–10 s | A list or a badge that changes on its own — services, devices |
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
module, and its tab on the machine page is the reference:

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

## The Agents page

The **Agents** page (被控端), at `/agents`, is one table of the managed
machines, one row each, every row the same height. Every machine on it was
added as an agent, so the page and its sidebar entry in the hub group take
the agent's name. The sidebar's machine group below the hub group is headed
with the same word and lists each machine on its own, a link to its machine
page; the hub group's entry opens this table of all of them. A panel address
`/devices` from 0.5 answers with the panel's redirect to `/agents`.

A row holds the icon, a button that opens a small picker of the device icons
under it and writes the pick at once; the status dot; the name, a link to
`/agents/<id>`; the address; the MAC; the status cell; the agent's version;
when the agent was last seen; and the row's actions as ghost buttons:
**Manage**, **Rename**, **Wake**, **Reboot**, **Shut down**, and **Forget**
last in the danger tier. **Rename** turns the name into an input and the
actions cell into **Save** and **Cancel** alone. The actions are
right-aligned in their cell, as the Clients page's are.

The status cell of a reporting machine is five ring gauges, 30 px each, the
integer inside and a label under: CPU, memory, disk, GPU and temperature, in
the tones `device_gauge` uses, the temperature ring warning at 70 and failing
at 85. The GPU ring shows the busiest card and wears a `×N` badge at its
corner when the machine has more than one; a machine with none has no GPU
ring. An offline machine's cell reads `Offline · <ago>`. A machine whose
row holds a token and no static key joined under 0.5, and it stays offline
until its agent is reinstalled and joins again. Its cell reads the words of
`code.hub_key_missing` in place of `Offline · <ago>`
([transport.md](transport.md), "A peer of 0.5"). The rings move on the
`metrics` event and ask for nothing.

The page has no filter chips, no legend, no search box, no scan and no drawer.
Its title carries `<n> agents, <m> online`, and its header holds two primary
buttons, both dialogs: **Add by link** (用链接添加), for a machine that joins
on its own, which asks **Name**, the machine's host name when it is left
empty, and whose **Generate link** shows the enrolment link and its QR in
the same dialog, as **New client link** does on the Clients page with no
permission, since an agent's binding has none; and **Add over SSH** (用
SSH 添加), the install dialog with **Host**, **Port**, **User name**,
**Credential**, **SSH key** and **Sudo password**. That dialog's button creates
the machine's row, named by its host until it reports, and starts the install
([protocol.md](protocol.md), `POST /api/hub/device/add`). Wake-on-LAN stays
on this page: it is a packet on the network and needs no agent
([protocol.md](protocol.md), `POST /api/hub/device/wake`). The words are
[ui_text.md](ui_text.md), "The Agents page's words".

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
| Settings | configurable, a `settings_group` with its own apply bar | **Server**, **SSH port**, **Account**, **Credential** and **Public port**, then the vault picker of the credential chosen. **Credential** is the **Add over SSH** dialog's picker, with its words and the hint `ui.overlay.relay_credential_hint`: **SSH key** shows the picker of the vault's SSH keys, **Password** the picker of its logins, and the request names the one picked as `key_id` or `login_id`, as the install's does. No link to the Credentials page. The bar's label is **Apply SSH relay**, its hint `ui.overlay.relay_apply_hint`, and its warning `ui.overlay.relay_apply_warning` while the relay is `connected` |

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

## The Services page

An app's row shows its machine's name beside its title, or its first
entry's host when no machine the hub knows is there. Each entry shows its
kind and the local address a client's Apps page shows for it
([client.md](client.md), "The Apps page"): `<scheme>://<local
name>:<local port><path>` for a `web` entry, and `127.0.0.1:<local port>`
for a `port` entry, with `/udp` after a UDP one. A declared app's `file`
entry, which has no local port, shows its share as `//<host>/<share>`. The
page leaves out a `web` or `port` entry's payload address, since a program
such as VS Code listens on its machine's loopback alone. It shows no `ssh`
entry and no row for a machine's SSH server, which is no app
([protocol.md](protocol.md), "Apps").

An app's row with a `web` entry carries **Share** (分享), a ghost button
that opens the Clients page's Web share dialog with that entry chosen ("The
Clients page"). An app with no `web` entry has no **Share**.

## The Clients page

The **Clients** page, at `/clients`, is who reaches the hub's machines from
outside the panel, in two panels, **Clients** (客户端), one row per enrolled
device with what each is allowed, and **Web shares** (Web 分享), one row per
share. The page's header holds two primary buttons, both dialogs, **New
client link** and **New Web share link**. **Default permissions**, a
bordered button in the Clients panel's header, opens the default's dialog.

**New client link** (新建客户端链接), in the page's header, opens a dialog in
the install dialog's style that adds one device. It asks **Name** and the
permission, the permission form below with **Follow the default** on, and
its foot is **Generate link** (生成链接), disabled while the name is empty.
The press creates the client's row and its link ([protocol.md](protocol.md),
`/api/hub/client`), and the same dialog then shows the link in mono with a
copy button, its QR under it, and `ui.clients.enrollment_hint`, which says
the link works for 30 minutes; the form goes, and the foot becomes **Done**.

A row whose device has not joined waits: in place of its host name, its
system and its version it reads `ui.clients.waiting {minutes}`, the minutes
`link_expires_in_s` leaves, counted down between the page's reads of the
list. Its actions are **Permissions** and **Delete**, whose dialog says
that the link stops working. The hub removes the row when the link expires
unused, and the page's next read drops it; a join makes it an ordinary row
with the permission it waited with.

**New Web share link** (新建 Web 分享链接) opens a dialog in the same style
that makes one share ([protocol.md](protocol.md), "Web shares"). The Services
page's **Share** on an app's row opens the same dialog with the app's `web`
entry chosen ("The Services page").

| Field | Idiom |
| --- | --- |
| **Name** | a text field, required |
| **App** | the panel's picker over `web_share_entries`, each the app's title and its machine's name; a share offers nothing else |
| **Expires** | **1 day**, **7 days**, **30 days** or **Until revoked**, one choice of four, **7 days** chosen at the start |
| **Site** | the picker over `web_share_sites`, the first chosen at the start, and **Another site**, which shows a field for an `https://` address |

While the chosen app's `guest_login` is `run_account`, the dialog shows
`ui.web_shares.run_account_warning {account}` under **App** in the warn tone
([visual.md](visual.md), "Colour carries one meaning each"), `{account}`
being the entry's `visitor_account` ([protocol.md](protocol.md), "Web
shares"); no other app shows a line there.

| Rule | Reason |
| --- | --- |
| The warning stays under **App** while that app is chosen, and **Generate link** stays live. | A visitor of such an app is signed in as the account the app runs as, and the owner reads that before the link exists; the choice is the owner's. |

Its foot is **Generate link**, disabled while the name or the app is empty.
The press makes the share, and the same dialog then shows the link in mono
with a copy button, its QR under it, and `ui.web_shares.link_once`; for an
app whose `guest_login` is `guest_account`, the guest account's e-mail in
mono with a copy button and `ui.web_shares.guest_hint`. The form goes, and
the foot becomes **Done**.

The Web shares panel lists the shares, newest first, one row each: the
name; the app's title and its machine; when it expires,
`ui.web_shares.expires_in {days}` or `ui.web_shares.until_revoked`; its
state as a dot and its word; `ui.web_shares.online {count}`; for a guest
account, its e-mail in mono with a copy button; and **Revoke** last, in the
danger tier. **Revoke** asks through `useConfirm`, the title
`ui.web_shares.revoke_title {name}`, the body `ui.web_shares.revoke_body`
and, for a guest account, `ui.web_shares.revoke_guest {email}` after it,
and the button **Revoke**; it acts at once, as a revocation does ("When an
effect happens"). A share that ends, at its expiry or by **Revoke**, leaves
the list at the page's next read, and the hub keeps nothing of it
([protocol.md](protocol.md), "Web shares").
With no share the panel shows `ui.web_shares.empty` and its hint.

| Rule | Reason |
| --- | --- |
| The state's tone follows "Status dots and badges": `active` is `ok`, `preparing` is `warn`, `unavailable` is `idle` and `failed` is `error`, with the code's words under the row. | A share's word is read at a glance beside its count. |
| The panel reads `GET /api/hub/client` on the list cadence, so the count and the state move by themselves. | A share's visitors come and go while the page is open. |
| A visitor has no row anywhere in the panel. | The share is what the owner manages: one press ends every visitor's access. |

**The permission form.** One form, `client_permission_form.tsx`, edits
every permission ([protocol.md](protocol.md), `/api/hub/client`): the
default's dialog, a client's row, and the client link dialog. It reads
`permission_kinds` and `permission_rows` from `GET /api/hub/client` and
works out no row itself.

| Part | What it holds |
| --- | --- |
| **Follow the default** | in a client's row and in the link dialog: a switch that, while on, shows the default's values and sends none of its own |
| a kind | one line per kind in `permission_kinds` order: its switch, and for every kind but **Virtual network** and the panel the chip **All agents**, which opens the machine checklist under the line |
| **Choose per app** | a switch at the form's foot, the fine mode of [protocol.md](protocol.md), `/api/hub/client`; off, the form is the coarse mode. While it is on, each kind with rows lists them under its line, one line per row: the row's title, its machine's name and a switch |
| a row's switch | shows what the judging function gives the row now. A press stores the row with the value it then shows, and a stored row has **Follow the kind**, a ghost button that takes it out again |

| Rule | Reason |
| --- | --- |
| Every kind has the same two positions, and a row has the same two. | On is the hub handing the credential and signing the client in; nothing in between asks for a password. |
| The form opens with **Choose per app** on when the permission's `entries` holds a row, and off otherwise. | The coarse mode is what most permissions need, and a permission with exceptions shows them at once. |
| Turning **Choose per app** off takes every stored row out at the apply, and the apply bar's warning says so while it is off with rows stored. | A row the mode hides still decides its app. |
| A kind lists every app of its kind on every machine, whatever its chip names. | A row is how one app on a machine the kind leaves out is given. |
| An app with entries of two kinds is a row under both, and a press on either switches both. | The two lines are one id ([protocol.md](protocol.md), `/api/hub/client`). |
| A kind with no rows yet shows `ui.clients.rows_empty` under its line while **Choose per app** is on. | A kind with nothing published reads as empty, and its line keeps its place. |

## The Credentials page

The **Credentials** page, at `/credentials`, holds four sections: **SSH
keys**, **Logins** and **Tokens**, the secrets the hub is given, and
**Generated by the hub** (中枢生成的), the ones it made for the machines
([protocol.md](protocol.md), `/api/hub/credential`).

**Generated by the hub** lists one block per machine, under the machine's
name, and in it one row per secret:

| Row | Its value | Its buttons |
| --- | --- | --- |
| `ui.credentials.smb_password {account}`, one per account the machine's file share enables | masked, the password in mono after **Reveal** | **Reveal** / **Hide**, **Copy**, **Rotate** |
| `ui.credentials.seat_password`, while the machine's Remote desktop module has one | the same | the same |
| `ui.credentials.ssh_key {account}`, one per account the machine's SSH server enables | its fingerprint, `SHA256:<base64>`, in mono and in the clear | **Copy**, which copies the fingerprint, and **Rotate** |

| Rule | Reason |
| --- | --- |
| **Reveal** and **Copy** of a password each send `generated/reveal`, which the hub logs; **Hide**, and leaving the page, drop the value. | A person types a password by hand now and then, on a machine with no client or in a plain RustDesk viewer, and a log shows when one was read. |
| An SSH key shows its fingerprint and never its private half. | The fingerprint is what a person checks a key against, and the private half belongs to the clients the hub hands it to. |
| **Rotate** asks through `useConfirm`, the title `ui.credentials.rotate_title {name}` and the body for its kind, `ui.credentials.rotate_smb_body`, `ui.credentials.rotate_seat_body` or `ui.credentials.rotate_ssh_body`, and acts at once on **Rotate**, as a revocation does ("When an effect happens"). | A secret that leaked, or that a removed client copied, ends with one press, and the dialog says what stops working. |
| The section shows `ui.credentials.generated_empty` while no machine has a generated secret. | The list fills by itself as modules are enabled. |

## The machine page

The machine page, `/agents/<id>`, is one managed machine: what it does now,
what it hosts, and its agent. Its header holds the machine's name, its
online dot, the chip `ui.machine.agent_version` with the agent's version,
the system and the architecture, the host name and the address, and at the
right one bordered `button`, **Agents** (`ui.nav.devices`), back to the
table. Three sections follow, top to bottom; what each reads is
[protocol.md](protocol.md), "The agent group":

| Section | Holds |
| --- | --- |
| **Monitor** (`ui.machine.monitor`) | four number tiles, uptime, load over 1, 5 and 15 minutes, disk and temperature, the last two toned by their thresholds; then the CPU and memory charts, one chart per GPU, and the process table; an offline machine shows `ui.device_monitor.waiting` alone, and a machine that joined under 0.5 the words of `code.hub_key_missing` in its place |
| **Modules** (`ui.machine.modules`) | **Available accounts**, then **Module configuration** |
| **The agent** (`ui.machine.agent`) | four rows, the version, the platform, the host name and the last report; and two bordered buttons, **Update agent** and **Reinstall**, the latter opening the **Add over SSH** dialog for this machine. Forgetting a machine is on the Agents page alone |

A machine that has not reported yet shows its name and `ui.device_monitor.waiting`
in each section, and an id the hub holds no row for shows
`ui.machine.not_found` with the **Agents** button alone.

**Available accounts** (`ui.accounts.title`) is the machine's accounts the
person added ([agent.md](agent.md), "The two layers and the accounts"). A
new machine shows none, with `ui.accounts.empty` and its hint; **Add**, a
bordered `button` at the panel's top right, opens the inline form under the
list, the panel add of "Inline forms", lit with the accent frame:

| Field | Idiom |
| --- | --- |
| **System account** | the panel's own picker over the accounts the machine reports that are not yet available, `system_accounts` |
| **Password** | on a Windows machine alone, a password field kept in the vault as the account's login; left empty on an edit, the login stays |
| **Share path** | a text field showing the account's home as its placeholder, with **Browse…** opening the path window in its folder mode; left empty, it sends empty and the default holds |
| **Shell** | a text field showing the account's login shell as its placeholder, PowerShell on Windows, with **Browse…** opening the path window in its file mode; left empty, it sends empty |
| **AI tools use the hub's gateway** | a switch, off by default; turned on, it shows the model rows: Claude Code's four slots, Codex's model and its effort, and Gemini's model, each picker's first choice `ui.ai_tools.gateway_default` |

**Cancel** and **Save** sit at the form's bottom right. A row shows the
account's name, and while its AI tools switch is on the result as a
`StatusDot` with a word, with **Edit** and **Remove** at its right, its
content centred; **Edit** opens the same form in the row's place. **Remove**
asks through `useConfirm`, the body naming the modules that lose the
account (`ui.accounts.remove_body`, or `ui.accounts.remove_body_none` when
none enables it).

**Module configuration** (`ui.modules.tabs_title`) is a left and right
split: on the left a vertical, scrollable list of the machine's modules, the
rows `GET /api/agent/module` marks `is_shown`, the first one picked when the
page opens and the picked one kept in the address as `?module=`, each
row the module's icon (`images/icons/modules/<module>.svg`, the generic glyph
for a module without one) and its title, and under it **+ Add module**, a
bordered button as wide as the list; on the right the picked module's tab.
A tab reads, top to bottom: its state line; `ui.modules.log_title` and the
log box; `ui.modules.config_title` and the module's panel, which **Configure**
opens and **Hide configuration** closes; and the buttons **Install**,
**Start**, **Stop**, **Uninstall** and **Configure** at the bottom, aligned
to the right edge.

In a window 880 px wide or narrower, or one no wider than it is tall, the
split is one column. The module list is then one row above the picked
module, and that row scrolls sideways.

**+ Add module** opens the module catalog, a dialog in the install dialog's
frame, wider: the title with a search box at its right, a row of activity
filters (`ui.module_catalog.category_<id>`, **All** first), and a grid of
cards, each the module's icon, its name, one line on it, its activity and a
check at its top right. Checking a card adds its tab, and unchecking takes
it away; Terminal, Remote desktop and the SSH server are checked and locked,
since the agent carries them, a module installed on the machine stays
checked, a module the machine cannot run is greyed out, and a module the hub
has no manifest of yet is drawn with no check. The dialog's foot holds
**Close** alone.

A tab of the account layer, File share, Terminal, the SSH server, VS Code,
code-server, CloudCLI, Codeg and SiYuan, holds **Enabled accounts**
(`ui.modules.enabled_accounts`) in its panel: one check row per available
account, Terminal's showing each account's shell and the file share's each
account's share path, and `ui.modules.no_accounts` pointing at **Available
accounts** while there is none. The panel is configurable, with its apply
bar; an account checked goes to the end of the order, and each row shows the
module's own field, its running dot and its code's words. The bar's hint is
`ui.modules.stopped_hint` while the module's `want` is `stopped`, and the
module's own hint otherwise, on every tab but Terminal's and the SSH
server's, which have no **Start**. An apply under `stopped` keeps the
module stopped, and its bar waits for `stopped`. The tabs of the
machine layer,
Remote desktop, Gitea, Containers and the container modules, hold no
accounts. No module asks for a port: the agent takes them.

The File share tab's panel holds two panels, one under the other, one for
each kind of share ([agent/modules/file_share.md](agent/modules/file_share.md)):

| Panel | Idiom |
| --- | --- |
| **Home shares** (`ui.samba.home_shares`) | the tab's **Enabled accounts** under this title, with `ui.samba.home_shares_hint` under it: one check row per available account showing its share path, one Home share per checked account; configurable, with its apply bar |
| **Folder shares** (`ui.samba.folder_shares`) | one row per folder share, with `ui.samba.folder_shares_hint` under the title, and `ui.modules.stopped_hint` under it while the module's `want` is `stopped`, and **Add** (`ui.samba.folder_add`), a bordered `button` at the panel's top right that opens the inline form under the list, the panel add of "Inline forms", lit with the accent frame |

| Field of the folder share form | Idiom |
| --- | --- |
| **Name** (`ui.samba.folder_name`) | a text field; an edit shows the name and does not change it |
| **Folder** (`ui.samba.folder_path`) | a text field with **Browse…** beside it, opening the path window in its folder mode |
| **Accounts** (`ui.samba.folder_accounts`) | one checkbox per account **Home shares** enables, in its order |

**Cancel** and **Save** sit at the form's bottom right, and **Save** is
disabled while the name or the folder is empty or no account is checked.
**Save** writes at once, `folder_share/add` or `folder_share/set`
([protocol.md](protocol.md), "`/api/agent/module`"), as the form of
**Available accounts** does. A row shows the share's name, its folder in
mono and its accounts, with **Edit** (`ui.samba.folder_edit`) and **Remove**
(`ui.samba.folder_remove`) at its right; **Edit** opens the same form in the
row's place. **Remove** asks through `useConfirm`, the title
`ui.samba.folder_remove_title {name}` and the body
`ui.samba.folder_remove_body {path}`, and acts at once. With no folder share
the panel shows `ui.samba.folder_empty`. While **Home shares** has no
account applied, **Add** is disabled with `ui.samba.folder_no_accounts` as
its reason.

| Rule | Reason |
| --- | --- |
| **Folder shares** writes each add, edit and remove at once and has no apply bar, while **Home shares** stages. | A folder share is a record the person adds, as an available account is; the Home shares are the module's one setting. |
| The checkboxes list the accounts **Home shares** enables as applied, not the draft. | A folder share's account logs in with the SMB user that enabling the account makes. |
| A folder share's name does not change after **Save**. | A permission's row and a client's mount name the share by it ([protocol.md](protocol.md), `/api/hub/client`). |

A module the machine reports `installed`, `stopped` or `running` while
the hub holds no `want` for it, as after a reset or a new join on a machine
that kept its modules, has **Start** live, whatever its state; the press
and an apply of its configuration give it the `want` `running`
([protocol.md](protocol.md), "Taking over a machine").

A module the machine reports `queued` is in transit, as `installing` and
`uninstalling` are: every button of its tab is disabled until the machine
reports another state, and the tab names what it waits for by the row's
code ([agent.md](agent.md), "Step locks"). Every button of a module's tab is
also disabled while its row's `task` runs, a configure task's among them.
After a press, the tab's optimistic step holds until the machine reports the
module in a state other than the one it showed at the press, at most two
minutes.

A module's tab shows its task's steps under the state line, one line each
in the plan's order: done, running, waiting with the words of what it waits
for, such as "waiting for the package manager, held by File share", and not
yet run. A failed step reads in the error tone with its code's words under
it. A wait's words and a failure's words show under their step, and no
notice of the tab repeats them. The notice at the top of the tab words a
row's code where the step list does not. Such a row has no task, as an
`absent` row with a code or a failed row after the agent restarted
([agent.md](agent.md), "A failure outlives a restart"), or is a failed row
whose next task runs. A `reboot_required` row words its code in the notice
alone, beside **Restart now**, and its `restart` step reads waiting with no
words under it. A step's words are
`ui.modules.step.<name>` with its params, or an artifact's or an image's
own words ([ui_text.md](ui_text.md), "A module task's words"), a lock's
`ui.modules.lock.<lock>`, and a wait's the code catalog's. A finished
task's steps stay until the next task starts. The module list shows `<i>/<n>`,
the running step's index and the plan's length, beside the spinner of a row
whose task runs ([agent.md](agent.md), "The steps").

A module reported `install_failed` has an `error` dot in the module list.
Its tab reads `state.install_failed` beside the same dot, and shows the
code's words as a `failed` module does. **Install** and **Uninstall** are
live, and **Start**, **Stop** and **Configure** are not:
**Install** runs the install again, and **Uninstall** removes what the
install left ([agent.md](agent.md), "An install that fails ends
install_failed"). No module has a **Cancel** button.

A module reported `installing` with a code shows the code's words under its
waiting step, `reboot_required` excepted, and its buttons stay disabled as
for any module in transit. A
module reported `absent` with a code shows the code's words as a notice at
the top of its tab, and its buttons are those of any `absent` module. A
`reboot_required` row shows the same notice with **Restart now**
(`ui.modules.restart_now`), which asks through `useConfirm`
(`ui.modules.restart_title`, `ui.modules.restart_body`) and sends `POST
/api/hub/device/reboot`. The agent never restarts the machine itself, and
the install goes on after the restart with no press ([agent.md](agent.md),
"Status is typed").

**Uninstall** asks through `useConfirm`, one dialog for every module: the
title `ui.modules.uninstall_title`, the body `ui.modules.uninstall_body`, and
under it the module's own line, the row's `uninstall_data` text in the
panel's language ([agent/module_install.md](agent/module_install.md), "The
manifest"):

| The row's `uninstall_data` | The line | The confirming button |
| --- | --- | --- |
| `is_deleted` true | in the error tone | `button--danger`, `ui.modules.uninstall` |
| `is_deleted` false | body text | `button--primary`, `ui.modules.uninstall` |

The line is the manifest's words, never composed on the page, so the dialog
says the same thing for a module on every machine of its system. A module
the agent carries has no **Uninstall** and no line.

A module whose last report is `failed` keeps the button of what it was
asked for live: **Install** while its `want` is `installed`, **Start** while
it is `running`, **Stop** while it is `stopped`, and **Uninstall** always.
That press tries the same step again ([agent.md](agent.md), "A retry is the
same press again"); there is no other retry button. A module panel's apply
and **Configure** on a refused configuration try again the same way. A
press, or a module panel's apply, on a module whose state is not its `want`
after the press asks the machine to apply it again, as **Start** on a module
that reads `installed` while its `want` is `running` does. A press on a
module that reads its `want` asks for nothing new.

A module's tab shows a version line under its state line once the module is
installed, from `GET /api/agent/module/version`
([agent/module_install.md](agent/module_install.md), "Module versions"); a
module that is not installed shows its state, its log box and its buttons
alone, and its **Install** installs the version the machine chose, the
tested one when it chose none. Terminal, Remote desktop and the SSH server
show no version line: they are the agent's, whose version **The agent**
shows:

| Part | Idiom |
| --- | --- |
| The version line | `ui.modules.version_installed` with the version the machine reports, then `ui.modules.version_newest` with the newest listed version when the two differ |
| **Update** (`ui.modules.update`) | a bordered `button` beside the line, live while the newest version differs from the one installed and the module is installed and not in transit; it sends `POST /api/agent/module/version/set` with the newest version |
| **Install another version…** (`ui.modules.install_version`) | a bordered `button` beside it, live under the same conditions; it opens a dialog listing the versions newest first, the tested one marked `ui.modules.version_tested` and each newer one `ui.modules.version_untested`, with **Follow the tested version** (`ui.modules.version_follow_tested`) at the top; a press on a row sends `version/set` with that version, or empty for the top row, and closes the dialog |
| A version older than the one installed | on a module whose manifest says `is_data_forward_only`, the press asks through `useConfirm` first (`ui.modules.downgrade_title`, `ui.modules.downgrade_body`) |
| A locked version | a module of the `builtin` or `system` method, and a `container` module whose manifest names no `releases`, shows the same line and buttons: **Update** disabled, and **Install another version…** opening the dialog with its one version as a row that cannot be pressed and no **Follow the tested version** row |

There is no switch that updates a module by itself. A `version_switch_failed`
shows under its step, as any `failed` module's code does, with the old
version on the version line.

The rows of the module list, each a tab, come in one order, the modules
every system runs first: File share, Terminal, the SSH server, Remote
desktop, Gitea, VS Code, code-server, CloudCLI, Codeg, SiYuan, Containers, Hermes
WebUI, Ayakaleaf. The eight modules of the account layer are drawn by one
`instances_panel.tsx` from the hub's description table. A module the machine cannot
run is left out, as before ([agent.md](agent.md), "Which modules each system
runs").

Terminal, Remote desktop and the SSH server are a tab on every managed
machine, checked and locked in the catalog. Their tab draws the module's
state line and its panel, and none of **Install**, **Start**, **Stop**,
**Uninstall**, **Configure** or the output box, since the agent's package
carries them:

| Tab | Its panel | Idiom |
| --- | --- | --- |
| Terminal | **Enabled accounts**, each check row showing the account's shell | one configurable `settings_group` with its own apply bar, `ui.terminal_module.apply` |
| SSH server | **Enabled accounts**, and the machine's host key fingerprint in mono under them, `ui.ssh_server.host_key` | one configurable `settings_group` with its own apply bar, `ui.ssh_server.apply` |
| Remote desktop | one switch, `ui.remote_desktop_module.switch`, with its description | one configurable `settings_group` with its own apply bar, `ui.remote_desktop_module.apply`; a failed step shows its code's words under it, and the apply bar's Apply tries again |

The Hermes WebUI tab draws the line `ui.hermes_webui.owner_notice`, or
`ui.hermes_webui.owner_notice_version` once the machine reports the version,
over its state, its log and its buttons; it has no panel, since the agent
takes its port.

The tab holds no link to the page: a client opens it from its **Apps** page
with the token the hub hands ([agent/modules/hermes_webui.md](agent/modules/hermes_webui.md),
"The page").

The Ayakaleaf tab draws the line `ui.ayakaleaf.owner_notice` over its state,
its log and its buttons, and holds no link to its page either. Its panel is
one configurable `settings_group` with its own apply bar,
`ui.ayakaleaf.apply`, around one field
([agent/modules/ayakaleaf.md](agent/modules/ayakaleaf.md), "The model"):

| Control | Idiom |
| --- | --- |
| **AI model** (`ui.ayakaleaf.model`) | the panel's picker over the view's `models`, its first row `ui.ai_tools.gateway_default`, with `ui.ayakaleaf.model_hint` under it; while `is_gateway_serving` is false the picker is disabled and `code.gateway_not_serving`'s words take the hint's place |

While the group is dirty the bar's warning is `ui.ayakaleaf.apply_warning`,
and the bar stays busy after its press until the machine reports the module
`running` again, at most two minutes.

The path window is the one the account form's **Browse…** opens
(`directory_picker_modal.tsx`); its file mode opens at the field's path, or
at the machine's root, lists files beside folders, and a press on a file
hands its path back. The Agents page holds no desktop section: the Remote
desktop tab is the one place the share is set, and it shows beside the
switch the RustDesk state with **Reset seat password**, and the AnyDesk and
TeamViewer detection with their unattended passwords.

On Windows and macOS the tab of a container module whose `want` is not
`absent` shows `ui.modules.memory_need {memory, need}` as a warn notice
under its state line while the module list's `memory_need` is set
([agent/modules/containers.md](agent/modules/containers.md), "Memory for the
container modules"). It is a hint: every button stays as its state makes it.

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
| **Account** | a picker over the machine's available accounts; on Windows the account's login is the one its form holds |
| **CPUs**, **Memory (GiB)** | number fields, 0 for the default, `ui.containers.run_default_hint` under them on macOS and `ui.containers.run_default_hint_windows` on Windows; under **Memory (GiB)** `ui.containers.run_memory_need {need}` while the view's `memory_need` is set and the field holds less than its `need_gib` |
| **Disk limit (GiB)** | a number field whose least value is the disk's size now, as the machine reported it, and on Windows at least 1, with `ui.containers.run_disk_hint` under it; it follows Podman Desktop's **Edit** form for a machine, where the disk size only grows. On Windows the field starts at 100 while the stored Run settings name no account. The apply bar is disabled, and the field shows the code's words in place of the hint, while the value is below 1 on Windows, `code.machine_disk_invalid`, or above 0 and below the disk's size now, `code.machine_disk_shrink` |

The group is one `settings_group` with its own apply bar,
`ui.containers.run_apply`. The bar's hint is `ui.containers.run_apply_hint`,
and `ui.modules.stopped_hint` while the module's `want` is `stopped`.
An apply under `stopped` keeps the settings for the next **Start**
([agent/modules/containers.md](agent/modules/containers.md)). While it is dirty, the bar's warning is
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
`ui.api.applied` shows only then, and a failure shows under its step.

On every system the tab has **Hub containers** (`ui.containers.hub_title`)
between **Running now** and **Registry mirrors**: one read-only row per hub
container, with its module's title, its image, its ports and its volumes,
`ui.containers.hub_hint` under the title, and no editor or apply bar. While
no module runs a hub container the panel shows `ui.containers.hub_empty`.
A hub container's row of **Running now** shows its module's title in the
middle, and has **Journal** alone, with no **Shell**, **Restart**, **Stop**
or **Start** ([agent/modules/containers.md](agent/modules/containers.md),
"Hub containers"). Every row ends at its right edge with one small chip of
where the container comes from, the view's `source`, as the Services page
ends a row with its source: `ui.containers.source_hub` in the accent tone for
a hub container, and `ui.containers.source_declared` or
`ui.containers.source_manual` in the secondary tone for a declared one or one
a person started by hand. No other badge names the owner, and wherever a
container a person started by hand is named to a person, it reads manual.

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

The AI tools of each account are its switch and its model rows in its form
(**Available accounts** above), and the account's row shows its last result
as a `StatusDot` with a word: `switched` `ok`, `switched_back` `idle`, and
`failed` `error` with the code's words.

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
Most interactions somebody reaches for here — a filter row, an inline add, a
masked secret, a confirm-before-delete — already exist above, and a third idiom
for a thing that has one is worse than a plain copy of it.

Only a genuinely novel interaction is a decision, and it is the user's: ask
before building it, not after.
