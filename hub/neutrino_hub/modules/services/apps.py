"""An app's local name and an entry's fixed local port, the same on every client.

An app is one program on one machine with one or more entries. Its local
name is ``<slug of the title>.<slug of the machine name>.localhost``, and
each entry's local port follows from the entry's id alone, so a client, the
hub and Gitea's own configuration compute one number without asking. Pure
functions; every input is a string.
"""

import hashlib
import re

from neutrino_hub.modules.services.constants import (
    SERVICES_APP_SLUG_FALLBACK,
    SERVICES_COOKIE_NAME_CHARS,
    SERVICES_COOKIE_NAME_PREFIX,
    SERVICES_LOCAL_NAME_SUFFIX,
    SERVICES_LOCAL_PORT_COUNT,
    SERVICES_LOCAL_PORT_MIN,
    SERVICES_MACHINE_SLUG_FALLBACK,
    SERVICES_SLUG_CHARS_MAX,
    SERVICES_SLUG_SUFFIX_CHARS,
)

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str, fallback: str = SERVICES_APP_SLUG_FALLBACK) -> str:
    """One name as a host label.

    Args:
        text: The title or the machine name.
        fallback: The word taken when nothing of ``text`` is a letter or a
            digit.

    Returns:
        ``text`` in lowercase, each run of characters other than ``a`` to
        ``z`` and ``0`` to ``9`` turned into one ``-``, ``-`` taken off both
        ends, cut to 63 characters.
    """
    made = _NOT_SLUG.sub("-", text.lower()).strip("-")[:SERVICES_SLUG_CHARS_MAX]
    made = made.strip("-")
    return made or fallback


def machine_slugs(names_by_id: dict) -> dict:
    """The slug of each machine's name, told apart where two names give one.

    Args:
        names_by_id: Device id to the name the hub calls the machine.

    Returns:
        Device id to its slug; two machines whose names give one slug take
        ``-`` and the first six hex characters of their device id after it.
    """
    plain = {
        device_id: slug(str(name), SERVICES_MACHINE_SLUG_FALLBACK)
        for device_id, name in names_by_id.items()
    }
    counts: dict = {}
    for made in plain.values():
        counts[made] = counts.get(made, 0) + 1
    return {
        device_id: (
            made
            if counts[made] == 1
            else f"{made}-{str(device_id)[:SERVICES_SLUG_SUFFIX_CHARS]}"
        )
        for device_id, made in plain.items()
    }


def app_slugs(titles_by_id: dict) -> dict:
    """The slug of each app's title on one machine, told apart where two titles give one.

    Args:
        titles_by_id: App id to its title, for the apps of one machine.

    Returns:
        App id to its slug; two apps whose titles give one slug take ``-``
        and the first six hex characters of the SHA-256 of their id after it.
    """
    plain = {app_id: slug(str(title)) for app_id, title in titles_by_id.items()}
    counts: dict = {}
    for made in plain.values():
        counts[made] = counts.get(made, 0) + 1
    return {
        app_id: (
            made
            if counts[made] == 1
            else f"{made}-{hashlib.sha256(str(app_id).encode()).hexdigest()[:SERVICES_SLUG_SUFFIX_CHARS]}"
        )
        for app_id, made in plain.items()
    }


def local_name(app_slug: str, machine_slug: str) -> str:
    """The local name of one app.

    Args:
        app_slug: The slug of the app's title.
        machine_slug: The slug of the machine's name.

    Returns:
        ``<app slug>.<machine slug>.localhost``.
    """
    return f"{app_slug}.{machine_slug}{SERVICES_LOCAL_NAME_SUFFIX}"


def local_port(entry_id: str) -> int:
    """The port a client forwards one entry on.

    Args:
        entry_id: The entry's id.

    Returns:
        24000 plus the first four bytes of the SHA-256 of the id, read as a
        big-endian unsigned integer, modulo 8000: a number in 24000 to 31999.
    """
    digest = hashlib.sha256(entry_id.encode("utf-8")).digest()
    return SERVICES_LOCAL_PORT_MIN + (
        int.from_bytes(digest[:4], "big") % SERVICES_LOCAL_PORT_COUNT
    )


def cookie_name(entry_id: str) -> str:
    """The name of the login cookie a forwarder sets for one entry.

    Args:
        entry_id: The entry's id.

    Returns:
        ``neutrino_`` and the first 12 hex characters of the SHA-256 of the
        id.
    """
    digest = hashlib.sha256(entry_id.encode("utf-8")).hexdigest()
    return f"{SERVICES_COOKIE_NAME_PREFIX}{digest[:SERVICES_COOKIE_NAME_CHARS]}"


def entry_id(app_id: str, name: str) -> str:
    """The id of one entry of one app.

    Args:
        app_id: The app's id.
        name: The entry's name inside its app.

    Returns:
        ``<app id>_<name>``.
    """
    return f"{app_id}_{name}"
