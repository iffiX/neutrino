"""Finding credentials and identifying details before they reach a commit.

This repository is one where a slip is expensive: it renders configuration for
a proxy gateway, and the real files it renders from hold node passwords, an
admin hash, device SSH keys and API keys. Those live in `.gitignore`d files, so
the danger is not them — it is the copy someone pastes into a docstring, a
test fixture built from a real `/proc/net/arp` dump, or an address written into
a commit message.

Off-the-shelf scanners find the first kind and miss the second. A proxy node's
name, a campus DHCP lease and a network card's MAC match no vendor's token
format, and they are exactly what identifies whose machine this is.

The rules here are patterns, never literals. A rule listing the real values
would itself be the leak, committed and searchable. So a real MAC is caught by
its globally-unique OUI bit rather than by being on a list, and a real address
by not being in a range reserved for documentation.

Pure: reads files, decides nothing about them.
"""

import math
import re
from dataclasses import dataclass

# Anything containing one of these is somebody's own word for "not a real
# value", and the line is left alone.
SCAN_PLACEHOLDER_WORDS = (
    "placeholder",
    "example",
    "replace-me",
    "replace_me",
    "your-",
    "your_",
    "changeme",
    "change-me",
    "dummy",
    "sample",
    "redacted",
    "xxxx",
    "notreal",
    "donotuse",
    "do-not-use",
)

# No real credential is shorter than this. Test fixtures are full of
# two-character stand-ins, and every scanner reports them.
SCAN_MIN_CREDENTIAL_LENGTH = 12

# Written on a line to say it was looked at and is fine.
SCAN_ALLOW_MARKER = "scan: allow"

# Never worth reading: build output, dependencies, binaries, lock files.
SCAN_SKIPPED_DIRECTORIES = (
    ".git",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
)
SCAN_SKIPPED_SUFFIXES = (
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".pdf",
    ".deb",
    ".rpm",
    ".tar",
    ".gz",
    ".zip",
    ".whl",
    ".so",
    ".pyc",
)
SCAN_SKIPPED_NAMES = ("package-lock.json", "yarn.lock", "uv.lock", "poetry.lock")

# How far back to look for the word that makes a dotted quad a version
# number rather than an address.
VERSION_CONTEXT_WIDTH = 32

# Below this, every part of a dotted quad is too small for it to be an
# address anyone was given.
VERSION_PART_CEILING = 16

# A line longer than this is minified or generated; entropy means nothing in it.
SCAN_MAX_LINE_LENGTH = 2000

# What counts as suspiciously random: length, and Shannon entropy in bits per
# character. Base64 tops out near 6, English prose sits near 4, and an
# identifier like ``CLIPROXYAPI_SUPPORTED_ARCHITECTURES`` stays below 4.2.
SCAN_ENTROPY_MIN_LENGTH = 28
SCAN_ENTROPY_THRESHOLD = 4.4

# Addresses that cannot identify anyone: private, loopback, link-local, CGNAT,
# multicast, broadcast, and the three ranges RFC 5737 reserves for writing
# about networks. Public resolvers are here because naming one leaks nothing.
SCAN_SAFE_ADDRESS_PREFIXES = (
    "0.",
    "10.",
    "127.",
    "169.254.",
    "192.0.2.",
    "198.51.100.",
    "203.0.113.",
    "224.",
    "240.",
    "255.",
    "1.1.1.1",
    "8.8.8.8",
    "8.8.4.4",
    "9.9.9.9",
    "223.5.5.5",
    "114.114.114.114",
)

_PRIVATE_172 = tuple(f"172.{octet}." for octet in range(16, 32))
_CGNAT_100 = tuple(f"100.{octet}." for octet in range(64, 128))

_ADDRESS_PATTERN = re.compile(r"(?<![\w./])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_MAC_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
_TOKEN_PATTERN = re.compile(
    r"\b("
    r"sk-ant-[A-Za-z0-9_-]{12,}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|gho_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|glpat-[A-Za-z0-9_-]{16,}"
    r"|tskey-[A-Za-z0-9-]{16,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[A-Za-z0-9_-]{30,}"
    r"|npm_[A-Za-z0-9]{30,}"
    r")"
)
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")
_HASH_PATTERN = re.compile(r"\$(?:argon2[a-z]*|2[aby]|6|5|scrypt)\$[^\s\"']{8,}")
_PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_BASE64_BODY_PATTERN = re.compile(r"^[A-Za-z0-9+/=]{40,}$")
# The scheme alone is the signal: nothing but a node's own share link is
# written this way, so the tail only has to be long enough to be an address.
_SHARE_LINK_PATTERN = re.compile(
    r"\b(?:ss|ssr|vless|vmess|trojan|hysteria2?|tuic)://[A-Za-z0-9+/=@:.?&\-_]{8,}"
)
_URL_CREDENTIAL_PATTERN = re.compile(r"\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(pass(?:word|phrase|wd)?|secret|token|api[_-]?key|auth[_-]?key"
    r"|access[_-]?key|private[_-]?key|setup[_-]?key|credential)\b"
    r"\s*[:=]\s*[\"']([^\"']{8,})[\"']"
)
_ENTROPY_CANDIDATE_PATTERN = re.compile(r"[A-Za-z0-9+/_-]{28,}={0,2}")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)+$")
_VERSION_CONTEXT_PATTERN = re.compile(
    r"(?i)(version|release|build|revision|installing|installed|install"
    r"|upgrade|update|downgrade|\bver|\brev|\bv)\W*$"
)


@dataclass
class SecretFinding:
    """One line that may not be safe to publish.

    Attributes:
        path: The file it was found in.
        line_number: Where in that file, counting from one.
        rule: Which rule fired, as a short slug.
        detail: What was matched, abbreviated so the finding itself is safe to
            paste into a terminal or a ticket.
        line: The whole line, trimmed.
    """

    path: str
    line_number: int
    rule: str
    detail: str
    line: str


class SecretScanner:
    """Reads text and reports what should not be published.

    Every rule answers "could this identify a person, a machine, or an
    account?" rather than "does this look like a secret". That is why a
    globally-unique MAC is reported while ``aa:bb:cc:dd:ee:ff`` is not: the
    second has the locally-administered bit set, which is what documentation
    addresses are supposed to use.
    """

    def __init__(self, *, is_entropy_checked: bool = True):
        """
        Args:
            is_entropy_checked: Whether to report long high-entropy strings.
                They catch credentials no rule anticipated, at the price of
                occasional noise from generated data.
        """
        self._is_entropy_checked = is_entropy_checked

    def scan_text(self, text: str, *, path: str) -> list[SecretFinding]:
        """Report everything questionable in one file's contents.

        Args:
            text: The file's contents.
            path: What to call it in the findings.

        Returns:
            Every finding, in the order the lines appear.
        """
        findings = []
        lines = text.splitlines()
        for number, line in enumerate(lines, start=1):
            if self._is_line_exempt(line):
                continue
            following = lines[number] if number < len(lines) else ""
            findings += [
                SecretFinding(path, number, rule, detail, line.strip()[:200])
                for rule, detail in self._match_line(line, following)
            ]
        return findings

    def _match_line(self, line: str, following: str) -> list[tuple]:
        """Every rule that fires on one line, as ``(rule, detail)`` pairs.

        Args:
            line: The line to judge.
            following: The line after it, which is what tells a real key from
                a mention of one.
        """
        matches = []
        for pattern, rule in (
            (_TOKEN_PATTERN, "vendor-token"),
            (_JWT_PATTERN, "jwt"),
            (_HASH_PATTERN, "password-hash"),
            (_SHARE_LINK_PATTERN, "proxy-share-link"),
            (_URL_CREDENTIAL_PATTERN, "url-credentials"),
        ):
            found = pattern.search(line)
            if found:
                matches.append((rule, _abbreviate(found.group(0))))

        if _PRIVATE_KEY_PATTERN.search(line) and _BASE64_BODY_PATTERN.match(
            following.strip()
        ):
            matches.append(("private-key", "-----BEGIN … PRIVATE KEY-----"))

        matches += self._match_addresses(line)
        matches += self._match_macs(line)
        matches += self._match_assignments(line)
        if self._is_entropy_checked:
            matches += self._match_entropy(line)
        return matches

    def _match_addresses(self, line: str) -> list[tuple]:
        """Public IPv4 addresses, which name a real host somewhere."""
        matches = []
        for found in _ADDRESS_PATTERN.finditer(line):
            address = found.group(0)
            if not _is_routable_address(address):
                continue
            # A four-part version number is shaped exactly like an address,
            # and vendor installers have plenty of them. What separates the
            # two is the word right before it, not the digits.
            before = line[max(0, found.start() - VERSION_CONTEXT_WIDTH) : found.start()]
            if _VERSION_CONTEXT_PATTERN.search(before):
                continue
            if _is_version_shaped(address):
                continue
            matches.append(("public-address", address))
        return matches

    def _match_macs(self, line: str) -> list[tuple]:
        """MAC addresses belonging to real hardware."""
        matches = []
        for mac in _MAC_PATTERN.findall(line):
            if not _is_real_hardware_mac(mac):
                continue
            matches.append(("hardware-mac", mac))
        return matches

    def _match_assignments(self, line: str) -> list[tuple]:
        """A credential-shaped name assigned something that is not a placeholder."""
        matches = []
        for name, value in _ASSIGNMENT_PATTERN.findall(line):
            if _is_placeholder(value) or _IDENTIFIER_PATTERN.match(value):
                continue
            if value.startswith(("$", "{", "<", "/", "http")) or " " in value:
                continue
            matches.append(
                (f"assigned-{name.lower().replace('-', '_')}", _abbreviate(value))
            )
        return matches

    def _match_entropy(self, line: str) -> list[tuple]:
        """Strings random enough to be a key nobody wrote a rule for."""
        matches = []
        for candidate in _ENTROPY_CANDIDATE_PATTERN.findall(line):
            if len(candidate) < SCAN_ENTROPY_MIN_LENGTH:
                continue
            if _IDENTIFIER_PATTERN.match(candidate) or _is_placeholder(candidate):
                continue
            if shannon_entropy(candidate) < SCAN_ENTROPY_THRESHOLD:
                continue
            matches.append(("high-entropy", _abbreviate(candidate)))
        return matches

    def _is_line_exempt(self, line: str) -> bool:
        """Whether a line is too long to judge, or marked as looked at."""
        if len(line) > SCAN_MAX_LINE_LENGTH:
            return True
        return SCAN_ALLOW_MARKER in line


# A word catalog line is ``"key": "sentence"``; the key names what the
# sentence is about, so a key holding ``password`` is a label, never a value.
CATALOG_DIRECTORY = "locales"


def is_catalog_line(path: str, line: str) -> bool:
    """Whether a line is a catalog entry whose value is prose, not a value.

    Args:
        path: The file's repository-relative path.
        line: The line another tool flagged.

    Returns:
        True for a ``"key": "text"`` line in a ``locales/*.json`` file whose
        text holds a space, a character outside ASCII, or is shorter than a
        credential.
    """
    parts = path.split("/")
    if CATALOG_DIRECTORY not in parts or not path.endswith(".json"):
        return False
    values = _quoted_values(line)
    if len(values) != 2:
        return False
    text = values[1]
    # Chinese prose carries no spaces; a credential is ASCII.
    return " " in text or not text.isascii() or len(text) < SCAN_MIN_CREDENTIAL_LENGTH


def is_worth_reporting(line: str, *, following: str = "", path: str = "") -> bool:
    """Whether another tool's finding on this line deserves a person's time.

    General-purpose scanners know many vendors' key formats and nothing about
    this repository, so they report every example file and every test fixture.
    Running their findings back through the rules here keeps their breadth
    without their noise.

    Three things make a finding not worth showing, and none of them is "it
    looked inconvenient": the line says of itself that it is a placeholder, it
    has already been marked as looked at, or it holds nothing long enough to
    be a credential at all.

    Args:
        line: The line the other tool flagged.
        following: The line after it, which decides whether a ``BEGIN`` header
            introduces a key or merely mentions one.
        path: The file it was found in; a word catalog's entries are prose.

    Returns:
        True when the line should still be shown.
    """
    if SCAN_ALLOW_MARKER in line or len(line) > SCAN_MAX_LINE_LENGTH:
        return False
    if path and is_catalog_line(path, line):
        return False
    if _PRIVATE_KEY_PATTERN.search(line):
        return bool(_BASE64_BODY_PATTERN.match(following.strip()))
    values = _quoted_values(line)
    if values and all(
        len(value) < SCAN_MIN_CREDENTIAL_LENGTH
        or _is_placeholder(value)
        or _IDENTIFIER_PATTERN.match(value)
        for value in values
    ):
        return False
    if not values and not _has_long_run(line):
        return False
    return not _is_placeholder(line)


def shannon_entropy(value: str) -> float:
    """The average bits of information per character.

    Args:
        value: The string to measure.

    Returns:
        Bits per character; 0 for an empty string.
    """
    if not value:
        return 0.0
    total = 0.0
    for character in set(value):
        share = value.count(character) / len(value)
        total -= share * math.log2(share)
    return total


def is_scannable(path: str) -> bool:
    """Whether a path is worth reading at all.

    Args:
        path: A repository-relative path.

    Returns:
        False for build output, dependencies, binaries and lock files.
    """
    parts = path.split("/")
    if any(part in SCAN_SKIPPED_DIRECTORIES for part in parts):
        return False
    if parts[-1] in SCAN_SKIPPED_NAMES:
        return False
    return not path.endswith(SCAN_SKIPPED_SUFFIXES)


def _is_routable_address(address: str) -> bool:
    """Whether an IPv4 address could belong to a real host worth hiding."""
    octets = address.split(".")
    if any(not part.isdigit() or int(part) > 255 for part in octets):
        return False
    if any(part != str(int(part)) for part in octets):
        return False
    if address.startswith(SCAN_SAFE_ADDRESS_PREFIXES):
        return False
    if address.startswith("192.168.") or address.startswith(_PRIVATE_172):
        return False
    return not address.startswith(_CGNAT_100)


def _quoted_values(line: str) -> list:
    """Every string literal on a line, which is where a pasted key would sit."""
    return re.findall(r"[\"'`]([^\"'`]+)[\"'`]", line)


def _has_long_run(line: str) -> bool:
    """Whether anything on the line is long enough to be a credential."""
    return any(
        len(run) >= SCAN_MIN_CREDENTIAL_LENGTH
        for run in re.findall(r"[A-Za-z0-9+/=_-]+", line)
    )


def _is_version_shaped(address: str) -> bool:
    """Whether a dotted quad reads as a release number rather than a host.

    A vendor's version has small parts all the way down. Real addressing does
    not work out that way: the ranges actually handed out have at least one
    part large enough to tell them apart.

    Args:
        address: A dotted quad.

    Returns:
        True when every part is small enough that this is a version.
    """
    return all(int(part) < VERSION_PART_CEILING for part in address.split("."))


def _is_real_hardware_mac(mac: str) -> bool:
    """Whether a MAC names real hardware rather than a written-down example.

    A vendor's OUI has the locally-administered bit clear; addresses meant for
    documentation are supposed to set it, which is what makes
    ``aa:bb:cc:dd:ee:ff`` safe and ``0c:5b:8f:…`` not.
    """
    octets = mac.split(":")
    first = int(octets[0], 16)
    if first & 0b10:
        return False
    if len(set(octets)) == 1:
        return False
    # A run of evenly spaced bytes is somebody counting, not a card.
    steps = {int(octets[i + 1], 16) - int(octets[i], 16) for i in range(5)}
    return len(steps) != 1


def _is_placeholder(value: str) -> bool:
    """Whether a value says of itself that it is not real."""
    lowered = value.lower()
    if any(word in lowered for word in SCAN_PLACEHOLDER_WORDS):
        return True
    return len(set(lowered.replace("-", "").replace("_", ""))) <= 2


def _abbreviate(value: str) -> str:
    """Shorten a match so a finding can be shown without republishing it."""
    if len(value) <= 12:
        return value
    return f"{value[:4]}…{value[-4:]} ({len(value)} chars)"
