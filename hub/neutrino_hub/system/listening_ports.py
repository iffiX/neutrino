"""Which ports something on this box already holds.

Asked before a listener is configured, because a port two services want is
found otherwise only as the second one exiting: xray validates a configuration
without binding it, and systemd reports a Type=simple unit started at fork.
"""

from neutrino_hub.utils.subprocess_run import run


class ListeningPortReader:
    """Reads the box's listening sockets."""

    def ports(self, *, ignoring: str = "") -> set[int]:
        """Every port with a listening socket on it.

        Args:
            ignoring: A process name whose sockets do not count. Re-applying a
                configuration would otherwise trip over the listeners the
                service being configured already holds.

        Returns:
            The port numbers, TCP and UDP together. Empty when the sockets
            cannot be read, so an unreadable box refuses nothing.
        """
        result = run(["ss", "-lntupH"], is_checked=False)
        held = set()
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 5:
                continue
            if ignoring and f'"{ignoring}"' in " ".join(fields[5:]):
                continue
            port = fields[4].rsplit(":", 1)[-1]
            if port.isdigit():
                held.add(int(port))
        return held
