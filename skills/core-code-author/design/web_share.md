# The Web share page

The Web share page is the static page a Web share link opens: plain
JavaScript in `share_page/`, which connects a browser to the hub through
the guest path and shows the one shared app in the whole window. A visitor
installs nothing, and sees nothing of Neutrino but a loading screen and,
when something is wrong, one of four refusal screens. The site's own
address, opened with no link, shows an introduction. The guest path's
bytes, the link's form and its address are in
[transport.md](transport.md), "The guest path" and "The links"; the panel's
side of a share is in [protocol.md](protocol.md), "Web shares", and
[ui_behavior.md](ui_behavior.md), "The Clients page".

## The files and the sites

| File | Holds |
| --- | --- |
| `share_page/index.html` | the shell page: the screen and the app's frame |
| `share_page/shell.js` | the connection: the session description, the data channel, the open record, a yamux client, the record layer, the control stream, an HTTP/1.1 client over `connect` streams, the cookie jar, the WebSocket bridge, and the screens with their words |
| `share_page/sw.js` | the service worker: every request of the app's frame handed to its tab's shell, and the cache of the app's files |
| `share_page/shim.js` | the script put at the top of each HTML page of the app |

| Rule | Reason |
| --- | --- |
| The page is plain JavaScript with no build step and no library, and no crypto runs in it: DTLS is the browser's. | It loads at once: the four files measured 53.2 KB, 14.8 KB compressed, where the member path built for WebAssembly measured 1.7 MB compressed ([transport.md](transport.md), "The guest path"). |
| The page is served at `/__neutrino/` of its site, and the site sends `Service-Worker-Allowed: /` with `sw.js`, from a `_headers` file on Cloudflare Pages. | The service worker's scope is the whole origin, so the app runs at `/` as it does on its own machine. |
| A share names its site when it is made: `https://share.neutrinohub.net`, the one site of `WEB_SHARE_SITES` in `modules/clients/constants.py`, or the `https://` address of a copy a person hosts. Cloudflare Pages serves the site. Its DNS stays at DNSPod, where a later record for mainland China points at an EdgeOne Pages copy of the same files. | A site runs nothing and stores nothing, so any static host serves the page. A link names one address, and the visitor's DNS answer picks the copy. |
| Publishing a release deploys the site. The `share_page` job of `publish.yml` builds the page from the tag with `packaging/build/build_share_page.py`. It deploys the tree to the Cloudflare Pages project `neutrinohub-share` as the production deployment of its branch `main` ([../agent_work_rule/release.md](../agent_work_rule/release.md), "The release itself"). A pre-release deploys nothing. | The site serves the page of the latest release, built from the same tag as its hub. The links of every released hub open the one site, so a pre-release leaves it unchanged. |
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
| Opening the page, the data channel and the admission together have 30 seconds. After 10 seconds of the loading screen, its line reads that the line is slow and the page is still connecting, or still loading once the session is admitted ("The screens"). Past the 30 seconds the page shows the hub-offline screen, tries again every 10 seconds with nothing on screen changing, and shows the app as soon as a try connects. | From an iPhone through a SakuraFrp tunnel, at about 330 ms round trip, a connection took 0.2 to 4 seconds and at times over 15. The changed line shows the visitor that the page is still working, and a hub that comes back is taken at once. |
| While the app is in use, the shell sends a `ping` frame every 3 seconds, and any byte the channel brings counts as the line alive. The shell counts the channel as dropped only when a `ping` has no `pong` yet and nothing at all has arrived for 15 seconds. | On the same iPhone line, at 100 to 150 KB/s, a ping's answer took 1 to 25 seconds while a page loaded, behind the page's own bytes. The browser's own consent checks take 15 to 30 seconds to give up on a dead connection. |
| A dropped channel is opened again with nothing on screen changing for about 10 seconds, the app's frame kept; past them the page shows the hub-offline screen, tries again every 10 seconds, and shows the app again when a try connects. | A short drop, a phone changing networks among them, passes unseen. |
| A page the shell loads into the frame, first or again, is broken when a request of it fails before its load event. When the page shows the app again, after a dropped channel or the app-unavailable screen, it loads a broken page again. | A drop while the page loads leaves a partial page whose scripts failed, and that page makes no further requests. On an iPhone through SakuraFrp, code-server's frame stayed blank for 5 minutes after the page came back. |
| The app-unavailable screen shows as soon as a `service` reply or a `connect` close carries `agent_offline`, or `service_unknown` for the share's entry, and as soon as a `connect` close carries `connect_failed` or `port_not_published`, the shared app itself being down. The page keeps its channel, sends the `service` frame again every 10 seconds, and shows the app when a reply carries no code. After `connect_failed` or `port_not_published` it also opens a `connect` to the entry, and shows the app, its frame loaded again, only once the hub accepts that stream. | The hub is up, so the page keeps the channel it has, and the app shows again as soon as its machine or the app itself is back. A declared app that is down keeps its entry published, so a `service` reply alone does not tell that it is back, and a page of the app that failed while it was down is loaded afresh. |
| Whatever the code, when the page shows the app after the app-unavailable screen, it loads the frame again if the frame's last navigation failed. | A navigation that failed while the app was down leaves its failure in the frame after the app is back. In the lab a frame showed a stopped Ayakaleaf's error for 4 minutes after the app returned, until it was loaded again by hand. |
| Any other code on a `service` reply or a `connect` close, `control_unavailable` among them, shows the hub-offline screen, and the page tries again as for a dropped channel. | A code the visitor can do nothing about reads as the hub being out of reach for now. |
| A refusal of the share, `share_unknown` or a refused `hello`, shows the link screen, and the page tries nothing more. A link whose facts do not read shows the incomplete-link screen, and an address with no `#` part shows the introduction. In both cases the page opens no connection. A share that ended before the page opened meets the guest door's silence, since its ufrag is no longer live, so that page shows the hub-offline screen and tries again. | A revoked or expired share does not come back, and a restore brings back no share. The hub keeps nothing of an ended share, so nothing answers its old link. A link cut short when it was copied works once it is copied whole, and the site's own address names no share. |

## The app in the page

The app runs in a frame that fills the window, at `/` of the page's origin.
The service worker takes every request the frame makes and hands it to the
shell of the frame's own tab, which sends it to the share's entry as HTTP/1.1
over a `connect` stream and gives the response back.

| Rule | Reason |
| --- | --- |
| The shell keeps up to 8 `connect` streams to the entry open, or 32 while the line is fast, and sends each request on a free one. | A stream costs a round trip to open, and an app's first page makes dozens of requests. More streams wait less on the app: on a fast line, a page of 100 files that each waited 50 ms on the app loaded in 0.70 seconds with 8 streams and 0.27 with 32. On a slow line more streams share the line among more responses, and a font waits behind all of them: at 128 KB/s, a font asked for with 30 responses of 200 KB arrived at 20.7 seconds with 8 streams, 34.7 with 16 and 59.2 with 32. |
| The shell measures the line in windows of 250 ms. A window counts when at least 2 requests were open, sent and not yet answered in full, through the whole window, and its rate is the bytes the channel brought in it. One counted window at 1 MB/s or more raises the count to 32, and two counted windows in a row below 1 MB/s lower it to 8. Each session starts at 8. A lower count closes no stream: a stream over the count closes when its response ends. | 8 on a fast line costs about 0.4 seconds of a page, where 32 on a slow line costs the font 38, so an unknown line gets 8. With fewer than 2 requests open, the bytes measure the app or the browser and not the line. A response under 64 KB reaches the page as one message, so how long a body takes to arrive measures nothing. A session after a drop may be on a new line, a phone's new network among them. |
| The worker passes each request's destination to the shell. A request whose destination is `font` or `style` waits ahead of every other request waiting for a stream, and the waiting requests of each kind go in the order sent. | A page draws its text and icons only once its style sheets and fonts arrive, and a font is asked for after the style sheet that names it, behind the app's earlier requests. Through a slow line in Safari, code-server's icons stayed empty boxes for about 2 minutes. Measured at 128 KB/s with 8 streams, a font asked for with 30 responses of 200 KB arrived at 20.7 seconds in Chrome and 20.8 in Firefox, where in the order sent it arrived at 59.1 and at 38 to 44. |
| Every request goes with `Host` `127.0.0.1`, and its `Origin`, where it has one, rewritten to the same host. | The forwarder in front of a module's page accepts no other host, and checks that the origin is its own ([agent/module_template.md](agent/module_template.md), "The run"). |
| A response's absolute `Location` is rewritten to a path. A navigation gets the 3xx with that `Location`, and the browser follows it. For every other request the worker follows a 3xx itself, by the Fetch standard's rules and at most 20 in a row, and returns the final response. The request keeps its own URL, since a worker cannot set a response's. | The app's addresses name its own machine, and the browser keeps the visitor on the page's origin. Safari 16.6 fails a script's `fetch` with `Load failed` when a service worker returns a 3xx to it. |
| The app's cookies are kept in the shell's memory, one jar per tab: a response's `Set-Cookie` goes into it and never to the browser, and each request carries what the jar holds. | Two shares in two tabs keep apart, and nothing of the app's login outlives the tab. |
| The worker decodes a compressed body and streams a response as it arrives; a download is a response with `Content-Disposition`, which the browser saves as usual. | A large file and a server-sent stream behave as they do on the app's own machine. |
| While the shell serves a request of the worker, from the request until its body ends, it sends the worker a message every 10 seconds. | Firefox stops a worker 30 seconds after its last event, even while the worker streams a response, and the page reads that response as complete where it stopped. Measured at 128 KB/s, a 6 MB response ended after 4.2 MB. Each message is a new event and restarts the 30 seconds; a fetch event that waits for its body's end keeps the worker only about 5 minutes longer. |
| The worker finds a request's tab by a tag the shell puts on the frame's first navigation, and records the tab of each page it routes. The shim announces each page's tab to the worker and adds it to a form's action. A request with no tag goes to the one shell while one is open. With several open, an untagged navigation gets a page that loads itself again with its tab, and an untagged form `POST` gets a 502. | A frame's first request can arrive with no client id, and a guess sends one share's requests to another tab's hub. |
| The worker removes `Content-Security-Policy` and `X-Frame-Options` from the app's responses. | The shim runs inside the app's pages, and the app runs in a frame. |
| A navigation of the whole tab to the page's origin, a link the app opens in a new tab among them, is answered with the shell, which loads that path in its frame. The shim adds the opener's tab to a same-origin address the app opens in a new tab, and the new shell asks the opener's shell for the share's facts through the worker. | A new tab opened by the app comes up as the app. A link opened with `target=_blank` has no opener, so the browser copies no `sessionStorage` into the new tab. |
| The shell signs the visitor in before it loads the frame: a `{token}` in the `service` reply is spent with `GET /?tkn=<token>`, and the app opens where the forwarder's redirect points, or at the link's `app.path`. | The visitor never sees the app's login for a share whose entry takes a guest account or the account the app runs as ([agent/module_install.md](agent/module_install.md), "The manifest"); an entry with no token shows the app's own login page. |
| The shell mirrors the frame's title and icon onto the tab. | The tab reads as the app. |

The shim, put at the top of each HTML page of the app, replaces three things
of the browser's:

| It replaces | With |
| --- | --- |
| `document.cookie` | a property that reads and writes the tab's jar, its HttpOnly cookies left out |
| `WebSocket` | a socket the shell carries over a `connect` stream to the entry, framed by RFC 6455 in JavaScript |
| `navigator.serviceWorker.register` | a call that does nothing; the worker also refuses every request whose destination is a service worker |

## The cache of the app's files

The worker keeps the app's static files in the browser's Cache Storage, and
a later open of the same app loads them from there. The cache holds the
app's public code alone, its scripts, styles, fonts and images, and no data,
cookie or secret of the app or of the visitor.

| Rule | Reason |
| --- | --- |
| The worker keeps the response to a GET when it is a 200 and the request's destination is `script`, `style`, `font` or `image`, or the response's `Content-Type` names a script, a style sheet, a font or an image. | These are the app's code and artwork, the same for every visitor. |
| Nothing else is kept: no document, by the destination `document` or `iframe` or a `Content-Type` of `text/html`, no API answer, and no response with `Set-Cookie` or with `no-store` or `private` in its `Cache-Control`. A static file sent with the jar's cookies is kept unless its `Cache-Control` forbids it. | A page, an API answer and a response that sets a cookie belong to one visitor at one moment. A script fetched with the app's cookie is still the app's public code. |
| There is one cache for each hub and app, named from the link's `hub.fp` and `app.entry`. | Every share a site serves has the site's one origin and so one Cache Storage, and a file kept for one hub's app never answers a request of another's. |
| A later load is answered from the cache first. The worker then sends the request again through the shell with the kept `ETag` or `Last-Modified` as its condition: a `304` keeps the entry, a response that can be kept replaces it, and any other removes it. A kept response with neither validator is sent again only once its `max-age` has passed, or at every load when it names none or names `no-cache`. | A second open reads the app's files from the browser, and a changed app reaches the visitor at the next open. A request sent again with no validator moves the whole file. code-server's 10 MB of scripts carry `max-age` and no validator, and through a line of 100 KB/s their second open took as long as the first. |
| A cache holds at most 50 MB. Before a response that takes it past that is stored, the worker removes the responses stored earliest until it fits; a response larger than 50 MB is never kept. | The browser keeps a bounded amount of each app. |
| When the page shows the link screen, it deletes the cache of the link's hub and app. | A share that has ended leaves nothing of its app in the browser. |

## What the page keeps

| Rule | Reason |
| --- | --- |
| The link's facts stay after `#` in the address, and the shell keeps a copy in `sessionStorage`, which is per tab. The page writes nothing to `localStorage`, IndexedDB or a cookie of its own, and the cache of the app's files is the one thing of the share it leaves in the browser after its tab closes. | A refresh and a bookmark keep working, and a closed tab leaves the app's public code behind and nothing else. |
| The page shows nothing of the share beyond the screens below: no hub name, no machine, no link. | A visitor sees the app the owner shared and nothing else. |

## The screens

Six screens fill the window: loading before the app shows, the
introduction, and four refusals. A refusal covers the app's frame when the
app cannot be reached, the frame kept under it. Each screen is centred on
the page background: the mark the panel shows while it checks a session,
with one or two lines of text under it. Their words are in
[ui_text.md](ui_text.md), "The Web share page's words", Chinese when the
browser's language starts with `zh` and English otherwise.

| Screen | Shown | Under the mark |
| --- | --- | --- |
| Loading | from the page's start until the app's first page | the mark breathes; one line, `Opening <app title>…`, in 12 px monospace, muted, which after 10 seconds reads `The line is slow, still connecting…` before the admission and `The line is slow, still loading…` after it |
| The introduction | the site itself is opened: the address has no `#` part, and the tab has neither kept facts nor an opener | the mark still; the first line in 14 px regular text in the main text colour, and a second line in 12 px muted text |
| The link is incomplete | the address has a `#` part whose facts do not read, a link cut short when it was copied among them | the same |
| The link no longer works | the share is refused, the page is opened inside another page's frame, or a tab the app opened gets no facts from its opener | the same |
| The hub is offline | no channel and admission within 30 seconds of the page's start, a link of an ended share among them, or a dropped one not back within about 10 | the same |
| The app is unavailable | `agent_offline` or `service_unknown` for the share's entry, or `connect_failed` or `port_not_published` from the shared app | the same |

| Rule | Reason |
| --- | --- |
| The mark is the panel's: a 46 px rounded square with an accent border and the accent's wash, the N logo inside as an inline SVG. While loading it breathes as the panel's does, `splash_breathe`, 2.2 seconds. | A visitor who opens the panel later meets the same mark, and the page loads no image. |
| The colours are the panel's dark and light tokens, `--color-bg`, `--color-text`, `--color-text-muted`, `--color-accent` and its wash, with their values, chosen by the system's setting. | The page has no Settings of its own, and reads as the panel does. |
| A screen shows no mascot, no button and no link. | A visitor has nothing to do on a refusal but ask the person who shared the link, and nothing to do on the introduction but open the link they were sent. |
| From 10 seconds after the page's start until the app's first page shows, the loading line reads that the line is slow. It names the connection until the session is admitted and the app's load after the admission, and a line that reads `still connecting` changes to `still loading` at the admission. | In Safari on an iPhone through SakuraFrp, every page was admitted within 6 seconds. code-server's first page then showed at 50 to 63 seconds and Ayakaleaf's at 37 to 46, under a line that read `Opening`. |
| While a screen shows, the tab's title is the screen's first line, the slow line among them. The introduction's tab shows the N icon of `images/icons/neutrino.png`, drawn as an inline SVG, and every other screen's tab has no icon. The app's title and icon come back with the app. | The tab reads as what the window shows, and a share that ended leaves nothing of its app on the tab. The introduction belongs to no share, and its tab reads as Neutrino. |
| The app-unavailable screen has one wording for a machine that is offline and for a shared app that is down. | The visitor waits in both cases, and the page shows the app once it is back. |
