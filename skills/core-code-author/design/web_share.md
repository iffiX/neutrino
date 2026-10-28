# The Web share page

The Web share page is the static page a Web share link opens: plain
JavaScript in `share_page/`, which connects a browser to the hub through
the guest path and shows the one shared app in the whole window. A visitor
installs nothing, and sees nothing of Neutrino but a loading screen and,
when something is wrong, one of three refusal screens. The guest path's
bytes, the link's form and its address are in
[transport.md](transport.md), "The guest path" and "The links"; the panel's
side of a share is in [protocol.md](protocol.md), "Web shares", and
[ui_behavior.md](ui_behavior.md), "The Clients page".

## The files and the sites

| File | Holds |
| --- | --- |
| `share_page/index.html` | the shell page: the screen and the app's frame |
| `share_page/shell.js` | the connection: the session description, the data channel, the open record, a yamux client, the record layer, the control stream, an HTTP/1.1 client over `connect` streams, the cookie jar, the WebSocket bridge, and the screens with their words |
| `share_page/sw.js` | the service worker: every request of the app's frame handed to its tab's shell |
| `share_page/shim.js` | the script put at the top of each HTML page of the app |

| Rule | Reason |
| --- | --- |
| The page is plain JavaScript with no build step and no library, and no crypto runs in it: DTLS is the browser's. | It loads at once: the four files measured 53.2 KB, 14.8 KB compressed, where the member path built for WebAssembly measured 1.7 MB compressed ([transport.md](transport.md), "The guest path"). |
| The page is served at `/__neutrino/` of its site, and the site sends `Service-Worker-Allowed: /` with `sw.js`, from a `_headers` file on Cloudflare Pages. | The service worker's scope is the whole origin, so the app runs at `/` as it does on its own machine. |
| A share names its site when it is made: one of `WEB_SHARE_SITES` in `modules/clients/constants.py`, the page on Cloudflare Pages first and on EdgeOne Pages second, or the `https://` address of a copy a person hosts. | A site runs nothing and stores nothing, so any static host serves the page, and a visitor in mainland China reaches the EdgeOne copy. |
| The share's facts are after `#` in the link, which a browser never sends to the site. | The site learns nothing of the hub, the share or the visitor. |

## The connection

The shell reads the link's facts, writes the hub's side of the session
description from them, and opens the data channel to the hub's one
candidate. It sends the open record with the share's ticket, runs a yamux
client inside the channel, opens the control stream, and sends `hello` with
the share's id from the `accept`. It then sends `service {request, id}` for
the share's entry ([protocol.md](protocol.md), "The service frame").

| Rule | Reason |
| --- | --- |
| Opening the page, the data channel and the admission together have 30 seconds. After 10 seconds of the loading screen, its line reads that the line is slow and the page is still connecting. Past the 30 seconds the page shows the hub-offline screen, tries again every 10 seconds with nothing on screen changing, and shows the app as soon as a try connects. | From an iPhone through a SakuraFrp tunnel, at about 330 ms round trip, a connection took 0.2 to 4 seconds and at times over 15. The changed line shows the visitor that the page is still working, and a hub that comes back is taken at once. |
| While the app is in use, the shell sends a `ping` frame every 3 seconds, and counts the channel as dropped when no `pong` comes within 6. | The browser's own consent checks take 15 to 30 seconds to give up on a dead connection. |
| A dropped channel is opened again with nothing on screen changing for about 10 seconds, the app's frame kept; past them the page shows the hub-offline screen, tries again every 10 seconds, and shows the app again when a try connects. | A short drop, a phone changing networks among them, passes unseen. |
| The machine-offline screen shows as soon as a `service` reply or a `connect` close carries `agent_offline`, or `service_unknown` for the share's entry. The page keeps its channel, sends the `service` frame again every 10 seconds, and shows the app when a reply carries no code. | The hub is up, so the page keeps the channel it has, and the app shows again as soon as its machine or the app itself is back. |
| Any other code on a `service` reply or a `connect` close, `control_unavailable` among them, shows the hub-offline screen, and the page tries again as for a dropped channel. | A code the visitor can do nothing about reads as the hub being out of reach for now. |
| A refusal of the share, `share_unknown` or a refused `hello`, and a link whose facts do not read, show the link screen, and the page tries nothing more. | A revoked or expired share does not come back. |

## The app in the page

The app runs in a frame that fills the window, at `/` of the page's origin.
The service worker takes every request the frame makes and hands it to the
shell of the frame's own tab, which sends it to the share's entry as HTTP/1.1
over a `connect` stream and gives the response back.

| Rule | Reason |
| --- | --- |
| The shell keeps up to 8 `connect` streams to the entry open and sends each request on a free one. | A stream costs a round trip to open, and an app's first page makes dozens of requests. |
| Every request goes with `Host` `127.0.0.1`, and its `Origin`, where it has one, rewritten to the same host. | The forwarder in front of a module's page accepts no other host, and checks that the origin is its own ([agent/module_template.md](agent/module_template.md), "The run"). |
| A response's absolute `Location` is rewritten to a path, and the shell follows no redirect itself. | The app's addresses name its own machine, and the browser keeps the visitor on the page's origin. |
| The app's cookies are kept in the shell's memory, one jar per tab: a response's `Set-Cookie` goes into it and never to the browser, and each request carries what the jar holds. | Two shares in two tabs keep apart, and nothing of the app's login outlives the tab. |
| The worker decodes a compressed body and streams a response as it arrives; a download is a response with `Content-Disposition`, which the browser saves as usual. | A large file and a server-sent stream behave as they do on the app's own machine. |
| The worker finds a request's tab by a tag the shell puts on the frame's first navigation. | A frame's first request can arrive with no client id, and a guess sends one share's requests to another tab's hub. |
| The worker removes `Content-Security-Policy` and `X-Frame-Options` from the app's responses. | The shim runs inside the app's pages, and the app runs in a frame. |
| A navigation of the whole tab to the page's origin, a link the app opens in a new tab among them, is answered with the shell, which loads that path in its frame. | A new tab opened by the app comes up as the app, with the share's facts a new tab copies from its opener's `sessionStorage`. |
| The shell signs the visitor in before it loads the frame: a `{token}` in the `service` reply is spent with `GET /?tkn=<token>`, and the app opens where the forwarder's redirect points, or at the link's `app.path`. | The visitor never sees the app's login for a share whose entry takes a guest account or the account the app runs as ([agent/module_install.md](agent/module_install.md), "The manifest"); an entry with no token shows the app's own login page. |
| The shell mirrors the frame's title and icon onto the tab. | The tab reads as the app. |

The shim, put at the top of each HTML page of the app, replaces three things
of the browser's:

| It replaces | With |
| --- | --- |
| `document.cookie` | a property that reads and writes the tab's jar, its HttpOnly cookies left out |
| `WebSocket` | a socket the shell carries over a `connect` stream to the entry, framed by RFC 6455 in JavaScript |
| `navigator.serviceWorker.register` | a call that does nothing; the worker also refuses every request whose destination is a service worker |

## What the page keeps

| Rule | Reason |
| --- | --- |
| The link's facts stay after `#` in the address, and the shell keeps a copy in `sessionStorage`, which is per tab. The page writes nothing to `localStorage`, IndexedDB or a cookie of its own. | A refresh and a bookmark keep working, and a closed tab leaves nothing behind. |
| The page shows nothing of the share beyond the screens below: no hub name, no machine, no link. | A visitor sees the app the owner shared and nothing else. |

## The screens

Four screens fill the window: loading before the app shows, and three
refusals that cover the app's frame when the app cannot be reached, the
frame kept under them. Each is centred on the page background: the mark the
panel shows while it checks a session, with one or two lines of text under
it. Their words are in [ui_text.md](ui_text.md), "The Web share
page's words", Chinese when the browser's language starts with `zh` and
English otherwise.

| Screen | Shown | Under the mark |
| --- | --- | --- |
| Loading | from the page's start until the app's first page | the mark breathes; one line, `Opening <app title>…`, in 12 px monospace, muted, which after 10 seconds reads `The line is slow, still connecting…` |
| The link no longer works | the share is refused, or the link's facts do not read | the mark still; the sentence in 14 px regular text in the main text colour, and a second line in 12 px muted text |
| The hub is offline | no channel and admission within 30 seconds of the page's start, or a dropped one not back within about 10 | the same |
| The machine is offline | `agent_offline` or `service_unknown` for the share's entry | the same |

| Rule | Reason |
| --- | --- |
| The mark is the panel's: a 46 px rounded square with an accent border and the accent's wash, the N logo inside as an inline SVG. While loading it breathes as the panel's does, `splash_breathe`, 2.2 seconds. | A visitor who opens the panel later meets the same mark, and the page loads no image. |
| The colours are the panel's dark and light tokens, `--color-bg`, `--color-text`, `--color-text-muted`, `--color-accent` and its wash, with their values, chosen by the system's setting. | The page has no Settings of its own, and reads as the panel does. |
| A screen shows no mascot, no button and no link. | A visitor has nothing to do on a refusal but ask the person who shared the link. |
