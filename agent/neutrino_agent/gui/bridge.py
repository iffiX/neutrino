"""The message bridge between the page and the control channel.

The page hands the shell ``{id, method, path, body}``; the bridge forwards
exactly those three request fields over the window's control connection and
answers ``{id, status, body}``. Scope never comes from the page: the channel
was opened by the ``nagent gui`` invocation, and the kernel-read identity of
that connection is the whole authority.
"""


class GuiBridge:
    """Forwards one page request at a time over the control connection."""

    def __init__(self, *, channel):
        """
        Args:
            channel: The window's control connection.
        """
        self._channel = channel

    def handle(self, request) -> dict:
        """Answer one page request.

        Args:
            request: The page's ``{id, method, path, body}``.

        Returns:
            ``{id, status, body}``; a channel that stopped answering gives
            ``status`` 0 and a ``control_channel_closed`` body.
        """
        asked = request if isinstance(request, dict) else {}
        method = "POST" if str(asked.get("method", "")).upper() == "POST" else "GET"
        path = str(asked.get("path", ""))
        body = asked.get("body") if method == "POST" else None
        if method == "POST" and not isinstance(body, dict):
            body = {}
        try:
            status, reply = self._channel.request(method=method, path=path, body=body)
        except (OSError, ValueError):
            status = 0
            reply = {"code": "control_channel_closed", "params": {}}
        return {"id": asked.get("id"), "status": status, "body": reply}


class GuiWindowApi:
    """What a pywebview page reaches as ``window.pywebview.api``."""

    def __init__(self, bridge):
        """
        Args:
            bridge: The window's bridge.
        """
        self._bridge = bridge

    def request(self, request) -> dict:
        """The page's one call: forward a request, return the reply.

        Args:
            request: The page's ``{id, method, path, body}``.

        Returns:
            The bridge's ``{id, status, body}``.
        """
        return self._bridge.handle(request)
