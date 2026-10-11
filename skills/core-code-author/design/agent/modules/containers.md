# The Containers module

The `podman` module is Containers: the Podman containers of a Linux
machine, and of no other system ([agent.md](../../agent.md), "Which modules
each system runs").

The Podman report gives each container's `host_bindings` as one `{address,
port, protocol}` per published host port, on TCP and UDP alike, `address`
empty for every address; `published_ports` reads the ports the machine
publishes, per protocol, from it ([agent.md](../../agent.md), "The connect
stream").
