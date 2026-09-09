"""The page's contract, checked on the frontend files it ships.

The page is plain HTML, CSS and JavaScript under ``client/frontend/``, so
what can be checked here is the contract's visible surface: the two
sections in order, one panel per service type, the redraw guards, the
bridge adapter with no direct network reach, and the words table asserted
complete: every ``{code}`` and every state token the client can emit is
enumerated from the source and must have a wording, so a new code or state
without a word fails this suite. Nothing of the agent's Modules section is
left.
"""

import pathlib
import re

import neutrino_client
from neutrino_client.control import page
from neutrino_client.services.ai import AI_CLAUDE_SLOTS, AI_REASONING_EFFORTS

PAGE_HTML = page.gui_asset("index.html")
PAGE_CSS = page.gui_asset("style.css")
PAGE_JS = page.gui_asset("app.js")

# What can raise or return a typed code anywhere in the client.
CODE_PATTERNS = (
    re.compile(r'"code":\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'ShareAttachError\(\s*\n?\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'EnrollmentError\(\s*\n?\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'GuiShellUnavailableError\(\s*\n?\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'_failure\(\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'word_code\(\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'"([a-z][a-z0-9_]*)",\s+# exit code'),
)

# Codes only the terminal surface can meet: a shell that refuses to open
# never shows a page to word them on, and a socket nobody could bind has
# no window behind it.
CLI_ONLY_CODES = {
    "gui_webkitgtk_missing",
    "gui_webview2_missing",
    "resident_not_running",
    "root_refused",
    "control_socket_unavailable",
}

# Codes the page words through their params' own detail text.
DETAIL_FALLBACK_CODES = {
    "switch_failed",
    "reconcile_failed",
    "mount_failed",
    "unmount_failed",
    "forward_failed",
}

MOUNT_BUSY_STATES = ("queued", "mounting", "pending")

# What can carry a state token anywhere in the client.
STATE_PATTERNS = (
    re.compile(r'"state":\s*"([a-z_]+)"'),
    re.compile(r'\bstate = "([a-z_]+)"'),
    re.compile(r'_stages\[record_id\] = "([a-z_]+)"'),
    re.compile(r'else\s+"([a-z_]+)"'),
)

# Strings the else-pattern catches that are not states: the CLI's own
# switch words and the mount helper's mount type.
NON_STATES = {"off", "cifs"}

# Mount record states the page words through ``is_attached`` rather than a
# states entry.
ATTACH_RENDERED_STATES = {"mounted", "detached"}


def emitted_codes() -> set:
    """Every code the client's own source can emit, by static enumeration."""
    root = pathlib.Path(neutrino_client.__file__).parent
    codes = set()
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in CODE_PATTERNS:
            codes.update(pattern.findall(text))
    codes.update(_helper_exit_codes())
    return codes


def _helper_exit_codes() -> set:
    from neutrino_client.constants import CLIENT_MOUNT_HELPER_EXIT_CODES

    return set(CLIENT_MOUNT_HELPER_EXIT_CODES.values())


def emitted_states() -> set:
    """Every state token the client's own source can emit."""
    root = pathlib.Path(neutrino_client.__file__).parent
    states = set()
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in STATE_PATTERNS:
            states.update(pattern.findall(text))
    return states - NON_STATES


def words_block(name: str) -> dict:
    """One block of the page's WORDS table, parsed key to wording."""
    match = re.search(name + r":\s*\{(.*?)\n  \}", PAGE_JS, re.DOTALL)
    assert match is not None, f"the page has no WORDS.{name} block"
    return dict(re.findall(r'\b([a-z][a-z0-9_]*):\s*\n?\s*"([^"]*)"', match.group(1)))


# --- the shipped files and the assembled document ---


def test_the_page_is_three_files_the_loader_assembles():
    assert '<link rel="stylesheet" href="style.css">' in PAGE_HTML
    assert '<script src="app.js"></script>' in PAGE_HTML

    document = page.control_page_html()

    assert "href=" not in document.split("<body>")[0].split("<title>")[1]
    assert ".card" in document
    assert "const WORDS" in document


def test_the_page_loads_from_the_checkout_when_nothing_is_built():
    assert page.gui_dir() == page.GUI_SOURCE_DIR
    assert page.GUI_SOURCE_DIR.name == "frontend"
    assert page.GUI_SOURCE_DIR.parent.name == "client"


# --- the words table is complete ---


def test_every_code_the_client_emits_has_a_word():
    worded = (
        set(words_block("codes"))
        | set(words_block("errors"))
        | DETAIL_FALLBACK_CODES
        | CLI_ONLY_CODES
    )

    missing = emitted_codes() - worded

    assert missing == set(), f"codes with no wording on the page: {sorted(missing)}"


def test_every_state_token_the_client_emits_has_a_word():
    assert "record.is_attached" in PAGE_JS
    assert 'not_attached: "not mounted"' in PAGE_JS
    worded = (
        set(words_block("states")) | set(MOUNT_BUSY_STATES) | ATTACH_RENDERED_STATES
    )

    missing = emitted_states() - worded

    assert missing == set(), f"states with no wording on the page: {sorted(missing)}"


def test_the_detail_fallback_names_each_of_its_codes():
    for code in DETAIL_FALLBACK_CODES:
        assert f"code === '{code}'" in PAGE_JS


def test_every_unbind_cause_has_a_word():
    assert set(words_block("causes")) == {
        "hub_refused",
        "hub_untrusted",
        "client_newer_than_hub",
    }


# --- the two sections and the five panels ---


def test_the_two_sections_are_titled_and_nothing_of_modules_is_left():
    assert 'section_status: "Status"' in PAGE_JS
    assert 'section_services: "Services"' in PAGE_JS
    assert "section_modules" not in PAGE_JS
    for gone in (
        "drawModules",
        "drawOperation",
        "missingModules",
        "accountChipRow",
        "drawRdpSharePanel",
        "shareUser",
        "rdpPasswordForm",
        "revealedSecret",
        "/api/module",
        "is_privileged",
        "state.accounts",
        "Modules",
    ):
        assert gone not in PAGE_JS, gone


def test_the_sections_render_status_then_services():
    assert (
        "section(WORDS.ui.section_status"
        in PAGE_JS.split("section(WORDS.ui.section_services")[0]
    )


def test_one_panel_per_service_type():
    for panel in (
        'panel_web: "Web"',
        'panel_ports: "Ports"',
        'panel_ai: "AI"',
        'panel_files: "Files"',
        'panel_desktops: "Remote desktops"',
    ):
        assert panel in PAGE_JS
    assert "['rdp', WORDS.ui.panel_desktops, drawDesktopsPanel]" in PAGE_JS


def test_the_ai_panel_is_one_toggle_config_and_apply():
    assert 'ai_enabled: "Enabled"' in PAGE_JS
    assert "aiStaged.is_enabled = !isOn" in PAGE_JS
    assert "is_enabled: aiStaged.is_enabled" in PAGE_JS
    assert "tool_configs: aiStaged.tool_configs" in PAGE_JS
    assert "targets" not in PAGE_JS


def test_the_ai_knobs_mirror_the_clients_own():
    assert (
        "const CLAUDE_SLOTS = %s;" % str(list(AI_CLAUDE_SLOTS)).replace('"', "'")
        in PAGE_JS
    )
    assert (
        "const REASONING_EFFORTS = %s;"
        % str(list(AI_REASONING_EFFORTS)).replace('"', "'")
        in PAGE_JS
    )


def test_the_desktops_panel_only_connects():
    body = PAGE_JS.split("function drawDesktopsPanel")[1].split("\n}")[0]
    assert "{ action: 'connect', id: entry.id }" in body
    assert "password" not in body
    assert "share" not in body


# --- greyed, never hidden ---


def test_an_unhealthy_entry_is_greyed_never_dropped():
    assert "'feat' : 'feat greyed'" in PAGE_JS
    assert 'unhealthy: "not reachable now"' in PAGE_JS


def test_everything_greys_while_the_hub_has_the_client_switched_off():
    assert "function isHeld(state)" in PAGE_JS
    assert PAGE_JS.count("isHeld(state)") >= 6
    assert 'disabled: "Switched off by the hub"' in PAGE_JS


def test_the_browse_button_greys_where_mounts_are_drive_letters():
    assert "(state.mount_location_shape || 'path') === 'path'" in PAGE_JS
    assert "browse.disabled = !canBrowse" in PAGE_JS


# --- busy states spin ---


def test_every_mount_busy_state_has_a_spinner_word():
    assert '<span class="spin">' in PAGE_JS
    for state in MOUNT_BUSY_STATES:
        assert f"{state}: WORDS.ui.mount_{state}" in PAGE_JS


# --- the redraw guards ---


def test_the_redraw_guards_are_all_present():
    assert "if (serialized === lastSerialized) return;" in PAGE_JS
    assert "getSelection" in PAGE_JS
    assert "activeElement" in PAGE_JS
    assert "openDialogs > 0" in PAGE_JS


def test_a_deferred_payload_is_replayed_when_the_guard_lifts():
    assert "pendingState = state; return;" in PAGE_JS
    assert "if (pendingState !== null && canRedraw())" in PAGE_JS


# --- the bridge adapter, staging, hygiene ---


def test_the_page_reaches_the_client_only_through_the_bridge():
    assert "window.pywebview.api.request(request)" in PAGE_JS
    assert "window.webkit.messageHandlers.neutrino.postMessage" in PAGE_JS
    assert "window.neutrinoReply" in PAGE_JS
    assert "fetch(" not in PAGE_JS
    assert "window.open(" not in PAGE_JS


def test_the_bridge_request_carries_only_id_method_path_and_body():
    adapter = PAGE_JS.split("function api(path, body)")[1].split("\n}")[0]
    for field in ("id:", "method:", "path:", "body:"):
        assert field in adapter
    assert "account" not in adapter
    assert "token" not in adapter


def test_a_refused_state_poll_renders_its_wording():
    assert "if (state.code) { renderHint(wordCode(state.code, state.params));" in (
        PAGE_JS
    )


def test_the_page_waits_for_the_bridge_before_polling():
    assert "bridgeReady().then(() => {" in PAGE_JS
    assert "setInterval(poll, POLL_INTERVAL_MS);" in PAGE_JS


def test_a_sent_mount_password_is_cleared_from_the_stage():
    assert "staged.password = '';" in PAGE_JS


def test_a_refused_link_is_worded_from_its_code():
    assert "wordCode(state.error.code, state.error.params)" in PAGE_JS


def test_the_page_offers_no_reassurance_prose():
    assert "the hub is never told it" not in PAGE_JS
