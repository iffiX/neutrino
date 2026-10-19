"""frpc's file from a vendor's config, and how frpc's lines read.

The file is written from named fields of the vendor's TOML, never as its
text: the server, the account, the ``auth``, ``metadatas`` and ``transport``
tables, and the one proxy of the picked tunnel. Every other key and table is
left out, so a ``plugin``, ``visitors``, ``webServer`` or ``includes`` in a
vendor's text never reaches a frpc that runs as root.

Pure: text in, text out.
"""

import json
import re
import tomllib

from neutrino_hub.modules.frp.constants import (
    FRP_DEFAULT_SERVER_PORT,
    FRP_LINE_CONNECTION_ERRORS,
    FRP_LINE_LOGIN_FAILED,
    FRP_LINE_START_ERROR,
    FRP_LINE_START_SUCCESS,
    FRP_LOOPBACK_HOST,
    FRP_STATE_LOGIN_FAILED,
    FRP_STATE_UNREACHABLE,
)

# What the file takes from the vendor's config, by part.
FRP_TOP_LEVEL_KEYS = ("serverAddr", "serverPort", "user")
FRP_TOP_LEVEL_TABLES = ("auth", "metadatas", "transport")
FRP_PROXY_KEYS = ("name", "type", "remotePort")
FRP_PROXY_TABLES = ("metadatas", "transport")
FRP_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
# The colour codes frpc writes around its console lines.
FRP_COLOUR_CODE = re.compile(r"\x1b\[[0-9;]*m")


def server_port(text: str) -> int:
    """The node's port frpc logs in at, from a vendor's config.

    Args:
        text: The vendor's TOML.

    Returns:
        ``serverPort``; frp's default 7000 when the config names none.

    Raises:
        ValueError: If the text is not TOML or the port is not a number.
    """
    return int(_parsed(text).get("serverPort", FRP_DEFAULT_SERVER_PORT))


def render_frpc(text: str, *, tunnel_name: str, loopback_port: int) -> str:
    """The file frpc runs from, for one tunnel of a vendor's config.

    Args:
        text: The vendor's TOML.
        tunnel_name: The ``name`` of the tunnel's proxy.
        loopback_port: The vendor's loopback listener, which the proxy's
            ``localPort`` names.

    Returns:
        The TOML frpc reads: the named top-level fields, ``loginFailExit``
        and ``log.to`` set by the hub, and the one proxy with ``localIP``
        and ``localPort`` set by the hub.

    Raises:
        ValueError: If the text is not TOML, or it holds no proxy of that
            name.
    """
    vendor = _parsed(text)
    proxy = next(
        (
            entry
            for entry in vendor.get("proxies") or []
            if isinstance(entry, dict) and entry.get("name") == tunnel_name
        ),
        None,
    )
    if proxy is None:
        raise ValueError(f"the config holds no proxy named {tunnel_name!r}")
    lines = [
        f"{key} = {_value(vendor[key])}" for key in FRP_TOP_LEVEL_KEYS if key in vendor
    ]
    lines += ["loginFailExit = true", 'log.to = "console"']
    for table in FRP_TOP_LEVEL_TABLES:
        if isinstance(vendor.get(table), dict):
            lines += ["", f"[{table}]", *_dotted(vendor[table])]
    lines += ["", "[[proxies]]"]
    lines += [f"{key} = {_value(proxy[key])}" for key in FRP_PROXY_KEYS if key in proxy]
    lines += [
        f"localIP = {_value(FRP_LOOPBACK_HOST)}",
        f"localPort = {loopback_port}",
    ]
    for table in FRP_PROXY_TABLES:
        if isinstance(proxy.get(table), dict):
            lines += _dotted(proxy[table], prefix=_key(table))
    return "\n".join(lines) + "\n"


def plain_lines(lines: list) -> list:
    """frpc's lines without their colour codes, empty ones left out.

    Args:
        lines: What frpc wrote, oldest first.

    Returns:
        Each line stripped of colour codes and surrounding space.
    """
    plain = (FRP_COLOUR_CODE.sub("", line).strip() for line in lines)
    return [line for line in plain if line]


def refused_line(lines: list) -> str:
    """The line saying the node refused the tunnel, when that is the last word.

    Args:
        lines: What the running frpc wrote, oldest first.

    Returns:
        The last line about the tunnel when it holds ``start error``; empty
        when the last one says the proxy started, or none says either.
    """
    for line in reversed(lines):
        if FRP_LINE_START_ERROR in line:
            return line.strip()
        if FRP_LINE_START_SUCCESS in line:
            return ""
    return ""


def judge_exit(lines: list) -> tuple:
    """The state an ended frpc leaves, from what it wrote last.

    Args:
        lines: What the ended frpc wrote, oldest first.

    Returns:
        ``(state, last_line)``: ``login_failed`` when a line says the login
        failed and names no connection error; ``unreachable`` otherwise. The
        line is the login line when there is one, else the last line.
    """
    written = [line.strip() for line in lines if line.strip()]
    for line in reversed(written):
        if FRP_LINE_LOGIN_FAILED in line:
            if any(error in line for error in FRP_LINE_CONNECTION_ERRORS):
                return FRP_STATE_UNREACHABLE, line
            return FRP_STATE_LOGIN_FAILED, line
    return FRP_STATE_UNREACHABLE, written[-1] if written else ""


def _parsed(text: str) -> dict:
    """A vendor's TOML, parsed."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"the config is not TOML: {error}") from error


def _dotted(table: dict, *, prefix: str = "") -> list:
    """A table's scalar values as dotted keys, nested tables flattened."""
    lines = []
    for key, value in table.items():
        path = f"{prefix}.{_key(key)}" if prefix else _key(key)
        if isinstance(value, dict):
            lines += _dotted(value, prefix=path)
        else:
            lines.append(f"{path} = {_value(value)}")
    return lines


def _key(key: str) -> str:
    """A key bare when TOML allows it, else quoted."""
    return key if FRP_BARE_KEY.match(key) else _value(str(key))


def _value(value) -> str:
    """One TOML value: a string, a number, a bool or an array of them.

    Raises:
        ValueError: For a value of another kind.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise ValueError(f"a value of kind {type(value).__name__} is not written")
