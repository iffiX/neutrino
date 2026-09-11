"""The words the client's own surfaces say, in the language this person picked.

The catalogs are the page's own files, ``client/frontend/locales/<language>.json``,
copied into ``neutrino_client/data/gui/locales/`` by the packaging builds; a
checkout with no built copy reads the source directory directly. One flat
object per language, keys such as ``ui.tray.open`` and ``code.busy``, values
whole sentences with ``{name}`` holes.

The page is handed both catalogs inlined in its document; Python reads the
same files here, so the window title, the tray menu and the page never drift
apart. A key the chosen language does not carry falls back to English, and a
key neither carries reads as itself.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import pathlib
import re

from neutrino_client.constants import CLIENT_DEFAULT_LANGUAGE, CLIENT_LANGUAGES

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
LOCALES_DATA_DIR = _PACKAGE_DIR / "data" / "gui" / "locales"
LOCALES_SOURCE_DIR = _PACKAGE_DIR.parent / "frontend" / "locales"


def locales_dir() -> pathlib.Path:
    """The directory the catalogs load from.

    Returns:
        The packaged ``data/gui/locales`` directory when it holds the
        English catalog, the ``client/frontend/locales`` source directory
        otherwise.

    Raises:
        FileNotFoundError: When neither directory holds the catalogs.
    """
    for directory in (LOCALES_DATA_DIR, LOCALES_SOURCE_DIR):
        if (directory / f"{CLIENT_DEFAULT_LANGUAGE}.json").is_file():
            return directory
    raise FileNotFoundError("the client package carries no word catalog")


def catalogs() -> dict:
    """Every catalog the client ships, as the page is handed them.

    Returns:
        ``{language: {key: wording}}``, one entry per
        ``CLIENT_LANGUAGES``.

    Raises:
        FileNotFoundError: When the catalogs are not on this machine.
        ValueError: When a catalog is not a JSON object.
    """
    directory = locales_dir()
    return {
        language: _catalog(directory / f"{language}.json")
        for language in CLIENT_LANGUAGES
    }


def words(language: str) -> dict:
    """Every word one language says, English behind it.

    Args:
        language: The language asked for; one outside ``CLIENT_LANGUAGES``
            answers in English.

    Returns:
        ``{key: wording}``, the chosen language's own entries over the
        English ones.

    Raises:
        FileNotFoundError: When the catalogs are not on this machine.
        ValueError: When a catalog is not a JSON object.
    """
    directory = locales_dir()
    merged = _catalog(directory / f"{CLIENT_DEFAULT_LANGUAGE}.json")
    if language in CLIENT_LANGUAGES and language != CLIENT_DEFAULT_LANGUAGE:
        merged.update(_catalog(directory / f"{language}.json"))
    return merged


def word(language: str, key: str, params: "dict | None" = None) -> str:
    """One key's wording, its ``{name}`` holes filled.

    Args:
        language: The language to say it in.
        key: The catalog key, such as ``ui.tray.open``.
        params: The wording's own parameters; a missing name fills as empty.

    Returns:
        The words; a key no catalog carries reads as itself.

    Raises:
        FileNotFoundError: When the catalogs are not on this machine.
        ValueError: When a catalog is not a JSON object.
    """
    wording = words(language).get(key)
    if wording is None:
        return key
    return _fill(wording, params or {})


def language_for_tag(tag: str) -> str:
    """The client's language a system locale tag asks for.

    Args:
        tag: A locale tag as the operating system spells it, such as
            ``zh_CN.UTF-8`` or ``en_GB``.

    Returns:
        ``zh-CN`` for any Chinese tag, ``en`` for everything else.
    """
    if tag.lower().replace("-", "_").startswith("zh"):
        return "zh-CN"
    return CLIENT_DEFAULT_LANGUAGE


def _catalog(path: pathlib.Path) -> dict:
    """One catalog file as an object.

    Args:
        path: The catalog file.

    Returns:
        ``{key: wording}``.

    Raises:
        FileNotFoundError: When the file is not there.
        ValueError: When it is not a JSON object.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a word catalog")
    return data


def _fill(template: str, params: dict) -> str:
    """A wording with its ``{name}`` holes filled from the params.

    Args:
        template: The wording, with ``{name}`` holes.
        params: The wording's parameters; a missing name fills as empty.

    Returns:
        The filled wording.
    """

    def _value(match) -> str:
        return str(params.get(match.group(1), ""))

    return re.sub(r"\{(\w+)\}", _value, template)
