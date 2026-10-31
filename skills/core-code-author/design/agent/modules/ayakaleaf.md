# The Ayakaleaf module

The `ayakaleaf` module runs Ayakaleaf (AGPL-3.0), Overleaf Community Edition
with the Server Pro features its publisher, `ayaka-notes`, adds, as three
containers on the Containers module: the app, MongoDB (SSPL-1.0) and Redis
(RSALv2 or SSPL-1.0). A person writes and compiles LaTeX papers in its page.
The module's software is container images, installed by the `container`
method ([module_install.md](../module_install.md), "From container images").

`agent/neutrino_agent/modules/ayakaleaf/` holds `config.py`, `constants.py`
and `hooks.py`: the steps of the first start, the forwarder's login and the
health read, which the `container` runner calls. The configuration is
`{secret, password, cookie_name, local_name, guests}`: the token secret, the
administrator's password, the name of the app's session cookie ("The
page"), the app's local name, which the forwarder checks the `Host`
against ([../module_template.md](../module_template.md), "The run"), and the
guest accounts of the live Web shares of the app ("The guest account"). The hub
generates the secret, the password, and the app's session and invitation
secrets the first time the module is installed, and seals them in
`config/devices/<id>/ayakaleaf.json`, beside the module's gateway key and the
model the tab names ("The model"). The module runs wherever Containers runs
([containers.md](containers.md)).

## The three images

| Image | Tested version | Index digest | Sources |
| --- | --- | --- | --- |
| app | 6.3.2 | `sha256:5f84c7f2d0230dd558130ca2901f603d4e0bfe021054879efea1b7fece2f4f1c` | `ghcr.io/ayaka-notes/overleaf-pro`, `ghcr.nju.edu.cn/ayaka-notes/overleaf-pro`, `ghcr.m.daocloud.io/ayaka-notes/overleaf-pro` |
| mongo | 8.0 | `sha256:8e7d23aa641b0ec6c86418866d5d18d74d5abf89061bc5db7bc4b80929021ef6` | `docker.io/library/mongo`, which Podman reaches through the docker.io mirrors the Containers module names |
| redis | 7.4 | `sha256:bd28fff4b665fdf1b73e8b5b73ec05d2f858f4fa3c8ea0d7c9bc09f7f6bf7039` | `docker.io/library/redis`, the same way |

Each index covers amd64 and arm64. The manifest's four `container` entries,
`linux`, `windows-amd64`, `darwin-arm64` and `darwin-amd64`, name the same
three artifacts and `source_sets: ["ctan"]` ("The first start"), and its top
level names `is_data_forward_only: true`.

| Rule | Reason |
| --- | --- |
| The module's version is the app's. The entries' `releases` name one `oci` feed, `{kind: oci, repository: ayaka-notes/overleaf-pro, tag: "{version}", sources: ["https://ghcr.io"]}`, The tested version installs the digests the manifest names, and any other version installs the app digest the registry gives its tag ([module_install.md](../module_install.md), "Module versions"). | The publisher tags every release of the app image with its version, which follows upstream Overleaf's numbers, and pushes `6.3.2-amd64`, `6.3.2-arm64` and `latest` beside `6.3.2`; only the dotted tag is a version. |
| MongoDB and Redis keep their own digests for every version of the app. | MongoDB opens the data files of its previous major version alone, so a database moves forward one major at a time, and the image stays the one the app was tested with. |
| The manifest names `is_data_forward_only`, so the machine page asks before it installs an older version. | The app runs its migrations at its first start on a new version. In the lab 6.2.2 started on the data of 6.3.2 with "Nothing to migrate" and listed the project, and the publisher supports no downgrade. |
| A tested digest can disappear from `ghcr.io`, and the pull then comes from a mirror that still holds it, or ends `download_failed {file, sources}`. | The publisher's release workflow deletes every untagged image version at once, and 6.3.0 was built again under the same tag, which left the first digest untagged. |

## The containers

The three containers join the network `neutrino_ayakaleaf` and have the
label `neutrino.module=ayakaleaf`, as every hub container does
([containers.md](containers.md), "Hub containers"). The app reaches the other
two by their names.

| Container | Image | Command | Ports | `after` | `stop_timeout_s` |
| --- | --- | --- | --- | --- | --- |
| `neutrino_ayakaleaf_mongo` | mongo | `--replSet overleaf` | none | none | 10 |
| `neutrino_ayakaleaf_redis` | redis | `redis-server --appendonly yes` | none | none | 10 |
| `neutrino_ayakaleaf` | app | the image's own | the app's 80, published on `127.0.0.1` at a port the agent picks ("The page") | the other two | 60 |

| Volume | Holds | Mounted in |
| --- | --- | --- |
| `neutrino_ayakaleaf_data` | data: the projects and their files, compile output, history and templates | the app, at `/var/lib/overleaf` |
| `neutrino_ayakaleaf_mongo` | data: the users, the projects and the documents | mongo, at `/data/db` |
| `neutrino_ayakaleaf_redis` | data: the edits the app has not yet flushed, in Redis's append-only file | redis, at `/data` |
| `neutrino_ayakaleaf_texlive` | cache: the app image's TeX Live, which Podman copies into the volume at its first mount, and the collections the first start adds ("TeX") | the app, at `/usr/local/texlive` |

The mongo image's own anonymous volume at `/data/configdb` goes with the
container, since every unit runs `podman run --rm`.

| Variable | Value |
| --- | --- |
| `OVERLEAF_MONGO_URL` | `mongodb://neutrino_ayakaleaf_mongo/sharelatex` |
| `OVERLEAF_REDIS_HOST`, `REDIS_HOST` | `neutrino_ayakaleaf_redis` |
| `REDIS_PORT` | `6379` |
| `V1_HISTORY_URL` | `http://127.0.0.1:3100/api`, the history service inside the app container |
| `GIT_BRIDGE_ENABLED` | `false` |
| `EMAIL_CONFIRMATION_DISABLED` | `true` |
| `DOCS_MCP_URL` | empty ("The model") |
| `OVERLEAF_SESSION_SECRET`, `OVERLEAF_INVITE_TOKEN_SECRET` | the module's session and invitation secrets |
| `COOKIE_NAME` | `ayakaleaf_sid_` and the first 12 characters of the device id ("The page") |
| `NEUTRINO_GATEWAY_URL`, `NEUTRINO_GATEWAY_KEY` | the gateway's address and the module's key ([containers.md](containers.md), "Reaching the machine") |
| `AI_ENABLED`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL` | `true`, `NEUTRINO_GATEWAY_URL` with `/v1` after it, the module's key, and the model ("The model") |

These are the app container's; mongo and redis have no variables. Each
container's environment is in its root-only environment file, never in its
unit or on a command line ([containers.md](containers.md), "Linux").

| Rule | Reason |
| --- | --- |
| The app's hub container names mongo and redis in `after`, so its unit starts after theirs and stops before them. | The app's start waits for the database, and its stop flushes the open edits into MongoDB and Redis while both still run. |
| The app's `stop_timeout_s` is 60 ([containers.md](containers.md), "Hub containers"). | A graceful stop took 19.4 seconds in the lab: the app closes the site for about 16 seconds, then flushes the document updater and the project history. Podman's 10 seconds killed it before the flush, so every stop ended unclean and only Redis's append-only file kept the edits. The publisher's own installer gives 60 seconds. |
| The app's hub container names `success_exit_codes` `[2]` ([containers.md](containers.md), "Hub containers"). | The app's init exits 2 on SIGTERM once the flush has ended: in the lab a clean stop of 20.3 seconds left the unit `failed` with `status=2`. |
| The module binds no host folder and mounts no engine socket, and every compile runs inside the app container. | A compile in a container of its own needs the root `podman.sock` inside the app, and each compile then shows as a container a person started by hand. |
| The module reads `running` while the three containers run and the app's `GET /status` returns 200 at its published port. | `/status` answers with no login, once the app has started. |
| The module's journal is the three containers' journals, the app's first. | Each container's journal is read as Containers reads any container's journal. |
| An uninstall removes the three containers, the network and the four volumes, the papers and projects among them, and the images no other container uses. The manifest's `uninstall_data` says so, and the dialog shows its line in red ([../../ui_behavior.md](../../ui_behavior.md), "The machine page"). | A container module is removed whole, and its data is in its volumes ([module_install.md](../module_install.md), "From container images"). |

## The first start

The hooks run three steps once per install, after the containers start,
and keep each step done in the module's record, root-only under the state
root:

| Step | What the agent runs | When |
| --- | --- | --- |
| The replica set | `podman exec neutrino_ayakaleaf_mongo mongosh --quiet --eval <initiate>`, `<initiate>` being `db.isMaster().primary \|\| rs.initiate({_id: "overleaf", members: [{_id: 0, host: "neutrino_ayakaleaf_mongo:27017"}]})` | while mongo runs |
| The administrator | `GET /launchpad` at the app's published port, for the session cookie and the `ol-csrfToken` the page holds, then `POST /launchpad/register_admin` with that cookie and the JSON body `{_csrf, email, password}`, `email` the address the module's `constants.py` fixes and `password` the module's | once `/status` returns 200 |
| The Chinese TeX set | `podman exec neutrino_ayakaleaf tlmgr --repository <source>/systems/texlive/tlnet update --self`, then the same with `install collection-langchinese collection-xetex collection-latexrecommended collection-pictures` in place of `update --self`, then `podman exec neutrino_ayakaleaf kpsewhich ctex.sty xeCJK.sty pgfplots.sty`, `<source>` the fastest source of the `ctan` set, and the next source after one that fails ([module_install.md](../module_install.md), "Source sets") | after the administrator |

| Rule | Reason |
| --- | --- |
| A source fails the TeX step when `kpsewhich` misses one of the three files after `tlmgr` exited 0, with the detail `kpsewhich finds no <files>`. | A `podman exec tlmgr` ended by the agent's stop exited 0 on Debian 12 in the lab, and the step kept `tex` while `ctex.sty` and `xeCJK.sty` were missing. The basic scheme has none of the three, and each comes from another of the collections. |
| The TeX step updates `tlmgr` itself from the source before it installs from it. | `tlmgr` refuses a repository newer than itself: in the lab every `ctan` source ended `tlmgr itself needs to be updated` on 6.3.1, whose `tlmgr` dated from 2026-10-12, and `update --self` took 3 seconds. Each image's `tlmgr` ages the same way. |
| The app's unit starts the app again until the replica set exists. | The app's start check polls for a primary for 60 seconds and then exits, and its unit's `Restart=` starts it again. In the lab `rs.initiate` took 0.4 seconds, and the next start passed. |
| From the install, and after a version change, the module reads `installing` until the three steps are done and `/status` returns 200. The module's task checks every 30 seconds meanwhile, and the steps `replica_set`, `wait_app`, `admin`, `tex` and `guests` are its steps ([agent.md](../../agent.md), "The steps"). | The app was ready 8 to 18 seconds after a start on Linux and 44 seconds after the first start on Windows, and the TeX set took 4 to 5 minutes. The page's `web` entry appears ("The page") once the editor compiles Chinese. |
| A step that fails ends the install `install_failed` with `ayakaleaf_setup_failed {step, detail}`, `step` being `replica_set`, `admin` or `tex`, and `detail` the tool's own last line. **Install** runs the steps the record does not hold. | The forwarder signs in as the administrator, and the editor compiles Chinese only with the set; a step done once is never repeated. |
| The administrator step fails `ayakaleaf_setup_failed {step: admin}` when `/launchpad` already sends the browser to `/login`. | An administrator the module did not make exists, so the module's password does not open the app. |

## A machine that joins another hub

A machine that runs Ayakaleaf and joins another hub keeps the module's
papers and data. The new hub imports none of the module's containers, and
they stop at its first apply of Containers. The module's install on the new
hub starts them again on the same volumes ([containers.md](containers.md),
"Hub containers"). The new hub generates the module's secrets and its
password at that install, as at every first install.

| Rule | Reason |
| --- | --- |
| The module's record keeps the password the app's administrator has. When the state names another password, the administrator step runs again: it signs in with the kept password and changes it with `POST /user/password/update` and the JSON body `{_csrf, currentPassword, newPassword1, newPassword2}`. The module reads `installing` until the step ends. | The volumes keep the administrator made with the earlier hub's password, and the forwarder signs in with the password the state names. |
| A change the app refuses fails the install `ayakaleaf_setup_failed {step: admin}`, and **Install** runs the step again. | The administrator's password was changed in the app, so the kept password does not open it. |
| The guests of the earlier hub's shares are deleted, as every guest the state no longer names is ("The guest account"). | Their shares ended with the earlier hub. |

## TeX

| Rule | Reason |
| --- | --- |
| The app image carries TeX Live 2026's basic scheme, 205 MB, with latexmk, XeTeX and the tools around them. An English article compiles with no network. | The kernel log showed no connection from the app while every outside connection was refused. |
| The TeX volume holds that tree, and the first start adds the collections `collection-langchinese`, `collection-xetex`, `collection-latexrecommended` and `collection-pictures` with `tlmgr`. | The basic scheme has no `ctexart.cls`, no `xeCJK.sty` and no `pgfplots.sty`. In the lab `tlmgr` installed the first three, about 230 packages, in 127 to 137 seconds, and the volume grew from 205 MB to 673 MB. `collection-pictures` added 326 packages, a 26 MB download and 104 MB on the volume, in 119 to 128 seconds. A `ctexart` page with a pgfplots figure then compiled with no network. |
| A version change removes the TeX volume and makes it again, and the TeX step runs again. | Podman copies an image's files into a new volume alone, so a kept volume holds the TeX Live of the old image. |
| The module installs those four collections and no scheme. | The full scheme took 991 seconds and 4.8 GB in the lab. The publisher's `texlive-full` image is a 9.4 GB download, 18.8 GB on disk, and its pull failed twice on Podman 3.4. |

## The page

The page is the `web` entry of the app `ayakaleaf_<device id>`, titled
`Ayakaleaf`, the entry's id `ayakaleaf_<device id>_web`, with
`is_token_required: true` and `description_code` `ayakaleaf_module`. The
entry exists while the module reads `running`.

| Rule | Reason |
| --- | --- |
| The agent's forwarder listens on `127.0.0.1` at a port the agent takes from 8900 up at the first apply and keeps in the module's record, where the agent's end of a `connect` stream reaches it, and reports it as `port`. | The page's port is the agent's, as Hermes WebUI's is ([hermes_webui.md](hermes_webui.md), "The page"). |
| The app's 80 is published on `127.0.0.1` at a free loopback port the agent picks at the first apply and keeps in the module's record. The published port is in no entry, and the `connect` stream does not serve it. | Every request from a client reaches the app through the forwarder's check. |
| The administrator's password stays set. | A program on the machine that finds the published port still meets the app's login. |

The forwarder turns the hub's token into the app's own login:

| A request | The forwarder |
| --- | --- |
| holds `?tkn=<token>` that verifies under the module's secret | sends `GET /login` to the app with the browser's `Host`, for a session cookie and the `ol-csrfToken` the page holds; sends `POST /login` with that cookie, `Accept: application/json` and the JSON body `{_csrf, email, password}`, the administrator's; sets the session cookie the app returns on the browser, and redirects to `/project` |
| holds `?tkn=<token>` that verifies under a guest's secret, a guest the module's record holds as made | signs in the same way with that guest's e-mail and password, accepts every invitation waiting for the guest ("The guest account"), sets the session cookie on the browser, and redirects to `/project` |
| holds `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| holds the session cookie | passed on unchanged, `Host` and `Origin` as the browser sent them, the editor's WebSocket included, and the app checks the cookie |
| is a `POST /login`, or asks for a path under `/launchpad`, whatever else it holds | 401; the browser's login never reaches the app |
| holds neither | 401 |

| Rule | Reason |
| --- | --- |
| The login is the forwarder's own two requests to the published port, with no `Origin`. | The app returns 403 to a login without the CSRF token of a session it gave. Its response to the second request is `{"redir": "/project"}` with the session cookie. |
| The session cookie is named `ayakaleaf_sid_` and the first 12 characters of the device id: the hub sets the whole name in the app's `COOKIE_NAME` and sends it as `cookie_name`, and the forwarder reads and sets that name. | `COOKIE_NAME` renames the cookie in the web and real-time services alike, and the editor's socket and compile worked under such a name in the lab. Two machines' pages at two local ports of one client keep both logins only under two names ([client.md](../../client.md), "The Apps page"). |
| The hub sets `OVERLEAF_SESSION_SECRET` and `OVERLEAF_INVITE_TOKEN_SECRET`. | The image makes a new session secret at every start without one, which ends every login at a restart, and refuses to start without the invitation secret. |
| The cookie is the app's, HttpOnly and SameSite=Lax, and lasts five days, longer with each use. | The app checks it on every request, and the forwarder keeps no login state of its own. |
| The forwarder passes `Host` unchanged, and the module sets no site URL. | The login, the project list, the editor and its socket, the compile and the PDF view worked at the app's local name and at `127.0.0.1` with `OVERLEAF_SITE_URL` at its default. The site URL serves e-mail and invitation links, the Git, Dropbox and SSO callbacks and the per-project MCP endpoint, which the module turns on none of. |
| A token under the module's secret signs the browser in as the administrator, and a token under a guest's secret as that guest; nothing else signs a browser in. | The owner's clients are the owner, so one account serves each of them. A share's visitors are not, so each share has an account of its own ("The guest account"). The app's other accounts and invitations stay the person's to make. |

## The guest account

A Web share of the app's page signs its visitors in as an account of the
app's own, one per share, and never as the administrator: the module's
manifest names `web_share: {guest_login: guest_account}`
([../module_install.md](../module_install.md), "The manifest"). The hub makes
the account's facts when the share is made and seals them in the share's
record ([../../protocol.md](../../protocol.md), "Web shares"):

| Fact | What it is |
| --- | --- |
| the account | `guest-` and 4 characters from `a` to `z` and `0` to `9`, which the hub picks unlike every other guest of the module on that machine |
| its e-mail | `<account>@share.neutrino`, a domain no mail reaches; the app sends none, `EMAIL_CONFIRMATION_DISABLED` being true |
| its password | 18 random bytes as `secrets.token_urlsafe` gives them |
| its token secret | 32 random bytes, which a visitor's token is minted with ([../../protocol.md](../../protocol.md), "The service frame") |

The state carries each live share's guest, opened, in the module's
`guests`, `[{account, email, password, secret}]`. The hooks make each guest
the module's record does not hold, over the app's published port, as the
administrator, in four steps:

1. `GET /login` and `POST /login` with the administrator's e-mail and
   password, for the session and its CSRF token, as the forwarder's own
   login does ("The page").
1. `POST /admin/register` with the JSON body `{_csrf, email}`, whose answer's
   `setNewPasswordUrl` holds the guest's `user_id` and a `token`.
1. `GET /user/activate?token=<token>&user_id=<user_id>`, then `POST
   /user/password/set` with `{_csrf, passwordResetToken, password}`, the
   guest's password.
1. As the guest, `GET /login` and `POST /login`, then `POST /user/settings`
   with `{_csrf, first_name, last_name}`, the account's name and an empty
   last name.

The record keeps each guest made, with its `user_id`, and the hooks report
`details.guests`, `[{account, code, params}]`, `code` empty for a guest
made. A guest the state no longer names is deleted through the
administrator's routes by its `user_id`, and leaves the record.

| Rule | Reason |
| --- | --- |
| The hooks make a guest through the app's own routes, as a browser of the administrator does, and run nothing inside the container. | The image's `create-user.mjs` fails in the version the module installs, and the routes are the ones the app's own pages use. |
| A step that fails reports the guest `ayakaleaf_guest_failed {step, detail}`, `step` being `admin_login`, `register`, `password` or `name`, and the hooks run it again at the next apply of the state. The share reads `failed` meanwhile. | A visitor reaches no app whose guest is half made, and the owner sees why on the Web shares panel. |
| A guest sees the projects the owner shares with it and nothing else. The owner invites the guest's e-mail in the app's own Share dialog, the e-mail the Web shares panel shows to copy, and the forwarder accepts every invitation waiting for the guest at each sign-in: it reads them from the `ol-notifications` of `GET /project`, then sends `GET /project/<id>/invite/token/<token>` and `POST /project/<id>/invite/token/<token>/accept` for each. | The owner's one step is the invitation, and a visitor never meets one to accept. |
| When the share is revoked or expires, the hub takes its guest out of the state, and the hooks delete the account. The owner's projects stay, with what the guest edited in them. An uninstall removes every guest with every other datum of the app. | The account lives as long as its share, and ending the share is the person's one press. |
| The owner's own clients keep signing in as the administrator. | The owner's clients are the owner, and a share changes nothing for them. |

## The model

The app's AI assistant reads one model from its environment and lists no
other in the page. The tab's **AI model** field holds it, `model` in
`config/devices/<id>/ayakaleaf.json` ([../../ui_behavior.md](../../ui_behavior.md),
"The machine page").

| Rule | Reason |
| --- | --- |
| `AI_MODEL` is the field's model, or the first model the gateway serves while the field is empty. The hub writes the four `AI_` variables while the gateway serves a model, and none while it serves none. | The app shows its AI features only with all four set. |
| A new model rewrites the app's environment, which restarts the app. | The app reads the model at its start alone. |
| The app calls the gateway itself, at `host.containers.internal`, with the module's key. | In the lab a stand-in gateway logged the app container as the caller of the editor's AI chat. |
| `DOCS_MCP_URL` is empty, and the web search stays off. | Its default is `https://docs.overleaf.com/~gitbook/mcp`, a call to another host. The web search needs a Tavily key, which the module does not set. |

## Memory and disk

The three containers take about 1.6 GB of memory idle: the app 1.24 to 1.30
GB, mongo 120 to 320 MB and redis under 15 MB. A heavy XeLaTeX page adds
about 0.2 GB while it compiles. On Windows the first start peaked at 2584 MB
in a 4 GiB Podman machine, and in a 2 GiB machine it finished only by
swapping. The manifest names 2600 as `memory_mib`
([containers.md](containers.md), "Memory for the container modules";
[../../min_support.md](../../min_support.md), "What the agent drives"). The
three images take 4.7 GB on the disk of Podman's storage, and the TeX volume
777 MB after the first start.
