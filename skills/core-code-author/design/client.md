# Client behaviour

The client is one person's window onto the hubs they joined: a tray and a
window on Linux, Windows and macOS (`client/desktop`), an app on Android
(`client/android`) and on iOS (`client/ios`, paused since 2026-10-03,
[release.md](../agent_work_rule/release.md)). This page fixes the layout of
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
| `hubs[]` | `hub_id`, `hub_name`, `gateway_url`, `software`, `connection`, `reached_through` (the hub's word for the way the channel reached it: `lan`, `direct`, `netbird`, `easytier`, `relay`, or empty before the first state), `is_panel_allowed` (the hub's state says whether this client's permission holds `panel`), `panel_forward` (empty, or the loopback port the panel's forward listens on), `last_error`, `is_exit`, `overlay`, `jobs` |
| `hubs[].overlay` | `network` (the chosen engine), `networks[]` (what the hub publishes), `state`, `stage` (empty, `login` or `hub` while connecting), `address`, `error` |
| `hubs[].jobs` | `is_refreshing`, `overlay_job` (empty, `connecting`, `disconnecting`), `is_leaving`, `is_opening_panel` |
| `services[]` | one per published service, with the hub's wire fields (`hub_id`, `device_id`, `module`, `kind`, `payload`, `is_healthy`, `unhealthy_code`), plus `job`, `last_error` and, for every entry the client forwards ("The local port table"), `local_port` (the setting: `auto` or a number) and `forward` (empty, or the loopback port the forward listens on) |
| `mounts[]` | the desktop's mount records, one per share mounted or being mounted |
| `terminals` | `machines[]` and `sessions[]`, as the hub sends them |
| `notices[]` | page-wide notices with a code, such as `binding_unknown`, each with a close button; a notice goes when closed, when **Refresh** is pressed, or after one minute |
| `language`, `theme`, `terminal_font_size` | the client's own settings, at the top level |

`services[].job` and `hubs[].jobs` are the only places a running action is
recorded. A button reads its own job from there and from nowhere else.

## The layout

| Rule | Reason |
| --- | --- |
| The frame is a sidebar on the left when the window is wider than it is tall, or at least 720 dp wide, and a bottom bar otherwise. | A phone in portrait has no room for a sidebar; a tablet, a laptop and a phone in landscape do, whatever the phone's display size setting makes of its width. |
| The bar lists the pages in one order: **Hubs**, **Web**, **Ports**, **AI**, **Files**, **Terminals**, **Remote desktops**, **Settings**. | One order on every client is one order to learn. |
| **Join** opens from the Hubs page and is the only page reached from another page; it has a back arrow and no bar entry. | A page reached from several places is lost from each of them. |
| The top bar holds the page title at the left and the refresh button at the right, and nothing else. | The refresh button is the one control that acts on every page. |
| The sidebar and the bottom bar carry only the pages; the machine's name, platform and version are on the Settings page's About card and nowhere else. | A foot that repeats on every page is noise; About is where a person looks for a version. |
| In the sidebar layout a page's own action (**New terminal** on Terminals, **Scan** on Join, which asks for the camera or scans again after a refused code) sits at the right of the page header, as the panel's `page_actions` does; the floating button at the bottom right exists only in the bottom-bar layout. | A floating button beside a sidebar covers content and reads as a leftover. |
| In the sidebar layout the page body starts to the right of the sidebar and never under it. | Content under the sidebar is unreadable and untouchable. |
| Every page body scrolls, Terminals included: on a phone the chips and the tab bar are always drawn in full, the terminal's box is as tall as the window under the top bar less the key row, so one screen holds the terminal and its keys and the chips scroll away above it; nothing collapses behind a tap, neither in landscape nor with the keyboard shown. On a desktop the terminal takes the height left under its chips and tabs. | A page squeezed to fit is a page that cannot be read; a line that must be tapped to see the page is a trap. |
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
| Body, line 4 | the error line, when the row's last action or its state has a code, removed the moment a new action starts; the faint reason line, when a button is disabled |
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
| An entry is unhealthy only when its `is_healthy` is `false`. An entry with empty health carries no health word and its actions stay enabled, on every page. | Empty health is a record no probe has reached, and a `generic_udp` record is never probed; read as unhealthy, its row could never be used. |

## Words and colours

The state words, by key. Each client's catalog has every key in both
languages, and the English column is the wording the English catalog holds.

| Key | English |
| --- | --- |
| `ui.state.connected` | Connected |
| `ui.state.connected_through` | Connected · `<way>` |
| `ui.through.lan` | LAN |
| `ui.through.direct` | Direct |
| `ui.through.netbird` | NetBird |
| `ui.through.easytier` | EasyTier |
| `ui.through.relay` | Relay |
| `ui.state.connecting` | Connecting… |
| `ui.state.down` | Not connected |
| `ui.state.pending` | Joined; the hub has not been reached yet |
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
| `ui.job.clearing` | Clearing… |

The Chinese catalog's words for the ways in are 局域网, 直连, NetBird,
EasyTier and 中继, the relay's word being the one [ui_text.md](ui_text.md) fixes.

The dot follows [visual.md](visual.md):

| Dot | Means |
| --- | --- |
| green | `connected`, or the overlay `on`, or an entry that is not unhealthy |
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
| `connecting` | the hub sends `welcome` | `connected` | the state word is `ui.state.connected_through` with the word for the state's `reached_through`, `ui.state.connected` until the first state names it |
| `connecting` | the round ends in a code | `down` | the code is the error line; the next round runs after the backoff, up to one minute |
| `connecting` | the code is `replaced` | `replaced` | |
| `connected` | the socket closes | `connecting` | automatic, no error line |
| `connected` | the hub rejects with a code | `down` | |
| `connected` | the frame says the client is disabled | `disabled` | |
| `down` | the backoff ends, or a refresh | `connecting` | |
| `replaced` | press **Reconnect** | `connecting` | nothing automatic leaves `replaced` |
| `disabled` | the frame says enabled | `connected` | no button acts on a disabled hub except **Leave** |
| any | the code is `binding_unknown` | row removed, as after **Leave** | the hub no longer holds the client; the code's wording is a notice on the page with a close button, gone when closed, on **Refresh**, or after one minute |

The row's controls, from left to right:

| Control | Shown | Enabled | Does |
| --- | --- | --- | --- |
| the network picker | when `overlay.networks` has two or more entries | in overlay `off` only | writes the chosen engine to the binding |
| the network button | always | as the overlay table gives it | Connect, Cancel or Disconnect |
| **Panel** | when `is_panel_allowed` | when the hub is `connected` and not disabled | job `ui.job.opening`: asks `service {is_panel: true}` for a sign-in token, makes the panel's forward when the hub has none, then opens the system browser at `http://panel-<hub-id>.localhost:<local-port>/?tkn=<token>` (on macOS `http://127.0.0.1:<local-port>/?tkn=<token>`); a failure, `permission_denied` among them, writes the code on the row's error line |
| **Reconnect** | in `replaced` only | always | takes the binding back and starts a round |
| **Leave** | always | not while `is_leaving` | arms; the second press deletes the binding at once, whether or not the hub answers: the core stops that hub's forwards (the panel's among them), mounts and viewers, leaves its network when no other hub uses it, forgets the binding, and only then tells the hub once, in the background, with a short timeout, a refusal or an unreachable hub changing nothing; the row shows `ui.job.leaving` and goes when the core has forgotten the binding, which never waits on the hub |

The panel's forward is a forward of the local port table whose far end is
`connect {is_panel: true}`; it listens from the first press of **Panel**
until the hub is left or the client quits. The panel answers through it
over plain HTTP, the channel being its encryption, and signs the browser
in with the token, so no panel password is asked; a token that no longer
spends lands on the ordinary login page. `<hub-id>` is the hub's id, so
each hub's panel keeps its own session cookie in the browser.

The row of the hub whose gateway the AI tools point at shows `ui.hub_is_exit`
under its mono line; the AI page sets it.

The join row is an input for the link and a **Join** button. On a phone the
row opens the Join page: a camera view that scans the hub's QR, and under it
the same input. The QR carries the whole link ([protocol.md](protocol.md),
"The link and the two endpoints"), the same compressed form a person
pastes, so a scan and a paste are one path: the app inflates it, stores the
binding at once with every address and the overlays' material, and the
channel's rounds do the rest. The button shows `ui.job.joining` while the
link is checked and the binding written; a success adds the row in
`pending`; a failure writes the code (`link_unreadable`, `hub_untrusted`)
under the input. A hub none of the link's addresses reaches yet keeps the
row pending.

### Joining before the hub is reached

| Rule | Reason |
| --- | --- |
| A join (a scanned QR or a pasted link) stores the binding at once, with the link's ticket kept and no token yet, and the Hubs page shows the hub's row in the same frame: the state word is `ui.state.pending` ("Joined; the hub has not been reached yet"), the mono line is the link's first address, and the virtual network line is live from the link's `overlays`, with its picker and **Connect**. | Nothing a person pastes or scans is refused for the hub being out of reach at that moment: a phone on 4G adds the hub now and reaches it later. The link carries the network's material at once. |
| The channel's rounds run as for any hub. The first time an address answers with the pinned certificate, the client spends the ticket there (`POST /api/channel/join`), keeps the token, and only then sends `hello`; from then on the binding is ordinary. | The join and the first channel share one reachable address, whichever path gave it. |
| A ticket the hub refuses (`ticket_spent`, or any refusal of the join) puts the row in `down` with that code, **Leave** as its only action, and no further rounds; the person scans again. | A dead ticket cannot be revived; a loop on it is a hang with a name. |
| `admission_paused {retry_after_s}` is the one transient refusal of the join: the client keeps the ticket, leaves the row `pending` with the code on its error line, and joins again after `retry_after_s` seconds. | The hub paused new enrolments after too many failures; the ticket behind the pause is still valid. |
| A ticket lives 30 minutes, which the Clients page says beside the QR. | A phone that has to raise a network first needs more than five minutes. |

### The virtual network line

Under a hub's body sits one line for the hub's virtual network: the state
word with the client's address when on, then the error line. Its controls are
the picker and the button in the row. The state is `off`, `connecting` or
`on`, and `error` holds the last failure while `off`:

| State | Event | Next | The button |
| --- | --- | --- | --- |
| `off` | press **Connect** | `connecting`, `overlay_job` is `connecting` | a spinner and **Cancel** |
| `connecting`, stage `login` | the engine reports an address | `connecting`, stage `hub`; `address` is set | a spinner and **Cancel** |
| `connecting`, stage `hub` | the hub's port answers at the hub's address on that network and the hub's channel is up through that address | `on` | **Disconnect** |
| `connecting`, stage `login` | the engine stops, or no address within 90 s | `off`, with error (`overlay_no_address`) | **Connect** |
| `connecting`, stage `hub` | the engine stops | `off`, with the engine's code | **Connect** |
| `connecting` | press **Cancel** | `off` | **Connect** |
| `on` | press **Disconnect** | `off` after the engine stops; `overlay_job` is `disconnecting` meanwhile | a spinner and `ui.job.disconnecting`, then **Connect** |
| `on` | the hub's frame no longer lists the network | `off`, with `overlay_withdrawn` | **Connect** |
| `on` | the engine stops by itself | `off`, with the engine's code | **Connect** |
| any | the person leaves the hub | `off` | row gone |

| Rule | Reason |
| --- | --- |
| The client never changes the chosen engine, never retries a failed connect and never moves to another network by itself. | The person chose; a client that changes the choice cannot be reasoned with. |
| A connect is one attempt in two stages: `login` (the engine starts, logs in and gets an address) within 90 s, then `hub` (the hub answers through the network), which has no limit: the probe runs every 2 s until the hub answers, the engine stops or the person cancels, and the reason line under the state word names the stage (`ui.stage.login`; `ui.stage.hub` with the address and the seconds waited so far). | A mobile network needs most of a minute for the login alone, and how long the tunnel to the hub takes is the engine's business; a clock that gives up while the engine is still working sends the person back to the button. |
| The `hub` stage probes the hub's own address on that network, which the hub's material carries as `address` (its NetBird or EasyTier address), never the hub's name on the network. | The desktop runs NetBird without its DNS, so the name resolves nowhere; the address is what the tunnel carries. |
| In the `hub` stage the channel reconnects through that address and keeps trying it until the stage ends; it does not move to another address meanwhile. | A channel that wanders back to the LAN address proves nothing about the network. |
| Each stage's start and end is one log line with its duration. | A connect that fails on a phone is explained from the log or not at all. |
| In EasyTier's console mode the `login` stage's 90 s cover the registration with the console; after it the state stays `connecting` with the reason line `ui.reason.console_waiting` (registered with the console, waiting for it to assign a network) until the owner assigns one or the person cancels. | The console's owner decides when a new machine gets a network; the client cannot hurry that, and failing after a minute would read as a fault. |
| At start, a binding whose last state was `on` gets one connect; a failure leaves it `off` with the error and no retry. | A phone that was on the network before a reboot comes back on it; a hub that is gone does not keep the phone trying. |
| While `on`, the hub's channel connects through the hub's address on that network first. | The network exists so the hub is reachable from outside; the channel is what proves it. |
| The picker is disabled in `connecting` and `on`, and shows the engine's name while disabled. | Changing the engine under a running one is the switch that hangs. |
| The picker is absent when the hub publishes one network; the line then names that engine. | A choice of one is no choice. |

## The Web page

A row per `web` entry: the title, the URL as the mono line, the provider
line. Every entry opens through a forward of the local port table. The
controls:

| Control | Shown | Enabled | Does |
| --- | --- | --- | --- |
| **Open** | always | when the entry is not unhealthy and the hub is not disabled | job `ui.job.opening`: makes the entry's forward when it has none, reads `{token}` on the `service` stream when the entry has `is_token_required`, and opens the system browser on the entry's forwarded URL below; a failure writes the code |
| **Configure** | always | when the entry is not forwarded | the local port dialog ("The local port table") |
| **Disconnect** | when the entry is forwarded | always | ends the forward, as on the Ports page |

A forwarded row is a Ports row: the mono line adds `→ 127.0.0.1:<local
port>`. The browser is opened on
`<scheme>://<slug>.localhost:<local-port><path>`, with `?tkn=<token>` added
for an entry with `is_token_required`. `<scheme>` and `<path>` are the
entry's url's own, and `<slug>` is the entry's id with every character
outside letters, digits and hyphens turned into a hyphen. A browser
resolves a `.localhost` name to the loopback by itself, and a cookie
belongs to its host, so each instance keeps its own cookie and two
instances never overwrite each other's; the distinct local port keeps their
storage apart as well. On macOS the host is `127.0.0.1`, since Safari
resolves no `.localhost` name; every forward there shares that host, and a
browser keeps one cookie per name for it, so two instances whose cookies
have the same name sign each other out. A phone does the same through its app core:
the forward listens on the phone's loopback, and the browser opens there.

VS Code reads its token from a cookie in the page to authenticate its own
connection, so the token must reach the browser in the URL. The forwarders
in front of code-server and CloudCLI trade a token for a login of their own
([agent.md](agent.md), "CloudCLI" and "code-server"). Their token is spent
once and dies after 60 seconds, so every press of **Open** reads a new one.

## The Ports page

A row per `port` entry: the title, `host:port` as the mono line, where the
service is on the hub's networks, and the provider line. A UDP entry's mono
line reads `host:port/udp`; a TCP entry's has no suffix. On a desktop the
forward is a state of the row:

| State | Event | Next | Control shown |
| --- | --- | --- | --- |
| not forwarded | press **Connect** | forwarding (job) | the button shows `ui.job.forwarding` |
| forwarding | the listener is up, and for a UDP entry its stream is open | forwarded | **Disconnect**; the mono line adds `→ 127.0.0.1:<local-port>`, with `/udp` after it for a UDP entry |
| forwarding | a code | not forwarded, with the error line | **Connect** |
| forwarded | press **Disconnect** | disconnecting (job), then not forwarded | the button shows `ui.job.disconnecting` |
| forwarded | the entry turns unhealthy | forwarded | **Disconnect** stays enabled; the state word is `ui.unhealthy` |

**Connect** is disabled while the entry is unhealthy or the hub is disabled,
with the reason on the row. A phone has the same states; its forward lives in
the app's foreground service, and the forwarded row adds **Copy** for the
loopback address, `127.0.0.1:<local-port>` without the `/udp` suffix, since
the phone has no shell to type it into.

A UDP entry's forward is one UDP socket bound to `127.0.0.1:<local port>`
from **Connect** until **Disconnect**, and one `connect` stream:

| Rule | Reason |
| --- | --- |
| The forward opens its stream at **Connect**, and again at the first datagram that finds it has none, after the hub's socket was replaced or the far end closed the stream. | A UDP program has no connection to start a stream with, and a stream that ended is opened again by the next datagram that needs it. |
| An open refused at **Connect** ends the forward and writes the code on the row's error line, as a failed bind does. An open refused later writes the code on the error line; the forward goes on listening and tries again at a later datagram, at most once a second. | A refusal at the press is the answer to the press; a refusal later is a state the hub can leave without the person pressing again. |
| Datagrams that arrive while an open waits for its first credit are held, at most `CLIENT_UDP_HELD_DATAGRAMS_MAX`, 16, and sent when the credit comes; more are dropped. No datagram waits anywhere else. | A program's first datagram is often its only one, and a bounded hold keeps it without a queue. |
| Each datagram goes into the stream with the port it came from as `source`. The forward remembers, per `source`, the address it last came from, for at most `CLIENT_UDP_SOURCES_MAX`, 64, sources, the one idle the longest giving way; a frame for a `source` it no longer remembers is dropped. | A reply returns to the local program that asked, and two programs on one forward stay two peers. |

## The local port table

A forward is a listener on `127.0.0.1:<local-port>` that opens one
`connect` stream to the hub for every connection it accepts and relays the
bytes both ways, or, for a UDP `port` entry, one UDP socket with one stream
for every datagram it carries ([protocol.md](protocol.md), "The connect
stream"). No page
of any client dials a service's own address; the hub's agent port is the
one address a client dials.

| Entry | The forward listens |
| --- | --- |
| `port` | from **Connect** until **Disconnect** |
| `web` | from **Open** until **Disconnect** |
| `ai`, on a desktop | while the client runs and the hub is the exit of any tool |
| `ai`, on a phone | from **Connect** until **Disconnect**, as a `port` entry |
| `rdp` | from **Connect** until the viewer ends |
| `file`, on Linux and macOS | from **Mount** until the share is unmounted |
| the hub's panel | from the first press of **Panel** until the hub is left or the client quits |

A `file` entry on Windows goes through the files adapter instead ("The
files adapter on Windows"), and on a phone the in-app SMB client's sockets
are `connect` streams themselves; neither holds a local port. A client that
quits ends every forward.

The local port is the client's to manage:

| Rule | Reason |
| --- | --- |
| A `port` or `web` entry has a **Configure** button at the left of its action, a small button like the row's others; it opens a dialog with one choice, **Local port**: **Auto** (the default) or **Fixed** with a number from 1024 to 65535, and **Save** and **Cancel**. The button is disabled while the entry is forwarded, with the reason `ui.reason.disconnect_first`. Every other forward is **Auto**. | The port a tool is told to use must not change under it; changing it under a running forward is the change nobody asked for. |
| **Auto** picks the entry's own port when no other entry holds it and it is free, else the first free port from 20000 up; the client records the pick for the entry and gives it the same port on every later forward and after a restart. The panel has no port of its own and starts at 20000. | Two instances on the same remote port must land on two local ports, and the local port of each must stay put. |
| A port is free only when nothing listens on it on any address of the machine: a probe binds it on the IPv4 wildcard address, and on the IPv6 one where the machine has IPv6, with no address-reuse option, and closes it; a TCP entry's probe binds TCP sockets and a UDP entry's binds UDP sockets. On Windows a UDP number is not bound at all: it is looked up in the system's own table of UDP endpoints (`GetExtendedUdpTable`, IPv4 and IPv6), and is free only when no endpoint on any address holds it. The forward itself listens on `127.0.0.1` alone. | A loopback listener beside a server on every address takes that server's local traffic, and on macOS a loopback bind succeeds beside it. A UDP socket bound to a wildcard address makes the Windows firewall ask the person whether to let the client reach their networks. |
| A kept pick or a **Fixed** number is probed again each time its forward is about to listen, with the address-reuse option off Windows so the client's own closed connections still on the port do not count. A kept **Auto** pick another program now listens on is picked again by the rule above and the new pick is kept; a **Fixed** number another program listens on is not listened on, and the row's error line says `port_taken` with the number. | A machine changes between two forwards; a port free when it was picked can have a server on it now, and the rule holds only if it is asked at every bind. |
| The client keeps one table of local ports: every entry's pick or fixed number is in it with its protocol, no two entries of one protocol hold one number, and a **Fixed** number another entry of the same protocol holds is refused in the dialog with `ui.reason.port_taken`, the `port_taken` of a bind likewise. A TCP entry and a UDP entry can hold one number, so **Auto** gives 53/tcp and 53/udp the same local number when both are free. The stored table reads an entry with no protocol as TCP. | One table is the only way two forwards never collide, and a TCP port and a UDP port of one number are two ports. |
| A forwarded row always shows `→ 127.0.0.1:<local port>`, on the Web, Ports and AI pages. | A port the person cannot see is a port they cannot type. |

## The AI page

A row per hub's gateway: `ui.module_ai_gateway` as the title, the gateway
address as the mono line, and `→ 127.0.0.1:<local port>` after it while
the forward listens. The desktop controls:

| Control | Enabled | Does |
| --- | --- | --- |
| **AI tools use this gateway** (a chip) | when the entry is not unhealthy, the hub is not disabled and no switch runs | job `ui.job.switching`: makes the entry's forward, reads this client's key on the `service` stream, and points Claude Code, Codex and Gemini at `http://127.0.0.1:<local-port>` with that key ([modules/ai.md](modules/ai.md)); one hub is the exit at a time, and only a chip the person turned on makes it so: with no chip turned on no hub is the exit; the chip of the other hub turns off in the same push, and its forward ends |
| **Configure** | the same | opens the configuration dialog: a picker per tool for its model and, for Codex, its effort; **Save** and **Cancel**; the dialog is the inline-form idiom with a dirty frame |

Under the controls is the line `ui.ai_needs_client`: the tools reach the
gateway only while this client runs.

A desktop client on a machine the Neutrino agent is installed on leaves the
machine's AI tools to the agent ([modules/ai.md](modules/ai.md), "How a
managed machine's tools are pointed at the gateway"). The agent is
installed when its program directory exists: `/opt/neutrino/agent` on
Linux, `/Library/Application Support/Neutrino/agent/app` on macOS,
`C:\Program Files\Neutrino\agent` on Windows ([files.md](files.md)). The
resident checks at its start and each time it takes a state from a hub.

| Rule | Reason |
| --- | --- |
| With the agent installed, the chip and **Configure** are disabled, with the reason `ui.reason.ai_managed` under the controls; the row, its address and its forward line still show. | The agent and the client would both write the provider `neutrino` into the same account's cc-switch store, with different endpoints. |
| A client whose chip is on when it first sees the agent turns the chip off and runs its deactivation once, as a press of the chip would; the chip stays off and disabled from then on. | The person's tools go back to what they had, and the agent's setting is the one that points them at the hub afterwards. |
| `nclient service ai apply` exits with `ai_tools_managed`, the code worded as the reason is; `nclient service ai show` still answers. | The command line is the same switch as the chip. |
| The Android app has no gate. | No agent runs on a phone. |

A phone forwards the gateway as a Ports row: **Connect** and
**Disconnect**, and the forwarded row shows the loopback address with
**Copy**, for an app on the same phone. Under it, this client's key on one
row: the key in a mono field with the eye toggle inside the field at its
right end (the panel's password field), then **Copy**; on a narrow screen
the field shrinks and the button keeps its size.

## The Files page

A row per `file` entry: the share's name, `//host/share` as the mono line,
where the share is on the hub's networks, and the provider line. On a
desktop the mount is a record with its own state, and the row's button is
the record's:

| Record state | Event | Next | The button |
| --- | --- | --- | --- |
| none | press **Mount** | `pending` | `ui.job.mounting` |
| `pending` | the core takes it | `queued`, then `mounting` | `ui.job.mounting` |
| `mounting` | the system mounts it | `mounted` | **Unmount** |
| `mounting` | a code | `failed`, with the error line; the form keeps its values | **Mount** |
| `mounted` | press **Unmount** | `unmounting`, then `detached`: the record and its login stay | `ui.job.unmounting` |
| `detached` | press **Mount** | `pending`, mounting with the kept login, nothing retyped | `ui.job.mounting` |
| `mounted` | the entry turns unhealthy | `mounted` | **Unmount**; the state word is `ui.unhealthy` |
| `failed` | press **Mount** | `pending` | `ui.job.mounting` |
| `failed` with a login refusal | press **Save** in the form with a new login | `pending`, mounting with the new login at once | `ui.job.mounting` |
| `failed` or `detached` | its entry leaves the hub's list, or another record is set to mount at the same place | none | a failed or detached record is dropped with its login and holds no place |

**Configure** opens the row's form in place: a user name (a picker over the
share's `users`, with typed text accepted), the password, and the place the
share is mounted, which takes the system's own shape
(`mount_location_shape` in the state document):

| System | Shape | The form's control | The mounted row |
| --- | --- | --- | --- |
| Linux | `path`: a directory under the home | the path with **Browse…**; the default is `~/nas/<share>` | the path |
| Windows | `drive_letter`: a drive | a picker over the free letters, with the caption that the share appears as that drive in File Explorer | the letter |
| macOS | `volume`: a network volume the system mounts under `/Volumes` | no control; a caption that the volume appears in the Finder under the server (`ui.mount_volume_caption`, with the server's address) | the mount point the system gave, `/Volumes/<share>` or the next free name, and `ui.mount_finder` under it with the server's address |

The form is a configurable panel with a dirty frame, **Save** and **Cancel**.
**Mount** is disabled until the form has a user name and, where the shape
asks for one, a place, with the reason on the row.

Every system mounts the share from the hub's channel, never from the
share's own address:

| System | The mount |
| --- | --- |
| Linux | the entry's forward, mounted by the root helper under `pkexec`: `mount_helper mount --share //127.0.0.1/<share> --port <local-port> --location <path> --credentials <file>`, which runs `mount.cifs` with `port=<local-port>` among its options |
| macOS | the entry's forward, mounted by the system as below |
| Windows | the files adapter's address for the share's machine, `net use <letter>: \\<fake-address>\<share>` ("The files adapter on Windows"); a share of the client's own machine (`is_own_machine`) is mounted from `\\127.0.0.1\<share>` directly, through no adapter |

On macOS the client does not mount the share itself: it asks the system to
mount the volume through `osascript`, with the one-line script on its
standard input and never on an argument:

```text
mount volume "smb://<user>@127.0.0.1:<local-port>/<share>" as user name "<user>" with password "<password>"
```

The volume is the one the Finder's **Connect to Server** would make, listed
under the server in the Finder's sidebar. The record's `path` is empty until
the system has mounted the volume, is then read back from the mount table
(`//<user>@127.0.0.1:<local-port>/<share> on /Volumes/<name> (smbfs, …)`),
and is empty again after an unmount; **Unmount** ejects that mount point
with `diskutil unmount`, which needs no administrator. A volume the system
already has mounted for the same address, port and share is taken as
mounted, not mounted twice.

The system's own dialogs belong to the system, and the client waits for
them rather than answering or killing them: the first connection to a server
asks the person to confirm the server once; a wrong password opens the
system's login dialog; a share that does not exist or a server that cannot
be reached shows the system's alert and the script returns only once the
person has dismissed it. So the script's timeout is ten minutes
(`MOUNT_SCRIPT_TIMEOUT_S`), the row shows `ui.job.mounting` throughout, and
a script the client had to kill is followed by nothing else until the
person mounts again. The script's errors map to the refusals: `-5014` and
`-43` are `share_not_found`; `-128`, the person cancelling the system's
dialog, is `mount_not_authorized`; `-5023` and `-5000` are the login
refusals; `-36` and "Connection failed" are `share_unreachable`; anything
else is `mount_failed` with the script's words, the password masked; a script that ran out its ten minutes is
`mount_timed_out`, a `failed` the timer never retries by itself. On a
Mac the empty form's reason is `ui.reason.mount_form_volume`, which asks for
a user name only.

A phone has no mount. Its row shows **Open in Files**, which makes the share
a location in the system's Files app through the client's file provider. The
password is asked once in a sheet and kept in the keystore; **Forget
password** on the row arms and removes it. The app's SMB client reaches the
share through its socket factory, which hands it sockets whose bytes are
`connect` streams naming the file entry.

## The files adapter on Windows

The Windows SMB client dials port 445 alone, and the system holds the
machine's own 445, so a forward on a loopback port cannot carry a share.
The Windows client gives every machine that provides a share an address of
its own on a virtual adapter, and sends the adapter's SMB connections to
the hub.

| Part | What it is |
| --- | --- |
| The adapter | `neutrino_files`, a wintun adapter at `198.19.255.1/24`, with no gateway and no DNS server, connected to no network <!-- scan: allow --> |
| The fake addresses | one per machine other than the client's own that provides a `file` entry, from `198.19.255.2` to `198.19.255.253`, kept per hub and machine in the client's store, so a drive letter keeps naming the same machine; the machine is the entry's `device_id`, or its host for a declared record <!-- scan: allow --> |
| tun2socks | the MIT-licensed executable the client's package includes, credited on the About card, run with the adapter as its device and the SOCKS endpoint as its proxy; it hands every TCP connection entering the adapter to that endpoint |
| The SOCKS endpoint | a SOCKS5 listener of the resident on `127.0.0.1`, behind a user name and password the resident generates at each start; it accepts a connection to `<fake-address>:445` of a machine it knows and opens a `connect` stream naming a `file` entry of that machine, and refuses any other address or port |

The adapter and tun2socks need administrator rights, and the resident has
none. The privileged part is a service the `.msi` installs beside the
EasyTier daemon, in the same way: `NeutrinoClientFiles`, which runs
`nclient.exe files-daemon --service` as LocalSystem and answers one JSON
request per connection on the pipe `\\.\pipe\neutrino_client_files`, with
the EasyTier pipe's security descriptor. The resident asks it `up` with the
endpoint's port, user name and password before its first Windows mount; the
daemon makes the adapter, gives it its address and runs tun2socks as its
child, and answers only once a connection of its own through the adapter is
answered, because the adapter drops what enters it in its first seconds. A
mount made before that moment times out inside Windows' SMB client. The
resident asks it `down` when it quits and at no other time: Windows' SMB
client keeps its connection to a fake address past an unmount, and an
adapter taken away and made again under that connection fails every mount
that follows. The daemon then stops tun2socks and removes the adapter. A
`status` answers whether the adapter is up.

The adapter serves one account at a time, since a drive letter of one
person must never reach another person's endpoint:

| Rule | Reason |
| --- | --- |
| The daemon reads who asks from the pipe itself: the account by impersonating the caller, and the calling process by its process id. | A request names nothing the daemon trusts; the pipe's peer is what the system vouches for. |
| While a resident of one account holds the adapter, an `up` or a `down` from another account is refused `files_adapter_in_use`; the holder's adapter, endpoint and mounts are untouched. | Serving the second person would send the first person's drive letters to the second person's endpoint. |
| A resident of the same account that asks later is served in the first one's place. | A restarted resident is the same person with a new endpoint. |
| The daemon keeps a handle on the holding process and looks at it every second; when it has ended, by a quit, a crash or the end of its session, the daemon stops tun2socks, removes the adapter and is free for any account. | A crashed resident never asks `down`, and a handle the daemon holds keeps the process id from naming another process meanwhile. |

A mount the refusal stops goes `failed` with `files_adapter_in_use` on the
row's error line, which says the files adapter is in use by another account
on this machine, and is tried again on the remount timer, so it mounts once
the other account's client has quit.

A share of the client's own machine never goes through the adapter.
Windows refuses a login that leaves the machine and comes back to it
(`0xC000006D`), and a mount at a fake address of the machine itself would
read on the row as a wrong password. An entry with `is_own_machine` is
mounted at `\\127.0.0.1\<share>`, the machine's own SMB server on its own
445, takes no fake address and brings the adapter up for nothing; its row
reads as any mounted row. On Linux and macOS such a share takes its forward
like any other: neither system's SMB client is the Windows one that the
server recognises as its own.

When the adapter cannot be made, because the service is missing, stopped or
refuses, the mount record goes `failed` with `files_adapter_unavailable
{detail}` on the row's error line, and nothing else changes on the system.

## The Terminals page

The page is, from top to bottom: a card with the machine chips, the tab
strip, the terminal, and the status line. The status line holds the two
switches at the right and nothing else.

| Rule | Reason |
| --- | --- |
| Tabs stay mounted while hidden; switching tabs loses no output. | A terminal redrawn from scratch loses its scrollback. |
| The chips name every machine with a terminal, each with its provider line; the picked chip is the one a new terminal opens on. | The person opens a terminal on a machine, and the machine is the first choice to make. |
| **New terminal** is disabled with no chip picked or with the picked machine offline, with the reason under the chips. | Nothing opens on a machine that cannot answer. |
| Keys reach the machine in the order they were pressed: a tab has one sender that writes its bytes in sequence, on every client. | A letter that overtakes the one before it types another word. |
| **Clear**, wherever a client offers it, sends Ctrl+C, clears the screen, drops what had arrived and was not yet drawn, and goes on dropping what arrives until the stream has been quiet for half a second, for twenty seconds at most. While it drops, the terminal's own box shows `ui.job.clearing` ("Clearing…", 「清屏中…」) where the output would be, and the word goes when the dropping ends. The desktop and the phone behave the same. | A clear that is followed by the rest of the flood clears nothing, and how long the flood's tail takes to cross the hub is not a number a client can know. |
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
| a tab's stream is closed `session_not_owned`, as when the owner stops sharing the session | the tab keeps its output and writes the code's words below it, as for every stream the hub closes with a code; the next state frame no longer lists the session, and the tab's label becomes `ui.terminal_ended` |
| the hub's channel drops and comes back | a tab whose session is in the new list attaches again by itself and replays the kept output; a tab whose session is gone reads `ui.terminal_ended`; nothing stays on "not connected" after the hub is back |

A tab shows these badges after its label: `kept` for a persistent session,
`shared` for a shared one, the count of attached windows when above one.
The active tab is marked the way the panel marks a selected chip: the
accent as its border and text, the elevated surface as its fill; the other
tabs have the plain border. A tab without that mark is a defect.

### The two switches

| Switch | Enabled | Does |
| --- | --- | --- |
| **Persistent** | the tab is open and `is_owned` | sends `persist` with `is_persistent`; the session outlives every window |
| **Shared** | the tab is open and `is_owned` | sends `persist` with `is_shared`; every client with terminal rights on the machine lists the session |

A tab that is not owned shows both switches disabled, drawn with no accent:
the track's border and the thumb in the faint text colour, the thumb's
position still telling the value, the label in the muted text colour; and
the reason line `Opened by <owner>`, where the name is the row's `owner_name` (the hub's
name, or the owning client's name) and the raw `owner` stamp when that is
empty. Every window shows the values from the last state frame,
so the owner's flip reaches the other windows with the next frame; in the
owner's window the flip shows the new value at once.

A shared session behaves as one tmux session: every attached window shows
the same output, input from any window reaches the shell, and the shell's
size is the smallest attached window's columns and rows. A window that
attaches receives the kept output first, then the live stream.

### The desktop terminal

| Rule | Reason |
| --- | --- |
| A right click opens a menu at the pointer: **Copy** (enabled with a selection), **Paste**, **Select all**, **Clear**. **Clear** is the page's rule: Ctrl+C, the screen cleared, and the output dropped under `ui.job.clearing` until the stream is quiet. Escape or a press elsewhere closes the menu. | A menu is what a right click opens on every desktop; a clear that leaves the flood running clears nothing. |
| Ctrl+Shift+C copies the selection and Ctrl+Shift+V pastes; on macOS Cmd+C and Cmd+V do the same. On Linux a middle click pastes the selection. | Each system's own terminal habit holds. |
| The copy goes through the resident with `POST /api/clipboard`, and the paste reads `GET /api/clipboard`. | The web view's clipboard permission differs by system; the resident's does not. |
| The wheel and the scrollbar move through the scrollback; the view follows new output only when it is at the bottom; Shift+PageUp and Shift+PageDown page. | Reading history while a build prints is the common case. |
| Ctrl+`+` and Ctrl+`-` change the font size, kept per client. | A person's eyes do not change per machine. |
| The font is MesloLGS NF, loaded through the resident, so powerline prompts draw. | A prompt in boxes is unreadable. |
| A middle click on a tab closes it as **×** does; a double click on the strip's empty space opens a new terminal on the picked machine. | The two gestures every tabbed window has. |

### The phone terminal

| Rule | Reason |
| --- | --- |
| A key row sits above the keyboard: Esc, Tab, Ctrl, Shift, Alt, the four arrows; a modifier is sticky for one key and shows pressed while held. | The system keyboard has none of them. |
| With the keyboard shown, the terminal's box shrinks to the space left above the key row, which stays above the keyboard, and the terminal refits its rows; the prompt line stays in view and nothing collapses. The top bar is drawn in every orientation. A phone in landscape with the keyboard up has room for the key row and little else, which is accepted: a tablet is the device for a landscape terminal. | A key row under the keyboard cannot be pressed, and a prompt below the fold cannot be read. |
| The font falls back to a face that has the box-drawing, geometric and powerline symbols for every glyph the monospace face lacks. | A prompt in boxes is unreadable. |
| The terminal's viewport scrolls by touch and shows a thin bar; the view follows output only at the bottom. | History on a phone is reached by the finger, and a bar says there is some. |
| A long press opens the same menu as the desktop's right click, with **Copy** and **Paste** through the system clipboard. | The phone's clipboard is the system's. |

## The Remote desktops page

A row per shared desktop: the machine's name, the provider line, the state
word. The controls:

| Control | Enabled | Does |
| --- | --- | --- |
| **Connect** | when the entry is not unhealthy, the hub is not disabled and no viewer runs on it | job `ui.job.connecting`: reads `{password}` on the `service` stream and makes the entry's forward; on a desktop starts the viewer at `127.0.0.1:<local-port>` with the seat password on its command line, the one channel RustDesk 1.4.9 has for a connect password (its peer file takes only a hash salted by the host), and follows the viewer process, on Windows the copy the bundled viewer starts of itself from its own data directory; on a phone opens the viewer page, whose core dials the same forward. The forward ends with the viewer |
| the viewer | | on a desktop a separate window, and the row then shows `ui.rdp_open`; on a phone a page of the app whose three round buttons open the keyboard, the key bar of Esc, Tab, Ctrl, Shift, Alt, Win, **Paste** and the arrows, and close the session |
| **Configure** | on a phone, when the entry is not unhealthy | the dialog of the inline-form idiom with two pickers: **Codec** (Auto, then each codec the core offers) and **Quality** (Balanced, Low bandwidth, Best); **Save** and **Cancel**; the choice is kept per entry in the app's settings and applied at the next connect |

The row's mono line is the entry's host and port, where the desktop is on
the hub's networks; the viewer dials the forward on the loopback and never
that address. The row's state word is the entry's health, and `ui.rdp_open` while the
viewer runs.

The phone's viewer page is built for the picture first:

| Rule | Reason |
| --- | --- |
| The page is immersive: the system's bars are hidden and come back on an edge swipe, and the picture fills the screen. | A phone's screen is small; every bar on it is taken from the desktop. |
| No title bar. Three translucent round buttons sit at the top right and stay: **Keyboard** raises the phone's keyboard and takes typing, and shows the keyboard's own state, so a keyboard the system floats over the picture counts as shown and the next press closes it; **Keys** shows the key bar; **Close** ends the session. Both the keyboard and the key bar start off, so the page opens on the picture alone. | A title the person already knows and bars that hide on a timer take the picture away and make the way back hard to find; three buttons that never move are found by feel. |
| The keyboard never shrinks the picture: the picture keeps its size and the keyboard covers its lower part, the key bar sits right above the keyboard, and the two-finger drag and pinch reach what the keyboard covers. | A picture squeezed to a strip above the keyboard cannot be worked on. |
| Typing goes through an input connection of the page's own, not through a text field that is diffed: the text the keyboard commits is sent as text, the text it is still composing is sent nowhere, a delete is sent as Backspace, Enter as Enter, and a single key with a modifier held is sent as that key. The connection keeps the focus while the keyboard is up. No ASCII-only keyboard type, no autocorrect, no suggestions. | The person's own keyboard, in its own language, is the input; a Chinese keyboard composes before it commits, and a field diffed on every change sends the composition and loses the focus when the page redraws. |
| Committed text with any character outside ASCII goes to a Linux host (`platform_os` `linux` on the entry) as a paste: the text is put on the remote clipboard and Shift+Insert is pressed once. ASCII-only text, and every text to a Windows or Mac host, is typed as before. | RustDesk types a character X11 has no key for by remapping a spare key, pressing it and mapping it back, and the programs read the map late, so a run of Chinese comes out doubled or with characters missing whatever the pace; a paste lands whole, and Shift+Insert pastes in terminals, browsers, GTK and Qt programs alike where Ctrl+V does not. |

A row whose entry is unhealthy shows the code's wording on the reason line:
`rdp_nobody_seated`, `rdp_screen_not_allowed`. A row whose entry's
`platform_os` is `darwin` shows a standing hint under the provider line,
`ui.rdp_mac_hint`: a black picture or a mouse that does nothing means that
Mac has not granted RustDesk screen recording and accessibility; the agent
cannot read those grants, so the client says it every time.

The viewer shares the clipboard both ways: text copied on the remote machine
is on this device's clipboard, and a paste in the viewer sends this device's
clipboard. On a desktop the viewer's **Transfer file** window copies files
both ways, which the agent's host allows; the viewer window itself takes no
drop. On a phone the viewer page keeps its session through a rotation.

## The Settings page

Two cards, in the panel's order. The first is **About**, the panel's About
card: a card header with the title, then two groups, each under a section
label (the panel's `section_label`: small, uppercase, muted): **This
machine** (the machine's name and its platform) and **Carried**, drawn as
the panel's credits rows: the first row is the client itself (`Neutrino
client <version>` at the left, `<licence> — Source` at the right), then one
row per core the client carries (`<name> <version>` at the left, `<licence>
— Source` at the right, with ` · Patch` after it where the client carries a
patch), where **Source** and **Patch** are short link words that open the
repository or the patch in the browser; no URL is ever written out. The
client's own **Source** and its patches open the repository of the client's
edition: GitHub for `intl`, Gitee for `cn`; the desktop window reads the
edition from the `edition` field of its state document. In `cn`, a carried
core's **Source** opens a Gitee repository that holds the same tag at the
same commit where one exists: EasyTier's own `gitee.com/easytier/EasyTier`
and Gitee's `gitee.com/mirrors/rustdesk`; the other cores keep their
upstream link. A row
is the label at the left in the muted colour and the value in mono at the
right, rows parted by the panel's faint rule. The second card holds a
**Language** picker, a **Theme** picker (System, Dark, Light), **Save**
enabled while the draft differs from the saved values, and **Cancel** beside
it. There is no About page. Leaving a hub is on the Hubs page and nowhere
else.

## Phone differences

| Feature | Desktop | Phone |
| --- | --- | --- |
| join | paste the link | scan the QR, or paste the link; either adds the hub at once |
| port entry | forward to the loopback | the same: a foreground service listens on `127.0.0.1:<local port>` and relays each connection as a `connect` stream, as the desktop does, and the forwarded row shows the loopback address with **Copy** |
| web entry | open through a forward, with the token for an entry with `is_token_required` | the same: the app forwards, reads the token and opens the system browser on the loopback URL |
| file entry | mount the forward, or the files adapter's address on Windows | a location in the system's Files app, its sockets `connect` streams |
| AI entry | point the tools at the forward, configure them | forward it as a port entry, copy the loopback address and the key |
| remote desktop | the viewer process, at the forward | the viewer page, at the forward |
| hub's panel | **Panel** on the hub row | the same |
| terminal input | right-click menu, shortcuts, middle click | the key row, long press |
| frame | sidebar, tray | bottom bar in portrait; a sidebar in landscape, and in portrait on a tablet at least 720 dp wide |
| virtual networks | one per hub, several hubs at once | one at a time: **Connect** on a second hub is disabled with the reason `overlay_other_network` while another hub's network is not off |

Everything else is the same: the pages and their order, the words, the state
machines, the badges, the dots and the reasons on disabled buttons.

A phone keeps its connections when the person switches apps:

| Rule | Reason |
| --- | --- |
| While any hub is bound, the app core runs in one foreground service with one notification line; the hub channels, the share connections and the forwards live in it, and nothing closes when the app leaves the screen. | A process the system freezes answers no ping, and the hub closes the channel within a minute; a service is what the system keeps running. |
| Returning to the foreground reconnects a dropped channel at once, with no backoff. | The person is looking; a wait they can see is a fault. |
| A share's root stays listed in the system's Files app for 60 s after its hub's channel drops, marked as reconnecting. | A root that vanishes mid-copy fails the copy. |
| There is no setting for this. | A connection that holds is the product, not an option. |

## An interaction this page does not cover

A control, a state or a gesture that none of the tables above name is not
invented in one client. It is written here first, for all three, and built
after it is written.
