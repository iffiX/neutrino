"""Reading what xray printed, and keeping only what a person can act on.

Everything xray writes to a terminal goes to one stream: a version banner, a
tagline, timestamped `[Info]` lines about which file it read, `[Warning]`
lines about protocols it would rather you stopped using, and — last — the
reason it refused. Handed to the panel whole, the reason is the tail of a
paragraph, and the paragraph is mostly about neither the configuration nor the
person reading it.

So the refusal is separated from the noise. Warnings are kept rather than
discarded: "the Shadowsocks you configured is deprecated" is worth saying once,
beside the thing it is about, and never in the middle of an error.

Pure: this module reads text and returns text.
"""

import re

# The banner, and the line under it. Printed on every invocation including the
# successful ones, so they say nothing about this run.
XRAY_BANNER_PATTERNS = (
    re.compile(r"^Xray \S+ \("),
    re.compile(r"^A unified platform for anti-censorship\.$"),
)
# `2026/09/02 05:01:46.768303 [Info] infra/conf/serial: Reading config: ...`
XRAY_LOG_LINE = re.compile(
    r"^\d{4}/\d{2}/\d{2} [\d:.]+ \[(?P<level>\w+)\] (?P<body>.*)$"
)
# What xray says before the reason, on the line that carries it.
XRAY_FAILURE_PREFIX = "Failed to start: "
# The chain it builds its reasons out of. The last link is the specific one.
XRAY_REASON_SEPARATOR = " > "


def failure_of(output: str) -> str:
    """The reason xray refused, out of everything it printed.

    Args:
        output: Its combined standard output and error.

    Returns:
        The reason on its own, as short as xray's own chain allows. Falls back
        to the whole output with the banner removed when nothing in it looks
        like a failure — an unrecognised message is still better read than
        swallowed.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    kept = [line for line in lines if not _is_banner(line)]
    for line in kept:
        if XRAY_FAILURE_PREFIX in line:
            return _shorten(line.split(XRAY_FAILURE_PREFIX, 1)[1])
    spoken = [line for line in kept if not XRAY_LOG_LINE.match(line)]
    return " ".join(spoken or kept) or "no reason given"


def warnings_of(output: str) -> list[str]:
    """The warnings xray printed, without their timestamps.

    Args:
        output: Its combined standard output and error.

    Returns:
        One entry per warning, in the order printed. These are about the
        configuration and are worth showing, but they are not why anything
        failed — xray prints them on runs that succeed.
    """
    found = []
    for line in output.splitlines():
        match = XRAY_LOG_LINE.match(line.strip())
        if match is None or match.group("level") != "Warning":
            continue
        body = match.group("body")
        # `common/errors: The feature X is deprecated` — the package prefix is
        # xray's own filing system, not something to read.
        _, _, message = body.partition(": ")
        found.append(message or body)
    return found


def _is_banner(line: str) -> bool:
    return any(pattern.match(line) for pattern in XRAY_BANNER_PATTERNS)


def _shorten(reason: str) -> str:
    """The most specific link of one of xray's reason chains.

    xray reports a failure as the path it took to reach it —
    ``main: failed to create server > core: not all dependencies are
    resolved.`` — where everything before the last link is where the error
    passed through rather than what it was.

    Args:
        reason: The text after ``Failed to start:``.

    Returns:
        The last link, without its trailing full stops.
    """
    last = reason.split(XRAY_REASON_SEPARATOR)[-1]
    return last.strip().rstrip(".").strip()
