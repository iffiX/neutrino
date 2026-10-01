# Client behaviour

The client is one person's window onto the hubs they joined: a tray and a
window on Linux, Windows and macOS (`client/desktop`), an app on Android
(`client/android`) and on iOS (`client/ios`). This page fixes the layout of
every page and the behaviour of every button as one design, and the three
implementations follow it line by line. A difference between two clients that
this page does not name is a defect in one of them.

Colours, button tiers and the glow are [visual.md](visual.md); the panel
idioms the client shares with the hub's panel are
[ui_behavior.md](ui_behavior.md); the frames the client exchanges with a hub
are [protocol.md](protocol.md). The strings are keys in each client's catalog,
and the keys named here are the same in all three catalogs.

## One state, pushed

| Rule | Reason |
| --- | --- |
| The resident on a desktop, and the app core on a phone, hold the one state document; the page draws from it and from nothing else. | Two sources of truth drift, and the page then shows a state the core is not in. |
| Every change to the document is pushed whole to the page; the page keeps no timers, no remembered presses and no guessed outcomes. | A guess on the page outlives the fact it was guessed from. |
| A route that starts a job writes the job into the document and pushes it before it returns. | The person sees the in-progress form in the same frame as their press, and there is no gap for a second press. |
| A field a platform cannot act on is still present in the document with the same name. | The three implementations read one shape; the page decides what to draw, the document does not. |

The document has these parts:

| Part | Holds |
| --- | --- |
| `hubs[]` | `id`, `name`, `gateway_url`, `software`, `connection`, `last_error`, `is_exit`, `overlay`, `jobs` |
| `hubs[].overlay` | `network` (the chosen engine), `networks[]` (what the hub publishes), `state`, `address`, `error` |
| `hubs[].jobs` | `is_refreshing`, `overlay_job` (empty, `connecting`, `disconnecting`), `is_leaving` |
| `entries[]` | one per published service: `hub`, `device`, `module`, `kind`, `payload`, `is_healthy`, `unhealthy_code`, `job` |
| `mounts[]` | the desktop's mount records, one per share mounted or being mounted |
| `terminals` | `machines[]` and `sessions[]`, as the hub sends them |
| `settings` | `language`, `theme` |

`entries[].job` and `hubs[].jobs` are the only places a running action is
recorded. A button reads its own job from there and from nowhere else.

## The layout

| Rule | Reason |
| --- | --- |
| The frame is a sidebar on the left when the window is wider than it is tall and at least 720 px wide, and a bottom bar otherwise. | A phone in portrait has no room for a sidebar; a tablet, a laptop and a phone in landscape do. |
| The bar lists the pages in one order: **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals**, **Remote desktops**, **Settings**. | One order on every client is one order to learn. |
| **Join** opens from the Hubs page and is the only page reached from another page; it has a back arrow and no bar entry. | A page reached from several places is lost from each of them. |
| The top bar holds the page title at the left and the refresh button at the right, and nothing else. | The refresh button is the one control that acts on every page. |
| The sidebar's foot shows the machine's name, its platform and the client's version. | A person with two clients open tells them apart there. |
| Every page body scrolls, except Terminals, which gives the terminal the height left under its chips and tabs. | A page squeezed to fit is a page that cannot be read; a terminal is sized to its box by design. |
| A page changes with no transition animation. | A fade adds time to every press and tells nothing. |
| A rotation or a window resize keeps every page's state and every running job; an attached terminal and an open viewer stay as they are. | The state is in the core, and a page is a view of it. |
| A page's content sits in cards with a 16 px gutter; a card is one concern, as in the panel. | The panel's reader is the client's reader. |

A row is the unit every page is made of:

| Position | Holds |
| --- | --- |
| Left | the status dot, coloured by the row's state |
| Body, line 1 | the title: the hub's name, the share's name, the machine's name |
| Body, line 2 | the state word, as the tables on this page give it |
| Body, line 3 | the mono line: an address, a path, `by <hub>:<device>:<module>` |
| Body, line 4 | the error line, when the row's last action or its state has a code; the faint reason line, when a button is disabled |
| Right | the row's actions, in one line; a red-outlined action, when the row has one, is the rightmost |

On a phone the actions wrap under the body, right-aligned, in the same order.
A page with nothing to show has one row with one sentence
(`ui.no_hubs`, `ui.services_wait_join`, `ui.empty_<page>`) and no picture.

## The button rule

| Rule | Reason |
| --- | --- |
| A button that starts a job is that job's indicator until the job ends: a spinner, the in-progress word as its label, and disabled. | The person sees what is happening where they pressed. |
| A duplicate request that reaches the core while the job runs is dropped and logged; it is never returned to the page as a code. The code `busy` does not reach any page. | The person is told nothing about a press the page did not let them make. |
| A button that cannot act in the current state is disabled, and the row's reason line says why in one sentence. | A grey button without a reason is a puzzle. |
| A button neither appears nor disappears with a transient state. The conditional controls are listed on this page by name, and there are no others. | A moving target cannot be pressed. |
| A destructive action arms on the first press (the label changes to `Press again to <verb>`, the fill turns red) and acts on the second press within 5 s; a press elsewhere disarms it. There is no confirmation dialog. | The arming idiom in ui_behavior.md, and a dialog on a phone covers the row it asks about. |
| A failed job writes its code's wording on the row's error line, and the line stays until the next press on that row or a refresh. | The person reads what failed where they pressed. |
| A running job survives a page switch; the page it belongs to shows it again when reopened. | The job runs in the core, and the page is a view of it. |

## Words and colours

The state words, by key. Each client's catalog has every key in both
languages, and the English column is the wording the English catalog holds.

| Key | English |
| --- | --- |
| `ui.state.connected` | Connected |
| `ui.state.connecting` | Connecting… |
| `ui.state.down` | Not connected |
| `ui.state.replaced` | Replaced by another client |
| `ui.state.disabled` | Disabled by the hub |
| `ui.overlay.off` | Not connected |
| `ui.overlay.connecting` | Connecting… |
| `ui.overlay.on` | Connected · `<address>` |
| `ui.job.refreshing` | Refreshing… |
| `ui.job.connecting` | Connecting… |
| `ui.job.disconnecting` | Disconnecting… |
| `ui.job.leaving` | Leaving… |
| `ui.job.joining` | Joining… |
| `ui.job.mounting` | Mounting… |
| `ui.job.unmounting` | Unmounting… |
| `ui.job.forwarding` | Forwarding… |
| `ui.job.switching` | Switching tools… |
| `ui.job.opening` | Opening… |

The dot follows [visual.md](visual.md):

| Dot | Means |
| --- | --- |
| green | `connected`, or the overlay `on`, or a healthy entry |
| amber, pulsing | `connecting`, or any job running on the row |
| amber, still | `down` with a code nobody has to act on (`hub_unreachable`), `disabled`, or an unhealthy entry |
| red | `down` with a code a person has to act on: `hub_untrusted`, `binding_unknown`, `protocol_too_old`, `protocol_too_new` |
| grey | a hub never reached, or the overlay `off` |

## Refresh

The refresh button is one control on every client, and a press is sharp:
the old state goes at once, every place that can show work shows it, and the
new state replaces the work when it arrives. The state machine runs per hub:

| State | Event | Next | What the page shows |
| --- | --- | --- | --- |
| idle | press, for every hub in `connected`, `connecting` or `down` | refreshing | the hub's error line is removed; its state word is `ui.job.refreshing` with a pulsing dot; every entry of that hub shows a pulsing dot and its action buttons are disabled; the overlay line's error is removed; the refresh button shows a spinner |
| refreshing | a state frame arrives from the hub | idle | the new frame, drawn whole |
| refreshing | the connection round ends in a code | idle | `ui.state.down` and the new error line |
| refreshing | 10 s pass | idle | whatever the document holds |
| refreshing | press | refreshing | nothing; the button is disabled while any hub refreshes |

What the core does on the press, before it pushes:

| Hub's connection | Action |
| --- | --- |
| `connected` | sends a report with `is_refresh: true`; the hub sends the whole state frame back whatever its hash; a report the socket cannot take closes the socket, and the hub goes to `connecting` as the Hubs table says |
| `connecting` or `down` | puts the backoff at its floor, ends the current wait, resolves the hub's addresses again and starts a round through them in the material's order |
| `replaced` or `disabled` | nothing, and the hub does not enter refreshing; those states change only by a press on **Reconnect** or by the hub |

The refresh and the automatic reconnection use the same loop. A refresh
starts no second loop; it moves the next round to now.

| Page | While a hub refreshes |
| --- | --- |
| Hubs | the row as the table gives it; the overlay line loses its error line and keeps its state word, since the engine decides the state |
| Web, Ports, AI, Remote desktops | each entry of that hub shows a pulsing dot and disabled actions until the new frame |
| Files | the entries as the row above; the mount records do not change, since a mount is the desktop's own |
| Terminals | the tabs stay; the session list merges from the new frame as the Terminals section says |
| Settings, Join | nothing |

## The Hubs page

The page is one card of hub rows and, under them, the join row. A hub row's
state is its connection:

| State | Event | Next | Notes |
| --- | --- | --- | --- |
| `connecting` | the hub sends `welcome` | `connected` | |
| `connecting` | the round ends in a code | `down` | the code is the error line; the next round runs after the backoff, up to one minute |
| `connecting` | the code is `replaced` | `replaced` | |
| `connected` | the socket closes | `connecting` | automatic, no error line |
| `connected` | the hub rejects with a code | `down` | |
| `connected` | the frame says the client is disabled | `disabled` | |
| `down` | the backoff ends, or a refresh | `connecting` | |
| `replaced` | press **Reconnect** | `connecting` | nothing automatic leaves `replaced` |
| `disabled` | the frame says enabled | `connected` | no button acts on a disabled hub except **Leave** |
| any | the code is `binding_unknown` | row removed, as after **Leave** | the hub no longer holds the client; the code's wording is a notice on the page for one minute |

The row's controls, from left to right:

| Control | Shown | Enabled | Does |
| --- | --- | --- | --- |
| the network picker | when `overlay.networks` has two or more entries | in overlay `off` only | writes the chosen engine to the binding |
| the network button | always | as the overlay table gives it | Connect, Cancel or Disconnect |
| **Reconnect** | in `replaced` only | always | takes the binding back and starts a round |
| **Leave** | always | not while `is_leaving` | arms; the second press deletes the binding, stops that hub's forwards, mounts and viewers, and leaves its network when no other hub uses it; the row shows `ui.job.leaving` and goes when the core has forgotten the binding |

The row of the hub whose gateway the AI tools point at shows `ui.hub_is_exit`
under its mono line; the AI page sets it.

The join row is an input for the link and a **Join** button. On a phone the
row opens the Join page: a camera view that scans the hub's QR, and under it
the same input. The button shows `ui.job.joining` while the link is checked
and the binding written; a success adds the row in `connecting`; a failure
writes the code (`link_unreadable`, `hub_untrusted`) under the input.

### The virtual network line

Under a hub's body sits one line for the hub's virtual network: the state
word with the client's address when on, then the error line. Its controls are
the picker and the button in the row. The state is `off`, `connecting` or
`on`, and `error` holds the last failure while `off`:

| State | Event | Next | The button |
| --- | --- | --- | --- |
| `off` | press **Connect** | `connecting`, `overlay_job` is `connecting` | a spinner and **Cancel** |
| `connecting` | the engine has an address and the hub's channel is up through the network | `on` | **Disconnect** |
| `connecting` | the engine stops, no address within 60 s, or no channel through the network within 60 s | `off`, with error | **Connect** |
| `connecting` | press **Cancel** | `off` | **Connect** |
| `on` | press **Disconnect** | `off` after the engine stops; `overlay_job` is `disconnecting` meanwhile | a spinner and `ui.job.disconnecting`, then **Connect** |
| `on` | the hub's frame no longer lists the network | `off`, with `overlay_withdrawn` | **Connect** |
| `on` | the engine stops by itself | `off`, with the engine's code | **Connect** |
| any | the person leaves the hub | `off` | row gone |

| Rule | Reason |
| --- | --- |
| The client never changes the chosen engine, never retries a failed connect and never moves to another network by itself. | The person chose; a client that changes the choice cannot be reasoned with. |
| A connect is one attempt of at most 60 s, and the person can cancel it at any second of that. | A loop with no exit is what the person sees as a hang. |
| At start, a binding whose last state was `on` gets one connect; a failure leaves it `off` with the error and no retry. | A phone that was on the network before a reboot comes back on it; a hub that is gone does not keep the phone trying. |
| While `on`, the hub's channel connects through the hub's address on that network first. | The network exists so the hub is reachable from outside; the channel is what proves it. |
| The picker is disabled in `connecting` and `on`, and shows the engine's name while disabled. | Changing the engine under a running one is the switch that hangs. |
| The picker is absent when the hub publishes one network; the line then names that engine. | A choice of one is no choice. |

## The Web page

A row per `web` entry: the title, the URL as the mono line, the provider
line. The controls:

| Control | Shown | Enabled | Does |
| --- | --- | --- | --- |
| **Open** | when the entry is not local-only | when the entry is healthy and the hub is not disabled | opens the URL in the system browser; no job |
| **Open locally** | when the entry is local-only, on a desktop | the same | job `ui.job.opening`: forwards the port to the loopback, reads the token on the `service` stream, opens the browser on the loopback URL; a failure writes the code |

A phone shows `ui.desktop_only` as the state word of a local-only entry and
no button.

## The Ports page

A row per `port` entry: the title, `host:port` as the mono line, the
provider line. On a desktop the forward is a state of the row:

| State | Event | Next | Control shown |
| --- | --- | --- | --- |
| not forwarded | press **Connect** | forwarding (job) | the button shows `ui.job.forwarding` |
| forwarding | the listener is up | forwarded | **Disconnect**; the mono line adds `→ 127.0.0.1:<local-port>` |
| forwarding | a code | not forwarded, with the error line | **Connect** |
| forwarded | press **Disconnect** | disconnecting (job), then not forwarded | the button shows `ui.job.disconnecting` |
| forwarded | the entry turns unhealthy | forwarded | **Disconnect** stays enabled; the state word is `ui.unhealthy` |

**Connect** is disabled while the entry is unhealthy or the hub is disabled,
with the reason on the row. A phone shows the address with a **Copy** button
and no forward.

## The AI page

A row per hub's gateway: `ui.module_ai_gateway` as the title, the gateway
address as the mono line. The desktop controls:

| Control | Enabled | Does |
| --- | --- | --- |
| **AI tools use this gateway** (a chip) | when the entry is healthy, the hub is not disabled and no switch runs | job `ui.job.switching`: points Claude Code, Codex and Gemini at this gateway with this client's key; one hub is the exit at a time, and the chip of the other hub turns off in the same push |
| **Configure** | the same | opens the configuration dialog: a picker per tool for its model and, for Codex, its effort; **Save** and **Cancel**; the dialog is the inline-form idiom with a dirty frame |

A phone shows the gateway address and this client's key, each with a
**Copy** button, and a **QR** button that draws both for another app to scan.

## The Files page

A row per `file` entry: the share's name, `//host/share` as the mono line,
the provider line. On a desktop the mount is a record with its own state, and
the row's button is the record's:

| Record state | Event | Next | The button |
| --- | --- | --- | --- |
| none | press **Mount** | `pending` | `ui.job.mounting` |
| `pending` | the core takes it | `queued`, then `mounting` | `ui.job.mounting` |
| `mounting` | the system mounts it | `mounted` | **Unmount** |
| `mounting` | a code | `failed`, with the error line | **Mount** |
| `mounted` | press **Unmount** | `unmounting`, then none | `ui.job.unmounting` |
| `mounted` | the entry turns unhealthy | `mounted` | **Unmount**; the state word is `ui.unhealthy` |
| `failed` | press **Mount** | `pending` | `ui.job.mounting` |

**Configure** opens the row's form in place: a user name (a picker over the
share's `users`, with typed text accepted), the password, and the mount path
with **Browse…**, or a drive letter picker on Windows. The form is a
configurable panel with a dirty frame, **Save** and **Cancel**. **Mount** is
disabled until the form has a user name and a path, with the reason on the
row.

A phone has no mount. Its row shows **Open in Files**, which makes the share
a location in the system's Files app through the client's file provider. The
password is asked once in a sheet and kept in the keystore; **Forget
password** on the row arms and removes it.

## The Terminals page

The page is, from top to bottom: a card with the machine chips, the tab
strip, the terminal, and the status line. The status line holds the hint
`ui.terminal_keys` at the left and the two switches at the right.

| Rule | Reason |
| --- | --- |
| Tabs stay mounted while hidden; switching tabs loses no output. | A terminal redrawn from scratch loses its scrollback. |
| The chips name every machine with a terminal, each with its provider line; the picked chip is the one a new terminal opens on. | The person opens a terminal on a machine, and the machine is the first choice to make. |
| **New terminal** is disabled with no chip picked or with the picked machine offline, with the reason under the chips. | Nothing opens on a machine that cannot answer. |
| A plain session ends when its tab closes; a persistent or shared session's **×** arms and the second press ends the session with `stop_session`. | Ending a session others can see takes two presses, like every destructive action. |

### The session list

The hub sends `terminals.sessions`: every session this client is the owner of,
and every shared session on a machine this client has terminal rights on.
Each has `session_id`, `device_id`, `owner`, `is_owned`, `is_persistent`,
`is_shared`, `attached_count` and `title`. The hub stamps `owner` on the
`shell` open, and `is_owned` is true for the sessions this client opened
(protocol.md).

| Event | What the strip does |
| --- | --- |
| a session is in the list and in no tab | a tab appears at the end; it attaches when first selected |
| a tab's session is gone from the list | the tab's label becomes `ui.terminal_ended`; the terminal keeps its last output; **×** removes the tab |
| the page opens with listed sessions | tabs for all; the first one is active and attaches as the page opens, with its kept output replayed |
| a tab's session reports `attached_count` | the tab shows the count as a badge when above one |

A tab shows these badges after its label: `kept` for a persistent session,
`shared` for a shared one, the count of attached windows when above one.

### The two switches

| Switch | Enabled | Does |
| --- | --- | --- |
| **Persistent** | the tab is open and `is_owned` | sends `persist` with `is_persistent`; the session outlives every window |
| **Shared** | the tab is open and `is_owned` | sends `persist` with `is_shared`; every client with terminal rights on the machine lists the session |

A tab that is not owned shows both switches disabled and the reason line
`Opened by <owner>`. Every window shows the values from the last state frame,
so the owner's flip reaches the other windows with the next frame; in the
owner's window the flip shows the new value at once.

A shared session behaves as one tmux session: every attached window shows
the same output, input from any window reaches the shell, and the shell's
size is the smallest attached window's columns and rows. A window that
attaches receives the kept output first, then the live stream.

### The desktop terminal

| Rule | Reason |
| --- | --- |
| A right click opens a menu at the pointer: **Copy** (enabled with a selection), **Paste**, **Select all**, **Clear**. Escape or a press elsewhere closes it. | A menu is what a right click opens on every desktop. |
| Ctrl+Shift+C copies the selection and Ctrl+Shift+V pastes; on macOS Cmd+C and Cmd+V do the same. On Linux a middle click pastes the selection. | Each system's own terminal habit holds. |
| The copy goes through the resident with `POST /api/clipboard`, and the paste reads `GET /api/clipboard`. | The web view's clipboard permission differs by system; the resident's does not. |
| The wheel and the scrollbar move through the scrollback; the view follows new output only when it is at the bottom; Shift+PageUp and Shift+PageDown page. | Reading history while a build prints is the common case. |
| Ctrl+`+` and Ctrl+`-` change the font size, kept per client. | A person's eyes do not change per machine. |
| The font is MesloLGS NF, loaded through the resident, so powerline prompts draw. | A prompt in boxes is unreadable. |
| A middle click on a tab closes it as **×** does; a double click on the strip's empty space opens a new terminal on the picked machine. | The two gestures every tabbed window has. |

### The phone terminal

| Rule | Reason |
| --- | --- |
| A key row sits above the keyboard: Esc, Tab, Ctrl, the four arrows; Ctrl is sticky for one key. | The system keyboard has none of them. |
| With the keyboard shown, the chips card and the tab strip collapse into one line (the machine, the tab, an expand arrow), and the terminal takes the rest and refits its rows. | The terminal is the page's reason; the chrome is not. |
| The terminal's viewport scrolls by touch and shows a thin bar; the view follows output only at the bottom. | History on a phone is reached by the finger, and a bar says there is some. |
| A long press opens the same menu as the desktop's right click, with **Copy** and **Paste** through the system clipboard. | The phone's clipboard is the system's. |

## The Remote desktops page

A row per shared desktop: the machine's name, the provider line, the state
word. The controls:

| Control | Enabled | Does |
| --- | --- | --- |
| **Connect** | when the entry is healthy, the hub is not disabled and no viewer runs on it | job `ui.job.connecting`: on a desktop starts the viewer with the seat password; on a phone opens the viewer page |
| the viewer | | on a desktop a separate window, and the row then shows `ui.rdp_open`; on a phone a page of the app with a back arrow |

A row whose entry is unhealthy shows the code's wording on the reason line:
`rdp_nobody_seated`, `rdp_screen_not_allowed`.

The viewer shares the clipboard both ways: text copied on the remote machine
is on this device's clipboard, and a paste in the viewer sends this device's
clipboard. On a phone the viewer page keeps its session through a rotation.

## The Settings page

One card: a **Language** picker, a **Theme** picker (System, Dark, Light),
**Save** enabled while the draft differs from the saved values, **Cancel**
beside it. Under the card, a section titled **About** lists the version, the
licence, the source links and, on a phone, the cores built into the app with
their patches, as plain rows. There is no About page and no card inside the
section. Leaving a hub is on the Hubs page and nowhere else.

## Phone differences

| Feature | Desktop | Phone |
| --- | --- | --- |
| join | paste the link | scan the QR, or paste the link |
| port entry | forward to the loopback | copy the address |
| local-only web entry | open through a forward | `ui.desktop_only` |
| file entry | mount into the system | a location in the system's Files app |
| AI entry | point the tools at the gateway, configure them | copy the address and the key, show a QR |
| remote desktop | the viewer process | the viewer page |
| terminal input | right-click menu, shortcuts, middle click | the key row, long press |
| frame | sidebar, tray | bottom bar in portrait; a sidebar in landscape when at least 720 px wide |

Everything else is the same: the pages and their order, the words, the state
machines, the badges, the dots and the reasons on disabled buttons.

## An interaction this page does not cover

A control, a state or a gesture that none of the tables above name is not
invented in one client. It is written here first, for all three, and built
after it is written.
