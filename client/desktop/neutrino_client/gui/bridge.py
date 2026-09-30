"""The message bridge between the page and the control channel.

The page hands the shell ``{id, method, path, body}``; the bridge forwards
exactly those three request fields over the window's channel and answers
``{id, status, body}``. Nothing else the page says reaches the resident.
"""


class GuiBridge:
    """Forwards one page request at a time over the channel."""

    def __init__(self, *, channel):
        """
        Args:
            channel: The window's channel.
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
