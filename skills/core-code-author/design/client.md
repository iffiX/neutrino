# Client behaviour

The client is one person's window onto the hubs they joined: a tray and a
window on Linux, Windows and macOS (`client/desktop`), an app on Android
(`client/android`) and on iOS (`client/ios`, with the differences "The iOS
app" names). This page fixes the layout of every page and the behaviour of
every button as one design, and the three implementations follow it line by
line. A difference between two clients that this page does not name is a
defect in one of them.

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
| A client judges no permission. The hub's state already holds only the entries, apps, machines and overlays the client's permission allows, and `is_panel_allowed`; a `permission_denied {kind}` on a stream or a `service` ask is the hub's answer at that moment ([protocol.md](protocol.md), `/api/hub/client`). | One function in the hub judges every use, so a permission changed on the Clients page reaches the client in its next state, the same on the three clients. |

The document has these parts:

| Part | Holds |
| --- | --- |
| `hubs[]` | `hub_id`, `hub_name`, `gateway_url`, `software`, `connection`, `reached_through` (the hub's word for the way the channel reached it: `lan`, `netbird`, `easytier`, `ssh_relay`, `direct`, `sakurafrp`, `openfrp`, or empty before the first state), `rtt_ms` (the last round trip the client measured, from its own `ping` frame to the hub's `pong` with the same `nonce`, in milliseconds; null before the first pong and while the hub is not `connected`), `is_panel_allowed` (the hub's state says whether this client's permission holds `panel`), `panel_forward` (empty, or the loopback port the panel's forward listens on), `last_error`, `is_exit`, `overlay`, `jobs` |
| `hubs[].overlay` | `network` (the chosen engine), `networks[]` (what the hub publishes), `state` (`off` or `on`), `stage` (empty, or `login` while a connect runs), `address`, `error` |
| `hubs[].jobs` | `is_refreshing`, `overlay_job` (empty, `connecting`, `disconnecting`), `is_leaving`, `is_opening_panel` |
| `apps[]` | one per app the hub publishes to this client, with the hub's wire fields (`hub_id`, `id`, `title`, `source`, `device_id`, `device_name`, `local_name`), plus `job`, `last_error` and `is_in_use` (its forwards listen) |
| `services[]` | one per published service, with the hub's wire fields (`hub_id`, `id`, `app_id`, `name`, `device_id`, `module`, `kind`, `payload`, `is_healthy`, `unhealthy_code`), plus `job`, `last_error` and, for every entry the client forwards ("The local port table"), `local_port` (the setting: the hub's number, a number of the person's, or `auto` for an entry of no app) and `forward` (empty, or the loopback port the forward listens on) |
| `mounts[]` | the desktop's mount records, one per share mounted or being mounted |
| `terminals` | `machines[]`, each with its enabled `accounts`, and `sessions[]`, as the hub sends them |
| `language`, `theme`, `terminal_font_size`, `is_ssh_include_enabled` | the client's own settings, at the top level; the last on a desktop alone ("SSH for other programs") |

`apps[].job`, `services[].job` and `hubs[].jobs` are the only places a
running action is recorded. A button reads its own job from there and from nowhere else.

## One client per machine

A desktop runs one person's client at a time, as RustDesk does. The
EasyTier daemon, which every desktop install runs as root or SYSTEM and
which keeps the machine's one virtual network, keeps which account's
client holds the machine, as the files daemon keeps which account holds
the adapter ("The files adapter on Windows"). The rule and its mechanism
are the same on Linux, Windows and macOS.

| Rule | Reason |
| --- | --- |
| The resident asks the daemon `hold` once its own control socket is bound, and again every 10 s. The daemon reads the account and the process from its socket or pipe. | A request names nothing the daemon trusts. Asking again keeps the hold after the daemon restarts. |
| While a resident of one account holds the machine, a `hold` from another account is refused `client_held` with the holder's account; a resident of the same account is served in the first one's place. | The virtual network, the files adapter and the loopback ports belong to the machine, and two people's clients would take them from each other. |
| The daemon keeps a handle on the holding process and frees the machine once it has ended, by a quit, a crash or the end of its session. | A crashed resident never says it is done, and the handle keeps the process id from naming another process meanwhile. |
| `nclient gui` refused a hold exits with no window, no tray icon and no message. Every other `nclient` command of another account prints the one line `client_held`, naming the holder's account, and exits 1. | A second window that can do nothing is noise; a terminal is where a person asks why. |
| Where no daemon answers, as in a checkout, the resident starts and holds nothing. | A checkout runs no daemon, and a client that cannot start is worse than two. |
| An installer, which runs elevated as whichever administrator started it, asks the one running client to quit for an upgrade, whoever's account it belongs to; the client registers its return as its own account and comes back in its own session ("A client upgraded while it runs comes back"). | An upgrade replaces the files of the one client that runs, whoever installs it. |

## A client upgraded while it runs comes back

An install over a running client closes it to replace its files, and the
client is running again when the install ends, in the same person's session,
as that person, never as SYSTEM or elevated, with no second prompt. An
install over no running client starts nothing.

On Windows the installer asks the one running client to quit for an
upgrade, whichever account it belongs to ("One client per machine"). It asks
the EasyTier daemon which client holds the machine and opens that account's
control pipe, which admits the administrators besides its own account. The
installer runs elevated, and the client takes that one request and no other
from an elevated caller; a caller that is neither its own account nor
elevated is refused. The client registers, as its own account, the task
`NeutrinoClientRelaunch_<account>`: no trigger, the limited run level, run
only while the account is signed in, starting `nclientw.exe gui --hidden`.
The installer's last step, as SYSTEM, starts every such task, and the client
deletes its own task when it starts. An account that is not signed in, as
under an install from ssh or a management tool with nobody at the desktop,
does not run its task, and the install does not fail. A removal deletes
every such task.

## The layout

| Rule | Reason |
| --- | --- |
| The frame is a sidebar on the left when the window is wider than it is tall, or at least 720 dp wide, and a bottom bar otherwise. | A phone in portrait has no room for a sidebar; a tablet, a laptop and a phone in landscape do, whatever the phone's display size setting makes of its width. |
| The bar lists the pages in one order: **Hubs**, **Apps**, **AI**, **Files**, **Terminals**, **Remote desktops**, **Settings**. A phone has no **AI** page, and lists the others in the same order. | One order on every client is one order to learn, and an app looks the same on a phone as on a computer. |
| On a phone's bottom bar each page is its icon with its label under it, the open page's in the accent. The bar labels **Remote desktops** as **Desktops** (`ui.bar_desktops`), and the top bar shows the full title. | An icon alone has to be learnt, and six pages leave room for a short word under each. |
| With the keyboard shown, a phone's bottom bar stays under the keyboard, and the page ends at the keyboard's top. | A bar above the keyboard takes room from the page, and no page is switched while typing. |
| **Join** opens from the Hubs page and is the only page reached from another page; it has a back arrow and no bar entry. | A page reached from several places is lost from each of them. |
| The top bar holds the page title at the left and the refresh button at the right, and nothing else. | The refresh button is the one control that acts on every page. |
| The sidebar layout has four parts: at the top left the client's name (`ui.window.title`: Neutrino client, 微子·客户端) in a box as tall as the page header beside it, at the top right the page header with the title and the refresh button, at the bottom left the page list, each page by its full name and Settings apart under a rule, at the bottom right the page. The bottom bar carries only the pages. The machine's name, platform and version are on the Settings page's About card and nowhere else. | The name's box and the header share one top line, as the desktop window draws them; a foot that repeats on every page is noise, and About is where a person looks for a version. |
| In the sidebar layout a page's own action (**Scan** on Join, which asks for the camera or scans again after a refused code) sits at the right of the page header, in the header's own row, as the panel's `page_actions` does. In the bottom-bar layout it sits in the page: **Scan** in the camera's card. **New terminal** is an exception: on every client and in both layouts it sits in the machines card, after the machine chips. A floating button exists only in the bottom-bar layout, except the share page's **+**, which is there in both layouts. | A floating button beside a sidebar covers content and reads as a leftover, and over a terminal it covers the status line's switches; the share page keeps one form of its actions in every layout. New terminal opens on the chip picked beside it. |
| In the sidebar layout the page body starts to the right of the sidebar and never under it. | Content under the sidebar is unreadable and untouchable. |
| Every page body scrolls, Terminals included: on a phone the chips and the tab bar are always drawn in full, the terminal's box is as tall as the window under the top bar less the key row, so one screen holds the terminal and its keys and the chips scroll away above it; nothing collapses behind a tap, neither in landscape nor with the keyboard shown. On a desktop the terminal takes the height left under its chips and tabs. | A page squeezed to fit is a page that cannot be read; a line that must be tapped to see the page is a trap. |
| A page changes with no transition animation. | A fade adds time to every press and tells nothing. |
| In the desktop window a dialog covers the whole window above every other layer. The page under it is blurred and inert, a dialog opened from a dialog lies above its parent, and Escape closes an open list, else the top dialog. | A dialog interrupts the person until they choose, as in the panel ([ui_behavior.md](ui_behavior.md), "Modals, and where a record's detail lives"). |
| A rotation or a window resize keeps every page's state and every running job; an attached terminal and an open viewer stay as they are. | The state is in the core, and a page is a view of it. |
| A page's content sits in cards with a 16 px gutter; a card is one concern, as in the panel. | The panel's reader is the client's reader. |
| In the desktop window every form field, a select or a text input, spans the full width of its row, and every form's button row (**Save** and **Cancel**, **Choose this folder**) sits at the bottom right of its panel or dialog, in one style on every page. | One form idiom is one thing to learn, and a field narrower than its row or a button row at the left reads as unfinished. |

A row is the unit every page is made of:

| Position | Holds |
| --- | --- |
| Left | the status dot, coloured by the row's state |
| Body, line 1 | the title: the hub's name, the share's name, the machine's name |
| Body, line 2 | the state line: the state word as the tables on this page give it, then ` · ` and the action when the state waits for one (a countdown, or a button's name) |
| Body, line 3 | the mono line: an address, a path, `by <hub>:<device>:<module>` |
| Body, line 4 | the error line, when the row's last action has a code, removed the moment a new action starts; the faint reason line, when a button is disabled. A hub row's connection never writes this line: its codes are state words on line 2 |
| Right | the row's actions, in one line; a red-outlined action, when the row has one, is the rightmost |

On a phone the actions sit under the body on every row of every page,
right-aligned and in the same order, also where they would fit beside it,
and wrap to a second line where one line is too narrow.
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
| `ui.through.netbird` | NetBird |
| `ui.through.easytier` | EasyTier |
| `ui.through.ssh_relay` | SSH relay |
| `ui.through.direct` | Direct |
| `ui.through.sakurafrp` | SakuraFrp |
| `ui.through.openfrp` | OpenFrp |
| `ui.state.rtt` | `<ms>` ms |
| `ui.state.connecting` | Connecting… |
| `ui.state.hub_silent` | The hub did not answer |
| `ui.state.hub_off_overlay` | The hub is not on the virtual network |
| `ui.state.no_network` | No network |
| `ui.state.untrusted` | Hub key mismatch |
| `ui.state.admission_paused` | The hub pauses new devices |
| `ui.state.unknown_device` | The hub does not know this device |
| `ui.state.too_old` | Version too old |
| `ui.action.update_client` | update the client |
| `ui.state.join_refused` | Join refused |
| `ui.action.retry_in` | retrying in `<s>` s |
| `ui.state.replaced` | Replaced by another client |
| `ui.state.disabled` | Disabled by the hub |
| `ui.overlay.off` | Not connected |
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

The Chinese catalog's words for the ways in are 局域网, NetBird, EasyTier,
SSH 中继, 直连, SakuraFrp and OpenFrp, the relay's word being the one
[ui_text.md](ui_text.md) fixes. Each word is the title of an **Access** card,
局域网 aside, so the row and the panel name a way in alike.

The dot follows [visual.md](visual.md):

| Dot | Means |
| --- | --- |
| green | `connected`, or the overlay `on`, or an entry that is not unhealthy |
| amber, pulsing | `connecting`, or any job running on the row |
| amber, still | waiting on `hub_silent`, `hub_off_overlay`, `no_network` or `admission_paused`, `disabled`, or an unhealthy entry |
| red | waiting on `untrusted`, `unknown_device`, `too_old` or `join_refused` |
| grey | a hub never reached, or the overlay `off` |

## Refresh

The refresh button is one control on every client, and a press is sharp:
the old state goes at once, every place that can show work shows it, and the
new state replaces the work when it arrives. The state machine runs per hub:

| State | Event | Next | What the page shows |
| --- | --- | --- | --- |
| idle | press, for every hub in `connected`, `connecting` or waiting | refreshing | the hub's state line is `ui.job.refreshing` with a pulsing dot; every entry of that hub shows a pulsing dot and its action buttons are disabled; the overlay line's error is removed; the refresh button shows a spinner |
| refreshing | a state frame arrives from the hub | idle | the new frame, drawn whole |
| refreshing | the connection round ends in a code | idle | the waiting state line the Hubs table gives for that code, with its countdown |
| refreshing | 10 s pass | idle | whatever the document holds |
| refreshing | press | refreshing | nothing; the button is disabled while any hub refreshes |

What the core does on the press, before it pushes:

| Hub's connection | Action |
| --- | --- |
| `connected` | sends a report with `is_refresh: true`; the hub sends the whole state frame back whatever its hash; a report the session cannot take ends the session, and the hub goes to `connecting` as the Hubs table says |
| `connecting` or waiting | puts the backoff at its floor, ends the current wait and the round in flight, resolves the hub's addresses again and starts a round, which dials them all at once ("The Hubs page") |
| `replaced` or `disabled` | nothing, and the hub does not enter refreshing; those states change only by a press on **Reconnect** or by the hub |

The refresh and the automatic reconnection use the same loop. A refresh
starts no second loop; it moves the next round to now.

| Page | While a hub refreshes |
| --- | --- |
| Hubs | the row as the table gives it; the overlay line loses its error line and keeps its state word, since the engine decides the state |
| Apps, AI, Remote desktops | each app and entry of that hub shows a pulsing dot and disabled actions until the new frame |
| Files | the entries as the row above; the mount records do not change, since a mount is the desktop's own |
| Terminals | the tabs stay; the session list merges from the new frame as the Terminals section says |
| Settings, Join | nothing |

## The Hubs page

The page is one card of hub rows and, under them, the join row. A hub row's
state is its connection, and its state line says it in one of three kinds:
the client is dialling, the client is connected, or the client stopped and
waits for something. A waiting state's word is its reason, and the action
after the ` · ` is what ends the wait:

| State line (English catalog) | Chinese | When | What ends it |
| --- | --- | --- | --- |
| `ui.state.connecting`, Connecting… | 连接中… | a round is dialling | the round ends |
| `ui.state.connected_through` · `ui.state.rtt`, Connected · LAN · 1 ms | 已连接 · 局域网 · 1 ms | the round won; the two tags follow each `ping` | the session ends: `connecting` at once, no wait |
| `ui.state.hub_silent` · `ui.action.retry_in`, The hub did not answer · retrying in 5 s | 中枢未响应 · 5 秒后重试 | every address of the round failed, and the hub's virtual network is off or the hub has none | the countdown reaches 0, or a network change, or a refresh |
| `ui.state.hub_off_overlay` · `ui.action.retry_in`, The hub is not on the virtual network · retrying in 5 s | 中枢未上虚拟网 · 5 秒后重试 | every address of the round failed while this client's virtual network of the hub's is `on` | the same |
| `ui.state.no_network`, No network | 无网络 | the device has no network at all | the device's connectivity changing |
| `ui.state.untrusted` · `ui.action.retry_in`, Hub key mismatch · retrying in 60 s | 中枢密钥不符 · 60 秒后重试 | `hub_untrusted` | the countdown, at `RedialBackoffMax` each time |
| `ui.state.admission_paused` · `ui.action.retry_in`, The hub pauses new devices · retrying in 60 s | 中枢暂停接纳 · 60 秒后重试 | `admission_paused {retry_after_s}` on the join | the countdown of `retry_after_s` |
| `ui.state.unknown_device`, The hub does not know this device | 中枢不认识本机 | `binding_unknown` | nothing; **Leave** is the row's only action |
| `ui.state.too_old` · `ui.action.update_client`, Version too old · update the client | 版本太旧 · 更新客户端 | `protocol_too_old` | nothing automatic: the person installs the new client, which keeps this state and its bindings, and the next round connects |
| `ui.state.too_old`, Version too old | 版本太旧 | `protocol_too_new` | nothing automatic; a refresh after an upgrade |
| `ui.state.join_refused` · `<the code's wording>`, Join refused · `<reason>` | 加入被拒 · 原因 | the hub refused the ticket (`ticket_spent`, any refusal of the join), or the binding is of the 0.5 shape, with no hub key (`hub_key_missing`), and the client dials nothing for it ([transport.md](transport.md), "A peer of 0.5") | nothing; **Leave** |
| `ui.state.replaced` · **Reconnect**, Replaced by another client · Reconnect | 已被替换 · 重新连接 | `replaced` | the press on **Reconnect** |
| `ui.state.disabled`, Disabled by the hub | 已停用 | the frame says the client is disabled | the frame says enabled |

A countdown is live: the state carries the moment of the next round, and
the page redraws the seconds left once a second; at 0 the line reads
`ui.state.connecting`. The wait between rounds is the backoff,
`RedialBackoffMin` doubling to `RedialBackoffMax`, put back at the
floor by a round that wins and by every network change. A row just joined
runs its rounds like any other and reads the same lines; nothing says
"pending".

A connect round, a reconnect after the session ended as much as the
first, dials every candidate address of the hub at once: the hub's address
on each of its virtual networks that is up, the hub's name, and the
binding's `urls`. The client's transport runs the round, from the candidates
the client gives it with `dial` ([transport.md](transport.md), "The local
channel"). Each address keeps its own connect time, `DialTimeout`. The
first connection whose handshake completes under the binding's `hub_key` is
the round's. At that moment the transport closes every other connection of
the round, before any `hello` on it, and sends `hello` on the round's
connection alone. The round ends `connected` when the `welcome`
follows, and in a code otherwise ([transport.md](transport.md), "Where
the port is reached").

| Rule | Reason |
| --- | --- |
| No address is preferred for having worked last. A connected hub moves to another address only when a round a network change started wins on a better path ("A network change starts a round"). | The path that completes first is the fastest one at that moment, whatever it was at the last round. |
| No prober runs between rounds, no round runs on a timer, and the client keeps no list of reachable addresses. | Every round already tries every address; a second mechanism that guesses reachability goes stale between rounds. |
| One `hello` per round. | The hub keeps one admitted session per binding and ends the earlier of two with `refused {code: replaced}`, so a second `hello` in one round ends the round's own winner. |
| An address refused in a round, a host that is up with the port not open yet, is dialled again every `RedialInterval`, 1 s, until `DialTimeout`, 10 s, has passed since the round started. An address that does not answer at all is not dialled again in that round. The desktop and the phone do the same. | A hub that restarts opens its port again within a second or two; without the redial the client waits out the round and the backoff before it dials again. |

### A network change starts a round

A network change starts one round at once for every hub whose row is not
`replaced` or `disabled`. Four events are network changes: a virtual network
of the hub's turning `on`, the device's own connectivity changing (an
interface coming up or going down, a phone moving from a mobile network to
Wi-Fi), a state frame whose `urls` differ from the binding's, and the
engine's peer list changing on a virtual network that is `on` (a peer
appearing or going). For a hub that is not `connected`, the change ends
the wait and the round in flight, if any, and the new round starts at once:
a dial still waiting out its connect time is closed, not waited for. For a
`connected` hub, the round runs beside the live channel, and the round trip
measure follows on whichever session carries the channel afterwards.

The client knows each candidate's path before its `hello`: the hub's address
on a virtual network is that engine's, the state's `ssh_relay_url`,
`sakurafrp_url` and `openfrp_url` are `ssh_relay`, `sakurafrp` and
`openfrp`, an address inside a network the device holds an address in is
`lan`, and any other is `direct`. The paths rank in one order, best first:

| Rank | Path |
| --- | --- |
| 1 | `lan` |
| 2 | `direct` |
| 3 | `netbird`, `easytier` |
| 4 | `ssh_relay`, `sakurafrp`, `openfrp` |

| Rule | Reason |
| --- | --- |
| A round on a `connected` hub takes the channel only when its winner's path ranks higher than the live channel's, or ranks the same and its handshake took less time than the live channel's took when it won. | A change of network is the moment a better path can appear, and moving the channel costs every stream on it. |
| A winner that is no better is closed before its `hello`, and the live channel stays where it is. | One admitted session per binding: a `hello` on the loser ends the channel that is working. |
| A better winner sends `hello`. The hub ends the old session with `refused {code: replaced}`, which the client expects on the session it moved off and never shows as the row's `replaced`. | The client replaced its own channel; the row's `replaced` is for another client taking the binding. |
| The row shows the new channel's `reached_through` and `rtt_ms` as after any round. | The row reads the channel, whichever round made it. |

A `connected` row shows two tags beside its dot, each one short token: the
state word `ui.state.connected_through` with the word for `reached_through`,
and `ui.state.rtt` with `rtt_ms` rounded to a whole number. The client sends
a `ping` frame of its own every `CLIENT_PING_INTERVAL_S`, 20 seconds, and once
right after the channel moves to a new session, and each `pong` whose `nonce`
is the last `ping` sent on that session sets `rtt_ms` to the time from that
ping to its pong, so the tag changes at every ping. The client sends no
WebSocket ping. No sentence goes with either tag.

The row's controls, from left to right:

| Control | Shown | Enabled | Does |
| --- | --- | --- | --- |
| the network picker | when `overlay.networks` has two or more entries | in overlay `off` only | writes the chosen engine to the binding |
| the network button | always | as the overlay table gives it | Connect, Cancel or Disconnect |
| **Panel** | when `is_panel_allowed` | when the hub is `connected` and not disabled | job `ui.job.opening`: asks `service {is_panel: true}` for a sign-in token, makes the panel's forward when the hub has none, then opens the system browser at `http://panel-<hub-id>.localhost:<local-port>/?tkn=<token>` (on macOS `http://127.0.0.1:<local-port>/?tkn=<token>`); a failure, `permission_denied` among them, writes the code on the row's error line |
| **Reconnect** | in `replaced` only | always | takes the binding back and starts a round |
| **Leave** | always | not while `is_leaving` | arms; the second press deletes the binding at once, whether or not the hub answers: the core stops that hub's forwards (the panel's among them), mounts and viewers, leaves its network when no other hub uses it, forgets the binding, and only then tells the hub once, in the background, trying the hub's addresses in turn with an equal share each of `CLIENT_LEAVE_TELL_TIMEOUT_S`, 5 seconds, a refusal or an unreachable hub changing nothing; the row shows `ui.job.leaving` and goes when the core has forgotten the binding, which never waits on the hub |

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
the same input. The QR carries the whole link ([transport.md](transport.md),
"The links"), the same compressed form a person
pastes, so a scan and a paste are one path: the app inflates it, stores the
binding at once with every address and the overlays' material, and the
channel's rounds do the rest. The button shows `ui.job.joining` while the
link is checked and the binding written; a success adds the row, which
reads `ui.state.connecting` as its first round starts; a failure writes the
code (`link_unreadable`, `hub_untrusted`) under the input. A hub none of the
link's addresses reaches yet leaves the row on the waiting line the Hubs
table gives, with its ticket unspent.

### Joining before the hub is reached

| Rule | Reason |
| --- | --- |
| A join (a scanned QR or a pasted link) stores the binding at once, with the link's ticket kept and no token yet, and the Hubs page shows the hub's row in the same frame: the state line reads `ui.state.connecting` as its first round starts, the mono line is the link's first address, and the virtual network line is live from the link's `overlays`, with its picker and **Connect**. | Nothing a person pastes or scans is refused for the hub being out of reach at that moment: a phone on 4G adds the hub now and reaches it later. The link carries the network's material at once. |
| The channel's rounds run as for any hub, each knock a join's while the binding holds no token. The first time a handshake completes under the link's key, the client spends the ticket there with the `join` frame, keeps the token, and only then knocks again as a bound peer and sends `hello`; from then on the binding is ordinary. | The join and the first channel share one reachable address, whichever path gave it. |
| A client holds at most one binding per hub id, and a join to a hub ends the binding held before for that hub as at a leave: its row goes, and what it held (forwards, mounts, viewers, its virtual network) stops. Right after the ticket is spent and before the `hello`, the client ends a binding holding the binding id the hub returned, as the hub returns for a client joining again from the same installation ([protocol.md](protocol.md), "Joining and leaving"), and the hub is not told. When a `welcome` names a hub id another binding holds, the client ends that binding before it takes the first `state`. If that binding holds a token, the client tells the hub it leaves as **Leave** does, in the background, and a refusal or an unreachable hub changes nothing. The Hubs page then has one row for the hub. | The hub id reaches the client only in the `welcome`, and before it the binding id the hub returned is the one sign of the same hub. A binding with the same id lost its token to the join, and its open session would read the new `hello` as `replaced` by another client. A binding with another id names a row the hub forgot, or a row the hub keeps until the client leaves it. |
| A client that starts with two or more bindings holding one hub id, as an older version left them, keeps the one joined last and ends each other one as a `welcome` ends it, telling the hub for each one that holds a token. | One binding per hub id holds from the start, so every lookup by hub id, the Hubs page's among them, finds one binding. |
| A ticket the hub refuses (`ticket_spent`, or any refusal of the join but `admission_paused`, `control_unavailable` and `channel_full`) puts the row on the `join_refused` line with that code's wording, **Leave** as its only action, and no further rounds; the person scans again. | A dead ticket cannot be revived; a loop on it is a hang with a name. |
| `admission_paused {retry_after_s}` keeps the ticket: the row reads the `admission_paused` line counting down `retry_after_s`, and the client joins again when it reaches 0. | The hub paused new enrolments after too many failures; the ticket behind the pause is still valid. |
| `control_unavailable` and `channel_full` keep the ticket as well. The row reads the `hub_silent` or `hub_off_overlay` line counting down the refusal's `retry_after_s`, or a minute when the refusal names none, and the client joins again when it reaches 0. The hub transport's `control_unavailable` names 5 seconds. | Neither refusal judges the ticket. The hub's transport makes `control_unavailable` while the hub's Python is away, as for a restart. A join that waits a minute comes back up to a minute after the Python. |
| A ticket lives 30 minutes, which the Clients page says beside the QR. | A phone that has to raise a network first needs more than five minutes. |

### The virtual network line

Under a hub's body sits one line for the hub's virtual network: the state
word with the client's address when on, then the error line. Its controls are
the picker and the button in the row. The line has two states a person sees:
`on`, the engine runs and has an address, and `off`, with `error` holding
the engine's code when it stopped. A connect in progress is the job
`overlay_job` `connecting` with `stage` `login`, drawn as `ui.job.connecting`
with a spinner:

| State | Event | Next | The button |
| --- | --- | --- | --- |
| `off` | press **Connect** | `off`, `overlay_job` is `connecting`, `stage` is `login` | a spinner and **Cancel** |
| `off`, connecting | the engine reports an address | `on`; `address` is set and the job ends; a network change, so a round starts at once ("A network change starts a round") | **Disconnect** |
| `off`, connecting | the engine stops, or no address within 90 s | `off`, with error (`overlay_no_address`, or the engine's code) | **Connect** |
| `off`, connecting | press **Cancel** | `off` | **Connect** |
| `on` | press **Disconnect** | `off` after the engine stops; `overlay_job` is `disconnecting` meanwhile | a spinner and `ui.job.disconnecting`, then **Connect** |
| `on` | the hub's frame no longer lists the network | `off`, with `overlay_withdrawn` | **Connect** |
| `on` | the engine stops by itself | `off`, with the engine's code | **Connect** |
| any | the person leaves the hub | `off` | row gone |

| Rule | Reason |
| --- | --- |
| The client never changes the chosen engine, never retries a failed connect and never moves to another network by itself. | The person chose; a client that changes the choice cannot be reasoned with. |
| A connect is one attempt with one stage, `login`: the engine starts, logs in and gets an address within 90 s, with the reason line `ui.stage.login` under the job's word. When the engine has an address the line reads `on`, whatever the hub's channel does. | A mobile network needs most of a minute for the login alone. The line says what the engine did, and the hub row says what the channel did. |
| Nothing on the line depends on the hub's channel: the client sends no probe to the hub through the network, shows no wait for the hub, and never holds the channel to the network's address. | A line that waited on the hub read as a broken network while the network was up, and a channel held to one address missed the others of the round. |
| The `login` stage's start and end is one log line with its duration. | A connect that fails on a phone is explained from the log or not at all. |
| In EasyTier's console mode the `login` stage's 90 s cover the registration with the console; after it the job stays `connecting` with the reason line `ui.reason.console_waiting` (registered with the console, waiting for it to assign a network) until the owner assigns one or the person cancels. | The console's owner decides when a new machine gets a network; the client cannot hurry that, and failing after a minute would read as a fault. |
| At start, a binding whose last state was `on` gets one connect; a failure leaves it `off` with the error and no retry. | A phone that was on the network before a reboot comes back on it; a hub that is gone does not keep the phone trying. |
| While `on`, the hub's address on that network, the material's `address` (never the hub's name on that network), is a candidate of every round and is dialled with the others at once, with no head start. | The network is one more path to the hub, and the round picks the path as for every other address. The desktop runs NetBird without its DNS, so the name resolves nowhere. |
| The picker is disabled while a connect runs and in `on`, and shows the engine's name while disabled. | Changing the engine under a running one is the switch that hangs. |
| The picker is absent when the hub publishes one network; the line then names that engine. | A choice of one is no choice. |
| A machine is on one hub's virtual network at a time, on the desktop as on the phone: while any hub's line is not `off`, **Connect** on every other hub's line is disabled with the reason `overlay_other_network`, and the core refuses a connect for another hub with the same code. | Two hubs' networks on one machine would carry the same addresses two ways, and the machine's one NetBird daemon and one EasyTier console serve one network. |
| A hub that publishes no virtual network has no virtual network line: no state word, no picker, no button and no reason. | A client reaches a hub over its LAN, through Direct, a frp node or the relay, so a hub with no virtual network is an ordinary hub, and a line that names only what is absent tells the person nothing. |

## The Apps page

A row per app ([protocol.md](protocol.md), "Apps"): the app's title, the
machine and the app's source word (`ui.app_source.module`,
`ui.app_source.declared`, `ui.app_source.manual`) as the provider line, and
one mono line per entry, its kind and its local address: `<scheme>://<local
name>:<local port><path>` for a `web` entry, and `127.0.0.1:<local port>`
for a `port` entry, with `/udp` after it for a UDP one. A browser resolves
the local name; the system resolver does not on Windows, and on Linux gives
`::1` first, which no forward listens on, so a port entry names the loopback
address the forward listens on, the address a program is given. The local
addresses are fixed, so the row shows them before the app is used. The
controls:

| Control | Shown | Enabled | Does |
| --- | --- | --- | --- |
| **Use** | while the app is not in use | when some entry of the app is not unhealthy and the hub is not disabled | job `ui.job.opening`: makes every entry's forward the app has not got, and opens nothing; a failure writes the code, the forwards that started staying up |
| **Stop** | while the app is in use, in **Use**'s place | always | job `ui.job.disconnecting`: ends every forward of the app |
| **Configure** | always | when the app is not in use | the local port dialog ("The local port table") |
| **Open** | while the app is in use, for an app with an `http` or `https` entry | always | job `ui.job.opening`: reads `{token}` with the `service` frame when that entry has `is_token_required`, and opens the system browser at the app's first `http` or `https` entry, in the order the hub lists them; a failure writes the code |

An app is in use from the first forward **Use** made until **Stop**, the
hub's leave, or the client's quit.

| Rule | Reason |
| --- | --- |
| The browser opens `<scheme>://<local name>:<local port><path>`, with `?tkn=<token>` added for an entry with `is_token_required`; `<scheme>` and `<path>` are the entry's url's own. On macOS and iOS the host is `127.0.0.1`. | A browser resolves a `.localhost` name to the loopback by itself and keeps cookies per host, so two apps never overwrite each other's login; Safari and WebKit resolve no `.localhost` name, so on macOS and iOS every app shares one host, and two apps whose cookies have the same name sign each other out. |
| A token is read at every **Open**. | The token of code-server, CloudCLI, Codeg, SiYuan, Hermes WebUI and Ayakaleaf is spent once and dies after 60 seconds; VS Code's is read from the URL by VS Code's own page. |
| An entry the hub reports unhealthy keeps its forward and shows `ui.unhealthy` on its line. | The forward stays where the person put it; the service behind it can come back. |
| A declared app's `file` entries are on the Files page and not here, and an app whose entries are all `file` entries has no row. | A share is mounted, not opened in a browser, and the Files page holds every mount. |
| No Apps page shows an `ssh` entry, so the machine's SSH server, whose entries are all `ssh` entries, has no row ([protocol.md](protocol.md), "Apps"). A desktop forwards each `ssh` entry by itself ("The local port table") and reaches it with `nclient ssh` ("SSH for other programs"). | The SSH server is a function of every machine, as the terminal and the remote desktop are, and no program a person opens; a phone reaches a shell on its Terminals page. |
| A phone's Apps page is this page: Android forwards each entry in its foreground service, and iOS while the app is in front ("The iOS app"). | One page on every client; the ports the phones lacked are an app's entries like any other. |

A UDP entry's forward is one UDP socket bound to `127.0.0.1:<local port>`
while the app is in use, and one `connect` stream:

| Rule | Reason |
| --- | --- |
| The forward opens its stream at **Use**, and again at the first datagram that finds it has none, after the hub's session was replaced or the far end closed the stream. | A UDP program has no connection to start a stream with, and a stream that ended is opened again by the next datagram that needs it. |
| An open refused at **Use** ends that forward and writes the code on the row's error line, as a failed bind does. An open refused later writes the code on the error line; the forward goes on listening and tries again at a later datagram, at most once a second. The line goes when a datagram comes back on a stream opened after it. | A refusal at the press is the answer to the press; a refusal later is a state the hub can leave without the person pressing again, and a line left after the far end answers again says a fault that is gone. |
| Datagrams that arrive while an open waits for its `accept` are held, at most `UdpHeldDatagramsMax`, 16, and sent when it comes; more are dropped. No datagram waits anywhere else. | A program's first datagram is often its only one, and a bounded hold keeps it without a queue. |
| Each datagram goes into the stream with the port it came from as `source`. The forward remembers, per `source`, the address it last came from, for at most `UdpSourcesMax`, 64, sources, the one idle the longest giving way; a record for a `source` it no longer remembers is dropped. | A reply returns to the local program that asked, and two programs on one forward stay two peers. |

## The local port table

A forward is a listener on `127.0.0.1:<local-port>` that opens one
`connect` stream to the hub for every connection it accepts and relays the
bytes both ways, or, for a UDP `port` entry, one UDP socket with one stream
for every datagram it carries ([protocol.md](protocol.md), "The connect
stream"). The client's transport holds every forward, which the client
starts with `forward_start` ([transport.md](transport.md), "The local
channel"). No page of any client dials a service's own address; the hub's
agent port is the one address a client dials.

| Entry | The forward listens |
| --- | --- |
| an app's `web` or `port` entry | from the app's **Use** until its **Stop** |
| an `ssh` entry, on a desktop | while the client runs and the hub lists the entry, which it does while it grants this client `ssh` on that machine and the SSH server enables the account |
| `ai` | while the client runs and the hub is the exit of any tool |
| `rdp` | from **Connect** until the viewer ends |
| `file`, on Linux and macOS | from **Mount** until the share is unmounted |
| `file`, on iOS | from **Open** until the share page closes, on a port the system picks ("The share page") |
| an `ssh` entry for `nclient ssh proxy` | for as long as the proxy runs, on no port: the proxy's standard input and output are the stream |
| the hub's panel | from the first press of **Panel** until the hub is left or the client quits |

A `file` entry on Windows goes through the files adapter instead ("The
files adapter on Windows"), and on Android the in-app SMB client's sockets
are `connect` streams themselves; neither holds a local port. A client that
quits ends every forward.

While a hub has no channel, each of its TCP forwards stops accepting new
connections and stays bound to its port. The connections waiting in the
listen queue are accepted and served once the channel is back. The desktop
and the phone do the same. A forward that accepts with no channel can only
close each connection at once. A program such as the kernel's SMB client
then reconnects at once, again and again, for as long as the hub is away.

The local port is the client's to manage:

| Rule | Reason |
| --- | --- |
| An app entry's local port is the hub's `local_port` for it ([protocol.md](protocol.md), "The local name and the local port"), the same on every client. **Configure** opens a dialog of one line per entry: its name, its kind and a number field that starts at the hub's number, with **Save** and **Cancel**; a number of the person's, from 1024 to 65535, replaces the hub's on this client alone, and an empty field goes back to the hub's. **Configure** is disabled while the app is in use, with no line under it. | The port a tool is told to use must not change under it, and a number every client shares holds a saved address on all of them. |
| An `ssh` entry's forward listens at the hub's `local_port` for it, the address `nclient ssh list` prints, and has no **Configure**. A number another program or entry holds fails the forward `port_taken {port}`; the client writes the code to its log and tries again at the hub's next state. | A program given a host and a port keeps them, and every program that reads the SSH configuration needs no port at all. |
| A forward with no hub number, `ai`, `rdp`, every `file` entry, a declared app's among them, and the panel's, takes the first free port from 20000 to 23999, and the client keeps the pick for it and gives it the same port on every later forward and after a restart. | Those forwards are reached by the client's own programs, which read the port from the client. |
| A port is free only when nothing listens on it on any address of the machine: a probe binds it on the IPv4 wildcard address, and on the IPv6 one where the machine has IPv6, with no address-reuse option, and closes it; a TCP entry's probe binds TCP sockets and a UDP entry's binds UDP sockets. On Windows a UDP number is not bound at all: it is looked up in the system's own table of UDP endpoints (`GetExtendedUdpTable`, IPv4 and IPv6), and is free only when no endpoint on any address holds it. The forward itself listens on `127.0.0.1` alone. | A loopback listener beside a server on every address takes that server's local traffic, and on macOS a loopback bind succeeds beside it. A UDP socket bound to a wildcard address makes the Windows firewall ask the person whether to let the client reach their networks. |
| A number is probed again each time its forward is about to listen, with the address-reuse option off Windows so the client's own closed connections still on the port do not count. An app entry's number another program listens on, or another entry of the same protocol holds, is not listened on: that forward fails `port_taken {port}` on the app's error line, and the number never moves by itself. A kept pick of no app that another program now holds is picked again from 20000 to 23999. | A port moved silently breaks a saved address, a clone address or a tool's setting; the person moves it, in **Configure**. |
| The client keeps one table of local ports: the numbers the person set and the picks of forwards of no app, each with its protocol. The dialog refuses with `ui.reason.port_taken` a number that another entry of the same protocol holds in the table or has as its hub number; two entries whose hub numbers collide stay as they are until the person moves one. A TCP entry and a UDP entry can hold one number. The stored table reads an entry with no protocol as TCP. | One table is the only way two forwards never collide that the person can see, and a TCP port and a UDP port of one number are two ports. |

## The AI page

A row per hub's gateway: `ui.module_ai_gateway` as the title, the gateway
address as the mono line, and `→ 127.0.0.1:<local port>` after it while
the forward listens. The desktop controls:

| Control | Enabled | Does |
| --- | --- | --- |
| **AI tools use this gateway** (a chip) | when the entry is not unhealthy, the hub is not disabled and no switch runs | job `ui.job.switching`: makes the entry's forward, reads this client's key with the `service` frame, and points Claude Code, Codex and Gemini at `http://127.0.0.1:<local-port>` with that key ([hub_components/ai.md](hub_components/ai.md)); one hub is the exit at a time, and only a chip the person turned on makes it so: with no chip turned on no hub is the exit; the chip of the other hub turns off in the same push, and its forward ends |
| **Configure** | the same | opens the configuration dialog: a picker per tool for its model and, for Codex, its effort; **Save** and **Cancel**; the dialog is the inline-form idiom with a dirty frame |

Under the controls is the line `ui.ai_needs_client`: the tools reach the
gateway only while this client runs.

A desktop client on a machine the Neutrino agent is installed on leaves the
machine's AI tools to the agent ([hub_components/ai.md](hub_components/ai.md), "How a
managed machine's tools are pointed at the gateway"). The agent is
installed when its program directory exists: `/opt/neutrino/agent` on
Linux, `/Library/Application Support/Neutrino/agent/app` on macOS,
`C:\Program Files\Neutrino\agent` on Windows ([files.md](files.md)). The
resident checks at its start and each time it takes a state from a hub.

| Rule | Reason |
| --- | --- |
| With the agent installed, the chip and **Configure** are disabled, with the reason `ui.reason.ai_managed` under the controls; the row, its address and its forward line still show. | The agent and the client would both write the provider `neutrino` into the same account's cc-switch store, with different endpoints. |
| A client whose chip is on when it first sees the agent turns the chip off and runs its deactivation once, as a press of the chip would; the chip stays off and disabled from then on. | The person's tools go back to what they had, and the agent's setting is the one that points them at the hub afterwards. |
| `nclient ai set` exits with `ai_tools_managed`, the code worded as the reason is; `nclient ai show` still answers. | The command line is the same switch as the chip. |

A phone has no AI page.

## The Files page

A row per `file` entry: the share's name as the title, `<share>
(<account>)` for a folder share's entry, which carries `account`, so a folder
share has a row for each of its accounts ([protocol.md](protocol.md), "The
services section, one entry per published service"); `//host/share` as the
mono line, where the share is on the hub's networks; and the provider line. A share a machine's file share serves, a
Home share or a folder share, comes with its login: the client reads the
share's `{user, password}` with the `service` frame at every mount and asks
the person nothing ([protocol.md](protocol.md), "The service frame"). A
declared share, a NAS the hub does not manage, keeps the person's own login,
which the form asks for. On a desktop the mount is a record with its own
state, and the row's button is the record's:

| Record state | Event | Next | The button |
| --- | --- | --- | --- |
| none | press **Mount** | `pending` | `ui.job.mounting` |
| `pending` | the core takes it | `queued`, then `mounting` | `ui.job.mounting` |
| `mounting` | the system mounts it | `mounted` | **Unmount** |
| `mounting` | a code | `failed`, with the error line; the form keeps its values | **Mount** |
| `mounted` | press **Unmount** | `unmounting`, then `detached`: the record stays | `ui.job.unmounting` |
| `detached` | press **Mount** | `pending`, mounting at the same place with the hub's login read again, or a declared share's kept login | `ui.job.mounting` |
| `mounted` | the entry turns unhealthy | `mounted` | **Unmount**; the state word is `ui.unhealthy` |
| `failed` | press **Mount** | `pending` | `ui.job.mounting` |
| `failed` with a login refusal on a declared share | press **Save** in the form with a new login | `pending`, mounting with the new login at once | `ui.job.mounting` |
| `failed` or `detached` | its entry leaves the hub's list, or another record is set to mount at the same place | none | a failed or detached record is dropped, with a declared share's login, and holds no place |

**Configure** opens the row's form in place. For a machine's share it holds
the place alone; for a declared share it also holds a user name (a picker
over the share's `users`, with typed text accepted) and the password. The
place takes the system's own shape (`mount_location_shape` in the state
document):

| System | Shape | The form's control | The mounted row |
| --- | --- | --- | --- |
| Linux | `path`: a directory under the home | the path with **Browse…**; the default is `~/remote/<machine>-<share>`, and `~/remote/<machine>-<share>-<account>` for an entry whose `account` is set | the path |
| Windows | `drive_letter`: a drive | a picker over the free letters, the first free one by default, with the caption that the share appears as that drive in File Explorer | the letter |
| macOS | `path`: a directory under the home | the path with **Browse…**; the default is `~/remote/<machine>-<share>`, and `~/remote/<machine>-<share>-<account>` for an entry whose `account` is set | the path, and `ui.mount_finder` under it with the server's address |

`<machine>`, `<share>` and `<account>` are the entry's `device_name`, share
name and `account`, each with every character outside letters, digits, `-`
and `_` turned into `-`.
**Mount** needs no form: every field has its default, so a machine's share
mounts at the first press. The form is a configurable panel with a dirty
frame, **Save** and **Cancel**, and **Mount** on a declared share is
disabled until the form has a user name, with the reason on the row.

Every system mounts the share from the hub's channel, never from the
share's own address:

| System | The mount |
| --- | --- |
| Linux | the entry's forward, mounted by the root helper under `pkexec`: `mount_helper mount --share //127.0.0.1/<share> --port <local-port> --location <path> --credentials <file>`, which runs `mount.cifs` with `port=<local-port>` among its options and deletes the credentials file once the mount answered; a machine with no `pkexec` refuses the mount `pkexec_missing`, a `failed` the timer does not retry |
| macOS | the entry's forward, mounted by the system as below, with the place a symbolic link to the volume |
| Windows | the files adapter's address for the share's machine and SMB user, `net use <letter>: \\<fake-address>\<share>` ("The files adapter on Windows"); a share of the client's own machine (`is_own_machine`) is mounted from the machine's own SMB server directly, through no adapter, at `\\127.0.0.1`, `\\localhost` or `\\<host name>`, one server name per SMB user |

On macOS the client does not mount the share itself: it asks the system to
mount the volume through `osascript`, with the one-line script on its
standard input and never on an argument:

```text
mount volume "smb://<user>@127.0.0.1:<local-port>/<share>" as user name "<user>" with password "<password>"
```

The volume is the one the Finder's **Connect to Server** would make, listed
under the server in the Finder's sidebar. The record's mount point is read
back from the mount table once the system has mounted it
(`//<user>@127.0.0.1:<local-port>/<share> on /Volumes/<name> (smbfs, …)`),
and the client makes the place a symbolic link to it, removed at the
unmount; **Unmount** ejects that mount point with `diskutil unmount`, which
needs no administrator. A volume the system already has mounted for the
same address, port and share is taken as mounted, not mounted twice.

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
`mount_timed_out`, a `failed` the timer never retries by itself.

A phone has no mount. Its row shows **Open in Files**, which makes the share
a location in the system's Files app through the client's file provider, and
the iOS app's row opens its share page ("The share page"). A machine's share
logs in with the hub's login at every open; a declared share's password is
asked once in a sheet and kept in the keystore, and **Forget password** on
its row arms and removes it. The app's SMB client reaches the share through
its socket factory, which hands it sockets whose bytes are `connect`
streams naming the file entry.

## The files adapter on Windows

The Windows SMB client dials port 445 alone, and the system holds the
machine's own 445, so a forward on a loopback port cannot carry a share.
The Windows client puts every machine that provides a share on a virtual
adapter, at an address of its own for each SMB user it mounts the machine's
shares as, and sends the adapter's SMB connections to the hub.

| Part | What it is |
| --- | --- |
| The adapter | `neutrino_files`, a wintun adapter at `198.19.255.1/24`, with no gateway and no DNS server, connected to no network <!-- scan: allow --> |
| The fake addresses | one per pair of a machine other than the client's own that provides a `file` entry and an SMB user a mount logs in to it as, from `198.19.255.2` to `198.19.255.253`, kept per hub, machine and user in the client's store, so a drive letter keeps naming the same pair; the machine is the entry's `device_id`, or its host for a declared record, and the user is the `user` the hub gives for a machine's share, or the user name of a declared share's login <!-- scan: allow --> |
| tun2socks | the MIT-licensed executable the client's package includes, credited on the About card, run with the adapter as its device and the SOCKS endpoint as its proxy; it hands every TCP connection entering the adapter to that endpoint |
| The SOCKS endpoint | a SOCKS5 listener of the resident on `127.0.0.1`, behind a user name and password the resident generates at each start; it accepts a connection to `<fake-address>:445` of a pair it knows and opens a `connect` stream naming a `file` entry the client mounts from that machine as that user, and refuses any other address or port |

Windows connects to one server as one SMB user at a time, and refuses a
mount as a second user name to the same server with error 1219. Two
accounts' Home shares of one machine, or a folder share's entries for two
accounts, are two pairs, and so two servers to Windows, each mounted at
its own fake address.

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
mounted from the machine's own SMB server on its own 445, takes no fake
address and brings the adapter up for nothing; its row reads as any mounted
row. On Linux and macOS such a share takes its forward like any other:
neither system's SMB client is the Windows one that the server recognises
as its own.

| Rule | Reason |
| --- | --- |
| The first SMB user that mounts a share of the client's own machine mounts it from `\\127.0.0.1\<share>`, the second from `\\localhost\<share>`, and the third from `\\<host name>\<share>`, the machine's host name. | Windows connects to one server as one SMB user at a time. `localhost` and the host name reach the machine's own server as two more servers; `127.0.0.2` and `[::1]` do not reach it. |
| A mount record keeps the server name it took and mounts from it again. A record with no name, or whose name another user's mounted share uses, takes the name a mounted share of its own user uses, else the first name no record of another user keeps, else the first name no mounted share of another user uses. | A drive letter keeps naming the same server, and two users never mount from one name at once. |
| A fourth user, while a mounted share of every name logs in as another user, is refused `share_session_conflict`, a `failed` the timer does not retry. | Windows has no fourth name for its own server. |

When the adapter cannot be made, because the service is missing, stopped or
refuses, the mount record goes `failed` with `files_adapter_unavailable
{detail}` on the row's error line, and nothing else changes on the system.

## The Terminals page

The page is, from top to bottom: a card with the machine chips, the
account picker and **New terminal** after them, the tab strip, the
terminal, the status line, and on a phone the key row. The status line holds the two switches
at the right, and on a phone the **Keyboard** and **Keys** buttons at its
left end.

| Rule | Reason |
| --- | --- |
| Tabs stay mounted while hidden; switching tabs loses no output. | A terminal redrawn from scratch loses its scrollback. |
| The chips name every machine in the state's `terminals`, each with its provider line; the picked chip is the one a new terminal opens on. | The person opens a terminal on a machine, and the machine is the first choice to make. |
| The account picker lists the picked machine's enabled accounts, the Terminal module's on that machine, the first one chosen; it is drawn only when the machine enables two or more, and a new terminal runs as the account it shows, with no password asked. | A terminal is one of the machine's accounts the person enabled, and a choice of one is no choice. |
| **New terminal** is disabled with no chip picked, with the picked machine offline, or with no account enabled on it, with the reason under the chips, `ui.reason.terminal_no_account` for the last. | Nothing opens on a machine that cannot answer, nor as an account nobody enabled. |
| Keys reach the machine in the order they were pressed: a tab has one sender that writes its bytes in sequence, on every client. | A letter that overtakes the one before it types another word. |
| **Clear**, wherever a client offers it, sends Ctrl+C, clears the screen, drops what had arrived and was not yet drawn, and goes on dropping what arrives until the stream has been quiet for half a second, for twenty seconds at most. While it drops, the terminal's own box shows `ui.job.clearing` ("Clearing…", 「清屏中…」) where the output would be, and the word goes when the dropping ends. The desktop and the phone behave the same. | A clear that is followed by the rest of the flood clears nothing, and how long the flood's tail takes to cross the hub is not a number a client can know. |
| A plain session ends when its tab closes; a persistent or shared session's **×** arms and the second press ends the session with `stop_session`. | Ending a session others can see takes two presses, like every destructive action. |

### The colours

Every client's terminal draws the 16 ANSI colours from one fixed palette, the
Tango palette, which is also xterm.js's own default:

| Colour | Normal | Bright |
| --- | --- | --- |
| black | `#2e3436` | `#555753` |
| red | `#cc0000` | `#ef2929` |
| green | `#4e9a06` | `#8ae234` |
| yellow | `#c4a000` | `#fce94f` |
| blue | `#3465a4` | `#729fcf` |
| magenta | `#75507b` | `#ad7fa8` |
| cyan | `#06989a` | `#34e2e2` |
| white | `#d3d7cf` | `#eeeeec` |

| Rule | Reason |
| --- | --- |
| The 16 colours are the same in the light and the dark theme. None is taken from the client's accent or status colours, and none is inverted. The 256-colour cube and truecolour are drawn as the terminal library draws them. | A prompt draws a segment as text in one of these colours on a fill in another. A theme's text shades put in their place lose the pair's contrast, and the person's own terminal draws the same prompt in these colours. |
| The default foreground, the default background, the cursor and the selection follow the client's theme (System, Light or Dark), taken from the client's own theme colours. Every open terminal takes the new ones at once when the theme changes. | Plain text reads like the rest of the page in either theme. |
| Bold text keeps its colour: a bold character in one of the eight normal colours is drawn bold in that colour, never in its bright twin. In xterm.js, `drawBoldTextInBrightColors` is `false`. | A program asks for a bright colour by its own code. Drawn bright, the bold green of a shell prompt and the bold blue of a directory turn pale on the light background. |

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
| the hub's channel drops and comes back | a tab whose session is in the new list attaches again by itself and replays the kept output, its terminal keeping what it showed until the replay's first bytes arrive; a tab whose session is gone, as a plain session ends with its channel, reads `ui.terminal_ended` and keeps its last output; nothing stays on "not connected" after the hub is back |

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

`nclient terminal` is the same terminal on the command line ("The command
line").

### The phone terminal

| Rule | Reason |
| --- | --- |
| A key row sits at the foot of the terminal's card, under the status line, whether the keyboard is shown or not: Esc, Tab, Ctrl, Shift, Alt, the four arrows; a modifier is sticky for one key and shows pressed while held. With the keyboard shown, the page is scrolled to its end, so the key row sits right above the keyboard. | The system keyboard has none of them, and a key row that comes only with the keyboard is gone whenever the keyboard is. |
| At the left end of the status line, left-aligned, sit two round buttons in the look of the remote desktop viewer's, with its icons, sized to the line: **Keyboard** opens and closes the keyboard and shows pressed while the keyboard is shown; **Keys** hides and shows the key row and shows pressed while the row is shown. **Persistent** and **Shared** stay at the right. The key row starts shown, and the terminal's box grows by the row's height while it is hidden. A tap on the terminal still opens the keyboard. | One press opens the keyboard where a tap on a small terminal can miss, and a person who types no special keys gives their row to the terminal. |
| With the keyboard shown, the terminal's box shrinks to the space left above the key row, which stays above the keyboard, and the terminal refits its rows; the prompt line stays in view and nothing collapses. The top bar is drawn in every orientation. A phone in landscape with the keyboard up has room for the key row and little else, which is accepted: a tablet is the device for a landscape terminal. | A key row under the keyboard cannot be pressed, and a prompt below the fold cannot be read. |
| The font falls back to a face that has the box-drawing, geometric and powerline symbols for every glyph the monospace face lacks. | A prompt in boxes is unreadable. |
| The terminal's viewport scrolls by touch and shows a thin bar; the view follows output only at the bottom. | History on a phone is reached by the finger, and a bar says there is some. |
| A long press opens the same menu as the desktop's right click, with **Copy** and **Paste** through the system clipboard. | The phone's clipboard is the system's. |

## The Remote desktops page

A row per shared desktop: the machine's name, the provider line, the state
word. The controls:

| Control | Enabled | Does |
| --- | --- | --- |
| **Connect** | when the entry is not unhealthy, the hub is not disabled and no viewer runs on it | job `ui.job.connecting`: reads `{password}` with the `service` frame and makes the entry's forward; on a desktop starts the viewer at `127.0.0.1:<local-port>` with the seat password on its command line, the one channel RustDesk 1.4.9 has for a connect password (its peer file takes only a hash salted by the host), and follows the viewer process, on Windows the copy the bundled viewer starts of itself from its own data directory; on a phone opens the viewer page, whose core dials the same forward. The forward ends with the viewer. The command line is `nclient rdp connect <machine>` |
| the viewer | | on a desktop a separate window, and the row then shows `ui.rdp_open`; on a phone a page of the app whose three round buttons open the keyboard, the key bar of Esc, Tab, Ctrl, Shift, Alt, Win, **Paste** and the arrows, and close the session |
| **Configure** | on a phone, when the entry is not unhealthy | the dialog of the inline-form idiom with two pickers: **Codec** (Auto, then each codec the core offers) and **Quality** (Balanced, Low bandwidth, Best); **Save** and **Cancel**; the choice is kept per entry in the app's settings and applied at the next connect |

One entry has one viewer at a time. A Connect while that entry's viewer
runs, from the command line as from the window, is refused
`rdp_viewer_open` and leaves the running viewer and its forward as they
are; the person closes the viewer, and the next Connect makes a new one.
Two viewers on one forward would end it under each other, since the forward
ends with the viewer.

The forward lives as long as the viewer window that shows it: a viewer the
client starts whose process ends within `RDP_HANDOFF_S` (5 s) while another
viewer it started still runs has handed its connection to that viewer's
window, as RustDesk does with a second `--connect` (a tab in the running
window), so its forward stays, the row reads `ui.rdp_open`, and both end when
that window's process ends; the rule is the same on every system.

The row's mono line is the entry's host and port, where the desktop is on
the hub's networks; the viewer dials the forward on the loopback and never
that address. The row's state word is the entry's health, and `ui.rdp_open` while the
viewer runs.

The phone's viewer page is built for the picture first:

| Rule | Reason |
| --- | --- |
| The page is immersive: the system's bars are hidden and come back on an edge swipe, and the picture fills the screen. | A phone's screen is small; every bar on it is taken from the desktop. |
| No title bar. Three translucent round buttons sit at the top right and stay: **Keyboard** raises the phone's keyboard and takes typing, and shows the keyboard's own state, so a keyboard the system floats over the picture counts as shown and the next press closes it; **Keys** shows the key bar; **Close** ends the session. Both the keyboard and the key bar start off, so the page opens on the picture alone. | A title the person already knows and bars that hide on a timer take the picture away and make the way back hard to find; three buttons that never move are found by feel. |
| The keyboard and the key bar never shrink the picture or change its zoom. The key bar sits right above the keyboard, or at the bottom edge with the keyboard down. While either is up, the picture's space is the screen above them. As they come up, the picture moves up by the height they take, and as they go, back down by that height. In either space, a picture that fits is centred. A larger one stops where an edge would leave a gap, and a pinch reaches every part of it. | A picture squeezed to a strip above the keyboard cannot be worked on, and one left under the key bar hides the remote taskbar. |
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

## SSH for other programs

The desktop client lets every program that speaks SSH reach the machines'
SSH servers ([agent/modules/ssh_server.md](agent/modules/ssh_server.md)):
`ssh`, `scp`, `sftp`, `rsync`, `git`, VS Code's Remote-SSH and JetBrains
Gateway through an SSH configuration of the client's own, and a program that
takes only a host and a port, such as FileZilla, WinSCP or Termius, through
the fixed local address of the account's `ssh` entry, `127.0.0.1:<local
port>`, which `nclient ssh list` prints and the client forwards while it
runs ("The local port table"). The SSH server is no app, and no Apps page
shows it ([protocol.md](protocol.md), "Apps"). A phone has none of this; it
reaches a shell on its Terminals page.

The client writes `~/.ssh/neutrino_config` again whenever the machines it
reaches by `ssh` change: one block for each machine that has an entry of the
type `ssh` this client is allowed, across every hub it is bound to.

```text
Host lab-gpu.nt
    User iffi
    ProxyCommand nclient ssh proxy "%r@%h"
    IdentityFile "~/.ssh/neutrino/lab-gpu_%r"
    IdentitiesOnly yes
    UserKnownHostsFile ~/.ssh/neutrino/known_hosts
    HostKeyAlias lab-gpu.nt
```

| Rule | Reason |
| --- | --- |
| A machine's host is the machine part of its apps' local names, followed by `.nt`; two hubs that hold a machine of one slug give each `<machine>.<hub>.nt`, the hub's name by the same slug. `User` is the machine's first `ssh` entry's account, the SSH server's first enabled account, since the hub lists the entries in that order. | One short name per machine, and the account a person most often means is the one they enabled first. |
| `ProxyCommand` is `nclient ssh proxy`, which connects the program's standard input and output to the account's `ssh` entry through the running client; it takes the host as `ssh` gives it, `.nt` and all, and `%r` names the account, so `ssh lab@lab-gpu.nt` reaches the instance of `lab`. The two are quoted, since a Windows account's name can hold a space. | The connection goes through the hub as every stream does, and each account has an instance of its own. |
| The client reads each account's key with the entry's `service` frame when the entry first appears, at each rewrite, and when the entry's `account_key_fingerprint` changes, as a **Rotate** on the Credentials page changes it, and writes it to `~/.ssh/neutrino/<host>_<account>`, `<host>` the machine's host without `.nt`, mode 0600, and each machine's host key to `~/.ssh/neutrino/known_hosts`, Neutrino's own, as `<host> <key>`. An `ssh` entry stays listed while its account is enabled, so a restart of the instance keeps its key; the client deletes the key of an entry that leaves its list. | `ssh` refuses a key file others can read, and a known_hosts of the client's own keeps the person's file as it is. |
| On Windows the files are the same under `%USERPROFILE%\.ssh`, the key's access list granting the person's account alone, and `ProxyCommand` names `nclient.exe`. | Windows' OpenSSH reads the same configuration and checks the key file by its access list. |
| The client never edits `~/.ssh/config` by itself. `nclient ssh config install`, or the **Settings** page's switch **SSH programs reach the machines** (`ui.settings.ssh_include`), adds `Include ~/.ssh/neutrino_config` as its first line, once; `uninstall` and the switch turned off take that line out and nothing else. | The person's SSH configuration is the person's, and an `Include` at the top is the one line that makes `<machine>.nt` known to every program. |
| `~/.ssh/neutrino_config`, the keys and the known_hosts go when the client's last hub is left. | Nothing of a hub stays after the client leaves it. |

## The command line

`nclient` is the client's command line, one command for each button of the
window. Every command but `gui` reaches the hub through the running client
and exits 1 with `client_not_running` when no client runs. Its groups
follow the window's pages, with the program itself and `ssh` above them:

| Command | Does | Exit status |
| --- | --- | --- |
| `gui` | runs the client and its window, or brings a running client's window to the front | 0 |
| `quit` | stops the running client: closes the window, and ends every forward and mount | 0 |
| `ssh list` | prints each machine with an `ssh` entry and its accounts, the default first, each account followed by its entry's local address `127.0.0.1:<local port>` | 0 |
| `ssh open [<account>@]<machine> [-- <command>]` | runs the system's `ssh` with `-F ~/.ssh/neutrino_config` against `<account>@<machine>.nt`, the first account when none is named; with `--` it runs the command alone and exits with its code | `ssh`'s own |
| `ssh config show` | prints the path and the text of `~/.ssh/neutrino_config` | 0 |
| `ssh config install`, `ssh config uninstall` | adds or takes out the `Include` line ("SSH for other programs") | 0 |
| `ssh proxy [<account>@]<machine>` | joins its standard input and output to the account's SSH server, for `ProxyCommand`; `<machine>` can end in `.nt` | 0 when the stream ends, 1 for a refusal |
| `hub list` | prints each hub: its name, its connection, the way it is reached, and the round trip | 0 |
| `hub join <link>` | joins a hub with a link, as **Join a hub** does | 0, 1 for a refusal |
| `hub leave <hub> [--yes]` | leaves a hub, as **Leave** does, after a `[y/N]` question that `--yes` answers | 0, 1 for a refusal |
| `hub open <hub>` | opens the hub's panel in the browser, as **Panel** does | 0, 1 for a refusal |
| `app list` | prints each machine's apps: the app, its source, each entry's kind and local address, and whether it is in use | 0 |
| `app use <app>` | uses an app, as **Use** does: makes every entry's forward and prints each entry's local address, opening nothing | 0, 1 for a refusal |
| `app open <app>` | opens the browser at the app's first `http` or `https` entry, as **Open** does; refused `app_not_in_use` for an app not in use and `app_no_page` for an app with no such entry | 0, 1 for a refusal |
| `app stop <app>` | ends an app's forwards, as **Stop** does | 0 |
| `app set <app> --port <entry>=<port>` | sets an entry's local port on this client, as **Configure** does; `--port` repeats; an empty port goes back to the hub's | 0, 1 for a refusal |
| `ai show` | prints each AI tool's gateway address and whether it is the hub's; a desktop alone | 0 |
| `ai set` | points the AI tools at the hub's gateway, as the AI page's chip does, and again to refresh them; a desktop alone | 0, 1 for a refusal |
| `file list` | prints each machine's shares: the share, with its account for a folder share's entry, where it is mounted here, and whether it is mounted | 0 |
| `file mount <machine>[/<share>] [--account <account>] [--path <path> \| --drive <letter>]` | mounts a share, as **Mount** does, at the place given or the default ("The Files page"); the share's name can be left out where the machine has one share, and `--account`, which picks a folder share's entry, where the share has one account | 0, 1 for a refusal |
| `file unmount <machine>[/<share>] [--account <account>]` | unmounts it | 0, 1 for a refusal |
| `terminal list <machine>` | prints the machine's sessions: the session id's first eight characters, the account, how long it has been open, whether it is persistent, whether it is shared, and who is attached | 0 |
| `terminal open <machine> [--account <account>]` | opens a new shell in this terminal, as the account named or the first enabled one; the shell ending ends the command | 0 once the shell closed, 1 for a refusal, 2 for a machine that is not offered |
| `terminal attach <machine> <session>` | attaches to a kept session, one this client owns or a shared one, its kept output first; Ctrl+] leaves it running | as `open`, and 2 for a session the machine does not list |
| `terminal exec <machine> [--account <account>] -- <command>` | runs one command through an `exec` stream ([protocol.md](protocol.md), "The exec stream"): this process's stdin goes up as it is and ends with `eof`, the remote stdout comes out on stdout and the remote stderr on stderr, unchanged | the remote command's exit code; 125 for a refusal, from the hub, the agent or the client itself; 126 when no hub offers the machine |
| `terminal set <machine> <session> [--persist on\|off] [--share on\|off]` | changes a session: whether it stays after its last window closes, and whether other clients can attach | 0, 1 for a refusal, 2 for a session the machine does not list |
| `terminal stop <machine> <session>` | ends a session and every program in it | as `set` |
| `rdp list` | prints each machine sharing its desktop: who is at the screen, and how many viewers it has | 0 |
| `rdp connect <machine>` | opens the viewer on the machine's desktop, as **Connect** does, the seat password read from the hub | 0, 1 for a refusal |
| `settings show` | prints each setting of the **Settings** page: its name, its value and the values it takes | 0 |
| `settings set <name> <value>` | changes one setting: `language`, `theme` or `ssh_include` | 0, 1 for a value it does not take |

| Rule | Reason |
| --- | --- |
| Every level prints its help with `-h`: the first line what it does, then one line per argument, then an example. The words are the same in meaning as the window's. | A person finds the next word where they stand. |
| A machine, a hub, an app and a share are named as `list` prints them; an app two machines hold under one name is named `<machine>/<app>`, and a hub's ordinal from `hub list` names it as well. A name that matches nothing prints the names there are and exits 1. | The name a person reads is the name they type. |
| `--hub <hub>` names the hub where several hold the same machine. `exec` also takes `--tty`, which opens it with `is_tty` on a pseudo-terminal of this terminal's size, for programs such as `top` and `vim`. | Two hubs can manage machines of one name, and a full-screen program needs a terminal. |
| A refusal prints one line, the code's words in the client's language, and no stack: `client_not_running`, `permission_denied {kind}` as "the hub gives this client no `<kind>` permission", `agent_offline {device}` as "`<machine>` is offline". | A command line is read by a person or a script, and both want the one line that says why. |
| A session id is matched by prefix among the sessions the state lists on that machine, as git matches a commit id: one match is the session; none exits 2 with `session_unknown`; several print every candidate and exit 2. | Eight characters are short enough to type, and a prefix that matches two sessions is never guessed at. |
| `exec` takes no session id, never opens a persistent or shared session, exits 125 and 126 for its own outcomes and never 1 or 2, and without `--tty` puts neither stdin nor stdout in raw mode. | A script's input reaches no session another window sees, the remote command's own 1 and 2 stay apart from the client's, as ssh and docker keep them, and a pipe has no terminal mode. |
| `terminal set` changes a session for its owner only; any other client gets the hub's `session_not_owned` and exits 1. | The person who opened a session decides whether it stays and who sees it. |
| The hidden `easytier-daemon` and `files-daemon` are the services the package installs, and no person types them. | They are the client's privileged halves ("One client per machine", "The files adapter on Windows"). |

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
edition: GitHub for `intl`, and `https://cnb.cool/iffi-X/neutrino` on CNB
for `cn`; the desktop window reads the
edition from the `edition` field of its state document. In `cn`, a carried
core's **Source** opens a Gitee repository that holds the same tag at the
same commit where one exists: EasyTier's own `gitee.com/easytier/EasyTier`
and Gitee's `gitee.com/mirrors/rustdesk`; the other cores keep their
upstream link. A row
is the label at the left in the muted colour and the value in mono at the
right, rows parted by the panel's faint rule. The second card holds a
**Language** picker, a **Theme** picker (System, Dark, Light), on a desktop
the switch **SSH programs reach the machines** ("SSH for other programs"),
**Save** enabled while the draft differs from the saved values, and
**Cancel** beside it. Each control is one setting `nclient settings` names:
`language`, `theme` and `ssh_include`. There is no About page. Leaving a hub is on the Hubs page and nowhere
else.

## Phone differences

| Feature | Desktop | Phone |
| --- | --- | --- |
| join | paste the link | scan the QR, or paste the link; either adds the hub at once |
| app | **Use** forwards every entry; **Open** opens the system browser at the first web entry, with the token for an entry with `is_token_required` | the same: the app forwards in its core, and **Open** opens the system browser, the in-app browser on iOS |
| file entry | mount the forward, or the files adapter's address on Windows, with the share's user and password from the hub | a location in the system's Files app on Android and the share page on iOS, their sockets `connect` streams, with the user and password from the hub |
| SSH for other programs | `~/.ssh/neutrino_config`, `nclient ssh` and each `ssh` entry's local port | none; a shell is on the Terminals page |
| AI entry | point the tools at the forward, configure them | none: no **AI** page |
| remote desktop | the viewer process, at the forward | the viewer page, at the forward |
| hub's panel | **Panel** on the hub row | the same |
| terminal input | right-click menu, shortcuts, middle click | the key row, long press |
| frame | sidebar, tray | bottom bar in portrait; a sidebar in landscape, and in portrait on a tablet at least 720 dp wide |

Everything else is the same: the order of the pages a phone has, the words,
the state machines, the badges, the dots and the reasons on disabled
buttons.

The Android app keeps its connections when the person switches apps:

| Rule | Reason |
| --- | --- |
| While any hub is bound, the app core runs in one foreground service with one notification line; the hub channels, the share connections and the forwards live in it, and nothing closes when the app leaves the screen. | A process the system freezes answers no ping, and the hub closes the channel within a minute; a service is what the system keeps running. |
| Returning to the foreground reconnects a dropped channel at once, with no backoff. | The person is looking; a wait they can see is a fault. |
| A share's root stays listed in the system's Files app for 60 s after its hub's channel drops, marked as reconnecting. | A root that vanishes mid-copy fails the copy. |
| There is no setting for this. | A connection that holds is the product, not an option. |

## The iOS app

The iOS app is the client on an iPhone. Every rule this page gives for a
phone holds for the iOS app, except where this section says otherwise. Its
floor is iOS 16 ([min_support.md](min_support.md)), and the person installs it by signing
the release's unsigned `.ipa` with their own Apple ID
([release.md](../agent_work_rule/release.md), "iOS app").

| Feature | Android | iOS |
| --- | --- | --- |
| pages in the bar | **Hubs**, **Apps**, **Files**, **Terminals**, **Remote desktops** and **Settings**, in that order | the same |
| join | scan the QR, or paste the link | the same |
| virtual network | the line under the hub's body, with its picker and its button; the app runs NetBird or EasyTier | no line; the app runs no engine, and a person who wants a virtual network on the iPhone joins it with that network's own app |
| an app's web entry and the hub's panel | the system browser, at the entry's forward | the in-app browser, at the entry's forward inside the app ("The in-app browser") |
| an app's port entries | forwarded at their local ports in the foreground service | forwarded at their local ports while the app is in front, and closed with every other forward when it leaves the screen ("In the background") |
| file entry | a location in the system's Files app | the share page inside the app ("The share page") |
| remote desktop | the viewer page | the same, with the RustDesk core linked into a device build ("The remote desktop viewer") |
| terminal | the key row and the long-press menu | the same, drawn by SwiftTerm |
| the app's name under its icon | 微子 with the phone's language Chinese (`app_name` in `values-zh-rCN/strings.xml`), Neutrino otherwise | the same, from `CFBundleDisplayName` in `zh-Hans.lproj/InfoPlist.strings` and `en.lproj/InfoPlist.strings` |
| background | a foreground service keeps every connection | the app closes every connection before iOS suspends it ("In the background") |

The in-app browser and the share page are reached from another page, as
**Join** is: a back arrow and the page's title in the top bar, and no bar
entry.

### Reaching the hub

| Rule | Reason |
| --- | --- |
| The app speaks the channel at the same `PROTOCOL` as the other clients, through the transport it embeds: one session to the hub's agent port under the binding's `hub_key`, and every service a stream on it. | One protocol for every client is one protocol to test, and the hub treats a client the same on every system. |
| A round dials the hub's name, the binding's `urls`, and the hub's address on every virtual network the hub publishes (the `address` of each `overlays` entry), all at once. | The app cannot see whether another app's virtual network is up, so it dials the address, and the round keeps whichever connection completes first. |
| A VPN that another app connects or disconnects is a change of the device's connectivity, and starts a round ("A network change starts a round"). | The hub's address on that network becomes reachable, or stops being reachable, at that moment. |
| Away from the hub's LAN, the app reaches the hub at the agent port open to the internet: Direct, with IPv6 or a port forward on the router, SakuraFrp, OpenFrp, or the SSH relay. | Each of these is an address in `urls`, and the app dials it as it dials any other. |

### The in-app browser

| Rule | Reason |
| --- | --- |
| **Open** on an app in use reads the token as on Android, and **Panel** on a hub row makes the panel's forward and reads its token; each then opens the in-app browser at `<scheme>://127.0.0.1:<local-port><path>`, with `?tkn=<token>` where the entry has `is_token_required`, and `/?tkn=<token>` for the panel. | iOS suspends the app while another app is in front, and a suspended app's forward answers nothing, so the system browser cannot use it. WebKit resolves no `.localhost` name, so the host is the loopback address, as on macOS. |
| The in-app browser is a WebKit web view under the top bar. Its back arrow closes the page; the forward listens until **Stop**, as on every client. | A page closed by mistake opens again with **Open**, on the same port. |
| Every page the in-app browser opens shares one cookie store and the host `127.0.0.1`, and a cookie belongs to its host whatever the port, so two instances whose cookies have the same name sign each other out, as on macOS. | iOS 16 gives an app one persistent web data store. |

### The share page

The share page reads and writes one share with AMSMB2 4.0.3, the SMB2 and
SMB3 client the app carries, which builds libsmb2 from its source. Both are
LGPL-2.1, and the app carries them as one framework of their own, linked
when the app starts.

| Rule | Reason |
| --- | --- |
| The file entry's row shows **Open** and, for a declared share while a login is held, **Forget password**, which arms and removes it. A machine's share logs in with the user and the password the `service` frame hands at every **Open** and every later login, shows no sheet and keeps nothing; a login it refuses writes `share_hub_login_rejected` on the row's error line, and the next **Open** reads the hub's login again. | The Android row's password rules, on a page of the app's own, and a machine's share needs no password from the person. |
| The first **Open** of a declared share shows a sheet: the user name (a picker over the entry's `users` when it names several, else a field holding the one it names), the password, **Remember** (on at first), **Cancel** and **Connect**. **Connect** logs in to the share, its button showing `ui.job.connecting`. A login the share takes is kept, in the Keychain with **Remember** on and until the app quits with it off, and the share page opens at the share's root. A refusal is worded in the sheet, and nothing is kept. | A login is kept only once the share has taken it, so a mistyped password is never kept. |
| **Open** with a login held logs in under `ui.job.opening` and opens the share page; a failure writes its code on the row's error line. `share_login_rejected`, on **Open** or on any later login of the open declared share, forgets the held login, so the next **Open** shows the sheet. | A password the share rejects has changed, and keeping it would fail every **Open** after it. |
| While the share page is open, AMSMB2 dials `127.0.0.1:<port>` and the share's name. The port is a forward of the app's own: a listener on `127.0.0.1` at a port the system picks, each accepted connection a `connect` stream naming the file entry, accepting nothing while the hub has no channel ("The local port table"). The port is in no local port table. | The share is reached through the hub, as on every client. Only the app's own SMB client dials the port, so no person needs its number to stay put. |
| The page lists one folder: folders first, then files, each sorted by name; a file's row shows its size and the time it changed. A tap on a folder opens it. The back arrow goes up one folder, and at the share's root closes the page, its connection and its forward. A pull on the list or the refresh button reads the folder again, after logging in again when the share's connection ended, as when the hub's channel dropped under it. | One folder per screen is how a phone lists files. |
| A tap on a file reads it into the app's temporary directory, its row showing `ui.job.opening`, the bytes read of the file's size, and **Cancel**. The system's preview (Quick Look) then shows the file, and its share button saves it to the Files app or sends it to another app. | The system's preview and share sheet open every kind of file the phone can open, and move it anywhere the person chooses. |
| Each row has a menu: **Rename**, **Save to Files** on a file, and **Delete**. **Rename** opens a dialog with the name to change. **Save to Files** reads the file as a tap does, under `ui.job.downloading`, then opens the system's export picker. **Delete** arms the row: an armed button, `ui.delete_armed`, takes the menu's place, and a press on it within 5 s deletes the file, or the folder with everything in it, as on Android. | The button rule's arming, reached from a menu, the place a phone keeps a row's actions. |
| The page has three actions, **Upload from Files**, **Upload from Photos** and **New folder**: in the menu of the one floating **+** button at the page's bottom right, in both layouts. **Upload from Files** opens the system's document picker for one or more files, copies each into the app's temporary directory, and writes each into the folder on a row of its own above the folder's rows, showing `ui.job.uploading`, the bytes written of the file's size, and **Cancel**. **New folder** opens a dialog for the name. | One button holds the page's actions in every layout, and every action starts from it. |
| **Upload from Photos** opens the system's photo picker (`PHPickerViewController`) for one or more photos and videos. Each item comes as its original, a HEIC photo as HEIC and a video as it was taken, as **Save to Files** in Photos gives it. Its file is copied out of the picker's temporary place into the app's temporary directory before the picker's callback returns, and is named by the name Photos suggests with the extension of that file, or by the file's own name when Photos suggests none. It is then written as a file from **Upload from Files** is, with the same row, numbering, **Cancel**, **Retry** and background rules. An item the picker does not hand over writes `share_photo_unavailable` on the page's error line, and the other items upload. | The photo picker runs outside the app, so the app reads no photo library and asks for no permission. The original is the file the person sees in Photos. |
| An upload or a new folder whose name the folder already holds takes the first free name of `<name> (1).<ext>`, `<name> (2).<ext>` and on, the number before a file's extension and at the end of a folder's name, as on Android. A rename to a name the folder holds is refused `share_name_taken`. | A copy never overwrites, and a rename does what the person typed or nothing. |
| One transfer runs at a time per open share, in the order the transfers were added: a read for a tap or for **Save to Files**, an upload from Files or from Photos, and a **Retry** of any of them. Every other transfer's row shows `ui.share_waiting` and **Cancel**, and the next one starts when the running one ends. | The share's one connection carries one request at a time, so transfers side by side only take turns inside it, and none of them shows how far it is. |
| A running transfer's row shows how many bytes the share's forward has carried since the transfer started, up for an upload and down for a read, while that is more than AMSMB2 has reported. That count stays below the file's size until AMSMB2 reports the end, and the row is drawn again about four times a second. | AMSMB2 moves a file in pieces of the server's largest read or write, 8 MiB on Samba and on Windows, and reports only after each piece; the forward also carries the requests of a listing or a rename, which the cap keeps out of the end. |
| **Cancel** stops a running transfer after the piece AMSMB2 is moving: a cancelled read leaves no file, and a cancelled write deletes the part it wrote. **Cancel** on a waiting row removes it at once. | A cancelled file is a file the person did not want. |
| A failure writes its code on the row's error line, or on the page's error line for a listing, a new folder, an item from Photos or the login on the return to the foreground: `share_login_rejected`, `share_hub_login_rejected`, `share_access_denied`, `share_not_found`, `share_unreachable`, `share_name_taken`, `share_photo_unavailable`, or the hub's code when the hub refused the forward's `connect` stream. | The codes the desktop and Android word, and the hub's code where the hub is what failed. |

A File Provider extension, the way an app adds a location to the system's
Files app, runs in a process of its own while the app is suspended, and so
needs a session of its own to the hub. A binding holds one session: a second
one replaces the first with `replaced`
([transport.md](transport.md), "Where the port is reached"). The app
therefore has no such extension, and a share is read on the share page
alone.

### The terminal

| Rule | Reason |
| --- | --- |
| SwiftTerm draws the 16 colours and the theme's colours as "The colours" gives them, and the 256-colour cube and grey ramp as xterm draws them (`ansi256PaletteStrategy` `.xterm`), as xterm.js does on the desktop and on Android. | SwiftTerm's own default derives the cube and the ramp from the theme's background and foreground, so one colour code would draw differently in the two themes and in the other two clients. |
| On iOS, SwiftTerm draws bold text in colours 0 to 6 in the bright colour, and `useBrightColors` stays on. This is the one place where the iOS terminal differs from "The colours". | With `useBrightColors` off, SwiftTerm draws every text colour above 7 eight places lower, the bright colours and the cube included. |
| A tap on the terminal opens the keyboard, and also brings back a keyboard iOS took away while the terminal kept the focus, as after a switch of keyboards with the globe key. One tap on empty space closes it: anywhere on the Terminals page outside the terminal and outside a control, such as the page's background, the cards' margins, the empty part of the tab strip and the status line's space beside its buttons. A tap on a control, a chip, a tab, a switch or a key, does what it does and leaves the keyboard as it is. Join's paste field, a share's login sheet and the local port dialog close the keyboard the same way; a system alert with a field, as for a new folder's name, keeps it until its buttons. When the keyboard goes, the Terminals page stays scrolled to its end, so the status line and the key row stay in view. | A tap beside what is being typed into is how a phone puts its keyboard away, and a terminal that holds the focus with no keyboard shown takes no typing. |
| With the keyboard shown, a switch of tabs keeps it shown, and the typing goes to the tab now shown. | A tab switch is no request to stop typing, and a keyboard taken down and put up again moves the whole page twice. |
| As the keyboard comes or goes and as the key row shows or hides, the terminal's card moves as one, in step with the keyboard's own slide: in every frame the terminal, the status line and the key row keep their order, and none is drawn over another. The app follows the slide frame by frame and lays the page out once per frame, with the Terminals page kept at its end; the terminal's new size goes to the hub once, when the slide ends. | A status line that moves later than the terminal sits over its text for a moment, and a shell told every size of a slide redraws for each. |

### The frame

| Rule | Reason |
| --- | --- |
| In the sidebar layout the sidebar's and the page header's backgrounds and dividers run to the screen's edges, under the camera housing and beside the home indicator. With the housing at the left, the sidebar's name box and entries start at the edge of the safe area iOS gives, with no space added to it; with the housing at the right, where iOS insets the left edge as much, they start 8 points from the screen's edge. The page and the header keep the safe area on the right. Remote desktops' icon in both bars is a monitor's outline with an empty screen, as the other icons are outlines. | A strip of another colour beside the housing reads as a gap, the safe area already clears the housing and the rounded corners, and a blank as wide as a housing that is not there is a gap too. |

### The remote desktop viewer

| Rule | Reason |
| --- | --- |
| The RustDesk core, RustDesk 1.4.9 with the patch the Android core has, is a static library linked into a device build alone. A Simulator build carries no core, and its viewer stops at once with `rdp_core_missing`. | RustDesk publishes no library for an app without Flutter, and the unit tests on the Simulator need no core. |
| **Connect** reads `{password}` with the `service` frame and makes the viewer's forward, a forward of the app's own as the share page's is: a listener on `127.0.0.1` at a port the system picks, each accepted connection a `connect` stream naming the entry, accepting nothing while the hub has no channel, in no local port table, and ended with the viewer. The core dials `127.0.0.1:<port>`. One viewer is open at a time. | Only the core dials the port, so no person needs its number to stay put, and the share page and the viewer hold a forward the one way. |
| The space above the keyboard and the key bar ends at the key bar's top edge while the key bar shows, and at the keyboard's top edge while the keyboard alone does. A keyboard iOS floats over the picture, as on an iPad, takes no space, and only the key bar does. | The key bar sits on a docked keyboard, or above the home indicator with the keyboard down, and a floating keyboard covers no strip of the screen's bottom. |
| **Configure** offers Auto, VP8, VP9 and AV1, and no H264 or H265. | RustDesk decodes H264 and H265 in software on iOS, so they bring no hardware decoder to choose. |
| The viewer's text input keeps what the keyboard marks, such as a pinyin composition, and sends only what the keyboard commits. | UIKit's marked text is the composition the phone rules send nowhere. |
| **Paste** on the key bar is the system's paste control. | iOS 16 reads the clipboard for that control without asking the person, and asks on every read the app makes on its own. |

### In the background

| Rule | Reason |
| --- | --- |
| While the app is on the screen, its channels, its forwards and its share connections run in the app. | iOS runs an app's code while the app is in front. |
| When the app leaves the screen, it starts a background task (`beginBackgroundTask`) and keeps every connection for the time iOS gives the task, about 30 s on iOS 16. Before that time ends, the app closes every channel and every share connection, stops every forward's listener, and ends the task. | A frozen session answers no keepalive, and the hub holds it until the keepalive times out, up to a minute; a closed one ends its streams at once. iOS takes back the listening sockets of a suspended app. |
| A channel closed this way has the effect of any dropped channel: a plain terminal session ends, and a persistent or shared one stays, its tab attaching again on return ("The session list"). | The machine keeps the sessions the person asked it to keep. |
| Returning to the foreground reconnects every hub at once, with no backoff, and every forward that listened before listens again on its port. An in-app browser whose page iOS ended in the background loads it again. | The person is looking; a wait they can see is a fault. |
| A transfer of the share page that the close cut, the running one and every waiting one, shows `share_interrupted` on its row, with **Retry**. On the return the open share's forward listens again, the app logs in to the share again and reads the folder again. **Retry** on an upload deletes the part the cut write left, then writes the file again under the same name. | A transfer cannot outlive the connection iOS takes back, and the person decides whether it starts again. |
| An open viewer stops drawing when the app leaves the screen and keeps its session; on the return the core asks the machine for a fresh keyframe. | iOS shows no picture of an app off the screen, and a fresh keyframe draws the whole picture at once instead of waiting for the next one. |
| When the background time ends, the viewer closes and its forward ends with every other connection, and the return opens no viewer. | The channel the session runs through closes then, and a session opened again unasked takes the remote screen without a press of **Connect**. |
| There is no notification line and no setting for this. | iOS keeps an app running in the background only for a few kinds of work, such as playing audio, navigation and calls, and this app does none of them. |

### The About card

| Rule | Reason |
| --- | --- |
| **This machine** on the About card shows the device name iOS gives the app, which on iOS 16 and newer is the model, such as `iPhone`. | iOS gives the name the person set only to an app holding an entitlement Apple grants on request. |
| The **Carried** group on the About card lists SwiftTerm, the MIT-licensed terminal view the Terminals page draws with, then AMSMB2 and libsmb2, the LGPL-2.1 SMB client of the share page, each with its version and its **Source** link, then RustDesk 1.4.9, the AGPL-3.0 core of the remote desktop viewer, with its **Source** and **Patch** links as on Android. | A library the app contains is credited where the app's own version is. |

### The pickers

| Rule | Reason |
| --- | --- |
| The **Language** and **Theme** pickers of the Settings page, the **Codec** and **Quality** pickers of **Configure**, and the user name picker of a share's login sheet are rows: the picker's name at the left, and at the right the chosen value in the same text size, in the accent, with the system's up-and-down chevrons. A press opens the system's menu of the choices, the chosen one checked. | The system's menu is the dropdown iOS shows in its own settings, and a value drawn larger than its name reads as a heading. |

## An interaction this page does not cover

A control, a state or a gesture that none of the tables above name is not
invented in one client. It is written here first, for all three, and built
after it is written.
