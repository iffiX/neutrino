# The panel's API

Every endpoint is `/api/<module>/<path>`, where `<module>` is the thing that
owns the data. The module is the unit: one router file, one prefix, one page in
the panel, and where a module exists under `modules/` the two names match.

## One module, one prefix

`web/routers/<module>.py` declares `APIRouter(prefix="/api/<module>")` and every
route in it is relative to that. Nothing is mounted at the top level, and no
route names a module it does not belong to.

A second file may share a prefix when it holds a sub-resource large enough to
be its own file — `device_files.py` serves `/api/devices/{mac_address}/files`,
`nodes.py` serves `/api/proxy/nodes` — but the prefix still names one module,
and the module's own routes stay in the file named after it.

## The module itself is the bare prefix

```text
GET  /api/network            what this module is, whole
PUT  /api/network            replace the module's own settings
```

`GET` returns the view the page draws: everything it needs for a first paint,
in one response. `PUT` takes the settings that belong to the module rather than
to one of its sub-resources — the global switches, not the individual
interfaces.

A module with nothing global to write has no bare `PUT`.

## A singular sub-resource is one whose write is not a setting

```text
PUT /api/network/mode
```

The mode is not stored beside the other settings and applied with them:
writing it replaces every interface in the module, hands the machine's network
back or takes it over, and answers with a configuration nobody sent. That is
its own resource, singular because there is one of it, and the body is what
the new shape needs rather than the shape's own fields.

The test is whether a caller could reasonably send it alongside the module's
other settings and expect nothing else to move. Where they could, it belongs
in the bare `PUT`.

## Sub-resources are plural nouns

```text
PUT    /api/network/interfaces/{name}
DELETE /api/network/interfaces/{name}
GET    /api/network/wifi_networks
DELETE /api/network/wifi_networks/{ssid}
POST   /api/proxy/nodes
DELETE /api/proxy/nodes/{node_id}
GET    /api/credentials/ssh_keys
```

The collection is plural, the member is addressed by its own identifier, and
every segment is `under_score` — the same rule as everywhere else in the
repository, so `install_plan`, never `install-plan`.

The identifier in the path is what the thing is called by the system that owns
it: an interface by kernel name, a device by MAC address, a pool by pool name.

## An operation is a verb, and only where there is no resource to write

```text
POST /api/proxy/apply
POST /api/network/interfaces/{name}/wifi/join
POST /api/devices/{mac_address}/wol
```

Render-and-apply, associating a radio, waking a machine: none of them is a
value that can be written somewhere. The test is whether a `PUT` or `DELETE` to
a resource would say the same thing; if it would, that is the endpoint.

A destructive operation that needs arguments keeps its verb, because the
arguments have nowhere else to go — `POST /api/zfs/datasets/destroy` carries
whether the destroy is recursive, which a `DELETE` cannot.

## A write answers with what a read answers

`PUT /api/network/interfaces/{name}` returns `NetworkView`, the same model
`GET /api/network` returns. The page replaces its state with the response and
never merges, so it cannot hold a version of the box that the box does not.

This is also what makes applying part of the request rather than a job to poll:
the response means the interface is already doing this.

## The names are the same in three places

A field is spelled once. `is_exposed` is the JSON key in
`config/router/network.json`, the attribute on the Pydantic model in
`web/models.py`, and the property on the TypeScript interface in
`frontend/src/api_types.ts`. A path segment is spelled the way the model that
answers it is.

Booleans are questions in all three: `is_`, `has_`
([coding_style/naming_style.md](../coding_style/naming_style.md)).

## What exists

| Prefix | Owns |
| --- | --- |
| `/api/agent` | Device agents checking in: heartbeat, enrolment, results |
| `/api/ai` | The AI providers the gateway forwards to |
| `/api/auth` | Signing in and out, and what the session is |
| `/api/cliproxyapi` | The AI gateway: its keys and settings |
| `/api/credentials` | The secrets the box holds for somebody: SSH keys, logins and tokens |
| `/api/dashboard` | The summary, the traffic history, the DNS log |
| `/api/devices` | Managed LAN machines, their features and their files |
| `/api/gitea` | The Gitea module |
| `/api/netbird` | The overlay network |
| `/api/network` | The mode, the interfaces and their roles, Wi-Fi, what answers where |
| `/api/podman` | Containers and registry mirrors |
| `/api/proxy` | Routing policy, the exit nodes, and the balancer over them |
| `/api/samba` | Shares and their users |
| `/api/services` | Unit state, journals, install and uninstall |
| `/api/settings` | The panel's own: its port, password, backup, restore, version |
| `/api/zfs` | Pools and datasets |

Adding a module adds a row and a file. A route that does not fit any row is a
route whose module has not been decided yet.
