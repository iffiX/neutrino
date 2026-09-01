"""What the direct lists may hold, checked before xray is asked to load them.

xray parses an address entry strictly: anything that is neither a database
name nor a readable address or prefix fails the whole configuration, so one
mistyped line stops the proxy, the firewall and the resolver from being
applied at all. A domain entry is parsed loosely — an unrecognised one becomes
a rule that matches nothing — except a regular expression, which is refused
the same way an address is.

Both are checked here, where the person can still see what they typed.
"""

import ipaddress
import re

from neutrino_hub.modules.xray.constants import (
    XRAY_RULE_DATABASE_PREFIXES,
    XRAY_RULE_REGEXP_PREFIX,
)


def check_direct_address(entry: str) -> None:
    """Check one line of the direct address list.

    Args:
        entry: The line as it was typed.

    Raises:
        ValueError: If the line is neither a database name nor an address or
            prefix.
    """
    value = entry.strip()
    if not value:
        raise ValueError("an address entry is empty")
    if value.startswith(XRAY_RULE_DATABASE_PREFIXES):
        return
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError as error:
        raise ValueError(f"{value!r} is not an address or a prefix: {error}") from error


def check_direct_domain(entry: str) -> None:
    """Check one line of the direct domain list.

    Args:
        entry: The line as it was typed.

    Raises:
        ValueError: If the line is empty, carries a space, or is a regular
            expression that does not compile.
    """
    value = entry.strip()
    if not value:
        raise ValueError("a domain entry is empty")
    if value.startswith(XRAY_RULE_REGEXP_PREFIX):
        expression = value[len(XRAY_RULE_REGEXP_PREFIX) :]
        try:
            re.compile(expression)
        except re.error as error:
            raise ValueError(f"{value!r} does not compile: {error}") from error
        return
    if any(character.isspace() for character in value):
        raise ValueError(f"{value!r} has a space in it")
