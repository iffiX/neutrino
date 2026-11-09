"""The shell of the App share page, checked on the file the page ships.

A tab the app opened at an address with a fragment opens the app at that
fragment, and the fragment of a link's facts never reaches the app.
"""

import pathlib

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[3]
SHELL = (REPOSITORY_ROOT / "share_page" / "shell.js").read_text(encoding="utf-8")


def load_method() -> str:
    """The shell's load of the app's first page in the frame."""
    start = SHELL.index("async load(session, token) {")
    return SHELL[start : SHELL.index("\n  },\n", start)]


def test_the_frame_opens_at_the_tab_s_own_fragment_with_no_tab_tag():
    load = load_method()
    passed = load.index(
        "if (isOwnAddress && location.hash && !linkedFacts()) url.hash = location.hash;"
    )
    framed = load.index("frame.src = url.pathname + url.search + url.hash;")
    assert passed < framed
    assert "searchParams" not in load
    assert "TAB_PARAM" not in SHELL


def test_the_address_the_shell_starts_from_holds_no_fragment():
    """A token's redirect takes the place of the root, whatever the fragment."""
    load = load_method()
    assert (
        'let start = isOwnAddress ? location.pathname + location.search : (this.facts.app.path || "/");'
        in load
    )
    assert (
        'if (where && start === "/" && !this.facts.app.path) start = where[1];' in load
    )


def test_a_tab_announces_itself_once_the_newest_worker_controls_the_page():
    start = SHELL[SHELL.index("  async start(cache) {") :]
    start = start[: start.index("\n  },\n")]
    assert (
        "const isReplaced = Boolean(controller) && (Boolean(registration.installing"
        " || registration.waiting) || registration.active.scriptURL !== controller.scriptURL);"
        in start
    )
    waited = start.index("await within(changed, performance.now() + TIMING.open);")
    assert start.index("if (!controller || isReplaced) {") < waited
    assert waited < start.index("await this.announce();")


def open_web_socket() -> str:
    """The shell's WebSocket of the app."""
    start = SHELL.index("function openWebSocket(session, url, protocols, handlers) {")
    return SHELL[start : SHELL.index("\n}\n", start)]


def test_the_web_socket_offers_deflate():
    """VS Code's server declines an offer that asks for no context kept."""
    assert (
        'const WS_DEFLATE_OFFER = "permessage-deflate; client_max_window_bits";'
        in SHELL
    )
    assert "no_context_takeover" not in SHELL[: SHELL.index("const WS_DEFLATE_PARAMS")]
    socket = open_web_socket()
    assert (
        'if (isWsInflatable) headers.push(["Sec-WebSocket-Extensions", WS_DEFLATE_OFFER]);'
        in socket
    )
    assert 'new DecompressionStream("deflate-raw");' in SHELL


def test_every_compressed_message_of_a_socket_is_inflated_in_one_stream():
    assert "const WS_DEFLATE_TAIL = new Uint8Array([0x00, 0x00, 0xff, 0xff]);" in SHELL
    start = SHELL.index("function wsInflater() {")
    inflater = SHELL[start : SHELL.index("\n}\n", start)]
    assert inflater.count('new DecompressionStream("deflate-raw")') == 1
    written = inflater.index("await writer.write(whole);")
    assert (
        written
        < inflater.index("await sleep(0);")
        < inflater.index("chunks = [];\n      return message;")
    )
    socket = open_web_socket()
    assert "if (isDeflate) inflater = wsInflater();" in socket
    assert (
        "const bytes = isInflated ? await inflater.inflate(message) : message;"
        in socket
    )
    assert "delivery = delivery.then(async () => {" in socket
    assert "if (inflater) inflater.close();" in socket


def test_the_shell_sends_its_own_frames_uncompressed():
    socket = open_web_socket()
    assert "frame[0] = 0x80 | opcode;" in socket
    assert "0x40" not in socket[: socket.index("const readFrames")]


def test_a_server_that_declines_sends_plain_frames_and_any_other_answer_fails():
    start = SHELL.index("function wsDeflateAnswer(value) {")
    answer = SHELL[start : SHELL.index("\n}\n", start)]
    assert "if (!value) return false;" in answer
    assert 'if (name !== "permessage-deflate"' in answer
    assert (
        "if (names.some((each) => !WS_DEFLATE_PARAMS.includes(each))) return null;"
        in answer
    )
    socket = open_web_socket()
    assert (
        "if (answer === null || (answer && !isWsInflatable)) { fail(); return; }"
        in socket
    )
    assert "if (isCompressed && !isDeflate) { fail(); return; }" in socket
