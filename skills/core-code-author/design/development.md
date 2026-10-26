# Running the hub from source

Development runs the hub from a checkout: a virtual environment for the
interpreter, and a root of its own for everything the hub writes about
itself. The routing, the firewall and the interface roles change the machine
exactly as an installed hub changes them. How an installed hub comes to run
is [architecture.md](architecture.md), "`nhub setup` configures and starts,
and installs nothing".

## Development runs from a checkout, against a root of its own

```bash
git clone git@github.com:iffiX/neutrino.git && cd neutrino
python3 -m venv .venv && .venv/bin/pip install -e "hub[dev]"
sudo .venv/bin/nhub --dev setup     # names the packages to install if any are missing
sudo .venv/bin/nhub --dev run       # the panel, the proxy core and the gateway
```

`--dev`, which comes before the subcommand, moves the five roots under
`hub_dev_root/` in the working copy, by setting `NEUTRINO_DEV_ROOT`; the
agent's own development root is `agent_dev_root/` beside it. Everything the
hub writes about itself goes there:

```text
hub_dev_root/
    etc/neutrino/hub/       the configuration, the transport's static key
                            among it
    var/lib/neutrino/       generated, geodata and the AI gateway's state
    var/log/neutrino/
    run/neutrino/           the login lockout and the transport's socket
    opt/neutrino/bin/       neutrino_transport, xray, frpc and the AI gateway
```

**What `--dev` changes, and what it does not.** It is not a sandbox. A
checkout is how the routing, the firewall and the interface roles are
developed, so `--dev` takes the interfaces over and writes the firewall
exactly as a real install does. The one thing it does not do is install the
hub as a service:

| Step | Package install | `--dev` |
| --- | --- | --- |
| Checking the packages the hub needs | Refuses if any are missing | Refuses, the same way |
| Guarding SSH with fail2ban | Writes the jail | Writes the jail |
| Creating service user and directories | Creates them | Creates them, under the dev root |
| Preparing the Python environment | Included in the package | Builds `.venv` |
| Installing xray-core and geodata | Included in the package | Fetches the pinned pair into the dev root |
| Installing frpc | Included in the package | Fetches the pinned frpc into the dev root |
| The transport | Included in the package, a unit of its own account | Built from `transport/` with the `go` on `PATH` into the dev root, and refused with one sentence when there is none |
| Preparing config from examples | Copies them | Copies them |
| **Installing systemd units** | **Writes them** | **Skipped** |
| Applying the interface roles | Takes the interfaces over | Takes the interfaces over |
| Rendering and applying configuration | Renders and validates | Renders and validates |
| **Enabling services at boot** | **Enables them** | **Skipped** |
| **Starting services** | **Starts them** | **Skipped** |
| **Installing the AI gateway** | **Unit, enabled and started** | **Directories and the rendered config only** |
| Setting the panel password | Stores the hash | Stores the hash |

The fetches of xray, the geodata and frpc go through the hub's fetcher, with
the method every download uses ([agent/module_install.md](agent/module_install.md),
"Choosing a source").

`nhub --dev run` is what runs in place of the units: the panel, the
transport as its child with the secret on its standard input, the proxy
core and the AI gateway together in the foreground, and where node is
installed the frontend's dev server beside them, with Vite proxying the API
to the same port.

The units on a real machine start the same command one process at a time
(`nhub run --only-web`, `--only-xray`, `--only-cliproxyapi`), so systemd keeps
deciding who each daemon runs as and what it can reach, and a working copy
still runs the same code path. The macOS and Windows services take the
supervising path instead, `nhub run` with no `--only` on macOS and
`nhub service run` on Windows ([architecture.md](architecture.md), "One
service supervises the daemons on macOS and Windows").

**Deleting `hub_dev_root/` undoes the hub, not the machine.** The
configuration, the rendered files, the databases and the panel password go
with it, and the next `nhub --dev setup` starts from nothing, the run-once
rule included, which reads the password from that root. What stays is what
`--dev` did to the machine itself: the interface roles, the firewall, the
`fail2ban` jail and the `xray` service account. Those are the parts a checkout
exists to exercise, and undoing them is the machine owner's to do.

## The Go programs in a checkout

The transport and the SSH server are Go, and a checkout builds them with the
toolchain on `PATH`, the version `transport/go.mod` and
`agent/sshserver/go.mod` name ([min_support.md](min_support.md), "The Go
programs"):

```bash
cd transport && go test -race ./... && go build -o ../hub_dev_root/opt/neutrino/bin/ ./cmd/neutrino_transport
cd agent/sshserver && go test -race ./... && go build -o ../../agent_dev_root/opt/neutrino/agent/bin/ ./cmd/neutrino_ssh_server
```

`nhub --dev setup` runs the first build itself. An agent or a client run
from a checkout finds `neutrino_transport` in its own development root's
`bin/`, and `NEUTRINO_TRANSPORT_BIN` names another file; the Python
packages carry no Go and import none.

## Why a checkout installs nothing either

Nothing installed the dependencies for it, so `nhub --dev setup` names them
and stops, on the same reasoning as the packaged path: a process that
reconfigures NetworkManager is never the process that installs it
([min_support.md](min_support.md), "What each package holds and depends
on").

The interpreter is the same story upside down. A package includes its own,
so it runs on a machine with no Python, while a checkout builds a virtual
environment because nobody else builds one.
