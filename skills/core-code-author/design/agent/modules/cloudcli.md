# The CloudCLI module

The `cloudcli` module runs CloudCLI, the npm package `@cloudcli-ai/cloudcli`
tested at 1.37.3 (AGPL-3.0), once per enabled account: a web page for AI coding
sessions. The module's version is the package's version, which the `npm`
feed lists ([module_install.md](../module_install.md), "Module
versions"). It is a program run as a person's account
([module_template.md](../module_template.md)): `agent/neutrino_agent/modules/cloudcli/`
holds `config.py`, `constants.py` and `hooks.py`, and `modules/shared/` does
the rest. Its configuration is `{instances: [{account, web_password,
token_secret, password}]}`, and the agent takes each instance's port itself
([../../protocol.md](../../protocol.md), "The account layer in the state").

**The account service layer runs it as the account, never as root**
([module_template.md](../module_template.md), "The run"): a unit
`neutrino_cloudcli@<account>.service` with `User=<account>` on Linux, a
LaunchDaemon with `UserName` on macOS, and on Windows a scheduled task
registered with the account's login, the one its row on the machine page
holds, as for VS Code. Its journal on Windows reads the end of `<account>.log` beside
the CLI, which the task's `cmd.exe` appends to, and an install still running
shows `run\install_<account>.log`; on macOS the LaunchDaemon's
`StandardOutPath` and `StandardErrorPath` name
`/Library/Logs/Neutrino/agent/cloudcli_<account>.log`.

**Node.js comes from the hub and stays out of the system.** It is CloudCLI's
own `node` artifact, and no other module reads it.
`data/manifests/cloudcli.json` pins the nodejs.org standalone build of Node
22 LTS for Linux, macOS and Windows on x64 and arm64, the same for every
version. Each has the digest of `SHASUMS256.txt` and two sources, nodejs.org
and then npmmirror's copy. The module's installer fetches it into the module cache,
and the agent opens `package {module: cloudcli, artifact, digest}` for it.
The agent unpacks it under
`cloudcli/node/` in its state root, `/var/lib/neutrino/agent/cloudcli/node/`
on Linux, `%ProgramData%\Neutrino\agent\state\cloudcli\node` on Windows and
`/Library/Application Support/Neutrino/agent/state/cloudcli/node` on macOS,
without the archive's own top directory, so `bin/node` sits directly under
it ([module_install.md](../module_install.md), "From the hub's cache"); the directory is opened to
every account: owned by root, read-only, one copy per machine. An install,
and every apply after it, removes a `node-v<version>-<os>-<arch>/`
directory it finds directly under `cloudcli/`; one whose files are still
open, as on Windows while an instance runs on it, goes at a later apply.
Node is never put on `PATH`, in any shell profile, or under `/usr/local`.

**CloudCLI is installed per account, apart from the account's own npm.** The
`cloudcli` artifact is of kind `npm`, and its `source_set` is the `npm` set,
the one list of npm registries ([module_install.md](../module_install.md),
"Source sets"). The agent ranks the registries, compares the chosen one's `dist.integrity` for
the version with the artifact's digest, and goes on to the next registry
when the two differ ([module_install.md](../module_install.md), "Choosing a
source"). As the account, with that Node, it runs `npm install
@cloudcli-ai/cloudcli@<version> --prefix <app-dir> --registry <registry>`
with `npm_config_cache` inside the app directory and
`npm_config_userconfig` naming an empty file, so no `~/.npmrc` is read,
`~/.npm` is untouched and nothing is installed globally. The app directory is
`~/.local/share/neutrino/agent/cloudcli/app` on Linux,
`~/Library/Application Support/Neutrino/agent/cloudcli/app` on macOS and
`%LOCALAPPDATA%\Neutrino\agent\cloudcli\app` on Windows. npm fetches the
package's dependencies from the same registry, each under its own
integrity. An install that fails on one registry runs again on the next, and
the last failure is the one reported.

**The service's environment is written from scratch**: `HOST=127.0.0.1`,
`SERVER_PORT` (CloudCLI's own name for its port) and `PATH`. Nothing is
inherited from a login profile or a version manager, and nothing names the
gateway. The tools CloudCLI starts read the account's own files: Claude
Code its `~/.claude/settings.json`, Codex its `~/.codex/auth.json` and
`~/.codex/config.toml`. Pointing those at the gateway is the machine's AI
tools setting ([ai_tools.md](../ai_tools.md)).

**The service's `PATH` names directories, never a tool.** After Node's own
directory it lists the account's `~/.local/bin` and `~/bin`, with `~` from
the account's passwd entry, then `/usr/local/bin`, `/usr/bin` and `/bin` on
Linux and `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin` and `/bin` on
macOS. On Windows the task's script puts `%APPDATA%\npm` after Node's
directory and then the account's own `PATH`, and nothing in any of them is
checked for existence.

**Node's own directory leads `PATH` for npm and for the service, on every
system.** The install scripts of the native modules call `node` by name,
and a task or a service that inherits no profile has nothing else on its
path that answers to it.

**A failed install names its step.** `download_failed {file, sources}` is
an install that no source served Node.js, or that no registry served the
package's integrity. `cloudcli_npm_install_failed` is a failed npm, and
`cloudcli_native_module_failed` is better-sqlite3, node-pty or bcrypt unable
to fetch its prebuilt binary. Both npm codes hold `detail`, the last lines
prebuild-install, node-gyp and npm wrote. node-pty and bcrypt hold their binaries inside their npm packages.
better-sqlite3 fetches its own from the host
`npm_config_better_sqlite3_binary_host` names: the artifact's `hosts` list
that setting's hosts, its GitHub releases and then npmmirror's copy, and the
agent sets it to the fastest. An install that fails on a native module runs
again with the next host.

**npm cannot take the agent down.** On Linux an account's npm runs as a
transient service of its own, `neutrino_cloudcli_install_<account>.service`,
started by `systemd-run --wait -p OOMPolicy=stop` with the service's output
and errors in one file, `run/install_<account>.log` under `cloudcli/` in
the state root, which systemd opens, the agent reads once the service has
ended and then deletes; the agent's unit has `OOMPolicy=continue`.
`systemd-run` gets no `--pipe` on any distribution: on Rocky 9 with SELinux
enforcing, systemd rejected the agent's pipes and the service failed to
start with `Failed to start transient service unit: Connection reset by
peer`. The service outlives an agent that stops during the install, and
systemd refuses a second service of its name while it runs. So the install
first waits for a service of its name that runs, polling every 5 seconds
for at most the install's 30 minutes, and stops it when the time is up.
When CloudCLI's version is then in the account's app directory, the
install takes that service's work and runs no npm. A `systemd-run` that
finds a service of that name still loaded, or a run the machine's shutdown
stopped, makes the step wait for its next check and keeps no failure, so a
reboot during npm leaves the step to run again after it. When the kernel kills the
install for want of memory, the install ends
`cloudcli_install_out_of_memory {account}` and the agent keeps running. A
failed install is tried again only with a state of another hash, and the
hash last tried is kept on disk, so an agent of the same build that starts
again does not try it again either.

**The install's state is `installing` until it ends.** npm runs as the
step `npm {account}` of CloudCLI's task ([agent.md](../../agent.md), "The
steps"). On Linux and macOS it runs to its end; on Windows the step starts
the install task and leaves it running (four hours at most), checks its
state every 30 seconds, and starts no instance until it has ended; an ended task is judged by its
result and by the app directory holding the package and the three native
modules, then unregistered. A task whose result says a shutdown or a
sign-out ended it is unregistered and started again, and keeps no failure. The hub publishes an instance's `web` entry
only while the device reports it running.

**The agent's forwarder stands in front of CloudCLI.** CloudCLI listens on
loopback alone. A thin HTTP forwarder of the agent's listens on
`127.0.0.1` at the instance's port, where the agent's end of a `connect`
stream reaches it. The hub generates each
instance's password and keeps it in its vault; on CloudCLI's first start the
agent registers the account with it through CloudCLI's register endpoint,
the first account registered being its administrator, and the forwarder
answers nobody before that. A CloudCLI that already has its administrator
and refuses the hub's password was set up for another hub: a reset or
reinstalled hub generates new secrets. The agent then starts that instance
afresh once: the instance's record names a new database file,
`auth-<UTC time>.db` beside the old one, which stays where it is untouched,
the instance is started again on it, and the forwarder registers the
account in it. The record's `database` names the file an instance runs on,
`auth.db` until it starts afresh.

| A request | The forwarder |
| --- | --- |
| carries `?tkn=<token>` that verifies | logs in to CloudCLI with the hub's password, writes CloudCLI's login state into the browser, and redirects to the page |
| carries `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| carries CloudCLI's login state | passes it on unchanged, WebSocket included |
| carries neither | 401 |
| asks for CloudCLI's register or login endpoint | 401; those are never passed on |

**A token is verified on the device, with no call to the hub.** The hub
mints one secret per instance, keeps it sealed, and the module's desired
state carries it opened, as it carries the password; the agent keeps a
root-only record per instance (its ports, password and secret) so the
forwarder comes back after an agent restart. A token is `base64url(expiry ||
nonce || HMAC-SHA256(secret, expiry || nonce))`, minted by the hub on every
`service` ask with `expiry` 60 seconds ahead
([protocol.md](../../protocol.md), the service material). The forwarder
checks the HMAC and the expiry itself and keeps every nonce it accepted until
that nonce's expiry, so a token works once. No token enters the device's
state, and minting one leaves the state's hash as it is
([client.md](../../client.md), "The Apps page").
