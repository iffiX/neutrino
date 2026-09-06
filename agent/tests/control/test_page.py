"""The page's contract, checked on the frontend files it ships.

The page is plain HTML, CSS and JavaScript under ``agent/frontend/``, so
what can be checked here is the contract's visible surface: the three
sections, one panel per service type, controls greyed and never hidden, the
redraw guards, the busy spinners, the bridge adapter under the old call
sites — and the words table asserted complete: every ``{code}`` and every
state token the agent can emit is enumerated from the source and must have
a wording, so a new code or state without a word fails this suite.
"""

import pathlib
import re

import neutrino_agent
from neutrino_agent.control import page
from neutrino_agent.services.ai import AI_CLAUDE_SLOTS, AI_REASONING_EFFORTS

PAGE_HTML = page.gui_asset("index.html")
PAGE_CSS = page.gui_asset("style.css")
PAGE_JS = page.gui_asset("app.js")
PAGE_TEXT = PAGE_HTML + PAGE_CSS + PAGE_JS

# What can raise or return a typed code anywhere in the agent.
CODE_PATTERNS = (
    re.compile(r'"code":\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'ShareAttachError\(\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'SelfUpdateError\(\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'GuiShellUnavailableError\(\s*\n?\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'_failure\(\s*"([a-z][a-z0-9_]*)"'),
    re.compile(r'else\s+"([a-z][a-z0-9_]*)"'),
)

# Strings the else-pattern catches that are not codes: state words, the
# rpm family's fallback package manager, and the CLI surface's own verb
# and switch words.
NON_CODES = {"absent", "disabled", "yum", "off", "uninstall"}

# Codes only the terminal surface can meet: a shell that refuses to open
# never shows a page to word them on.
GUI_ONLY_CODES = {
    "gui_webkitgtk_missing",
    "gui_webview2_missing",
    "gui_wkwebview_missing",
}

# Codes the page words through their params' own detail text.
DETAIL_FALLBACK_CODES = {
    "install_failed",
    "download_failed",
    "reconcile_failed",
    "mount_failed",
    "unmount_failed",
    "forward_failed",
}

MODULE_BUSY_STATES = (
    "installing",
    "uninstalling",
    "activating",
    "deactivating",
)
MOUNT_BUSY_STATES = ("queued", "mounting", "pending")

# What can carry a state token anywhere in the agent.
STATE_PATTERNS = (
    re.compile(r'"state":\s*"([a-z_]+)"'),
    re.compile(r'\bstate = "([a-z_]+)"'),
    re.compile(r'clean_status\(\s*"([a-z_]+)"'),
    re.compile(r'_transient\("([a-z_]+)"'),
    re.compile(r'_stages\[record_id\] = "([a-z_]+)"'),
    re.compile(r'else\s+"([a-z_]+)"'),
)

# Strings the else-pattern catches that are not states: a code the codes
# test covers, the rpm family's fallback package manager, and the CLI
# surface's own verb and switch words.
NON_STATES = {"agent_update_fetch_failed", "yum", "off", "uninstall"}

# Mount record states the page words through ``is_attached`` rather than a
# states entry: an attached record shows the ok dot, a detached one the
# ``not_attached`` word.
ATTACH_RENDERED_STATES = {"mounted", "detached"}


def emitted_codes() -> set:
    """Every code the agent's own source can emit, by static enumeration."""
    root = pathlib.Path(neutrino_agent.__file__).parent
    codes = set()
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in CODE_PATTERNS:
            codes.update(pattern.findall(text))
    return codes - NON_CODES


def emitted_states() -> set:
    """Every state token the agent's own source can emit."""
    root = pathlib.Path(neutrino_agent.__file__).parent
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
    return dict(re.findall(r'([a-z_]+):\s*\n?\s*"([^"]*)"', match.group(1)))


# --- the shipped files and the assembled document ---


def test_the_page_is_three_files_the_loader_assembles():
    assert '<link rel="stylesheet" href="style.css">' in PAGE_HTML
    assert '<script src="app.js"></script>' in PAGE_HTML

    document = page.control_page_html()

    assert "href=" not in document.split("<body>")[0].split("<title>")[1]
    assert ".card" in document
    assert "const WORDS" in document


# --- the words table is complete ---


def test_every_code_the_agent_emits_has_a_word():
    worded = (
        set(words_block("codes"))
        | set(words_block("errors"))
        | DETAIL_FALLBACK_CODES
        | GUI_ONLY_CODES
    )

    missing = emitted_codes() - worded

    assert missing == set(), f"codes with no wording on the page: {sorted(missing)}"


def test_every_state_token_the_agent_emits_has_a_word():
    # The anchors that let the attach-rendered pair stand outside the table.
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
    # The loop's rejection counter can only name these three causes.
    assert set(words_block("causes")) == {
        "hub_refused",
        "hub_untrusted",
        "agent_newer_than_hub",
    }


def test_every_module_and_ai_state_has_a_word():
    # One closed table: absent, installed, installing, uninstalling,
    # failed, unsupported — plus the ai rows' switching pair.
    states = words_block("states")
    for state in (
        "installed",
        "absent",
        "unsupported",
        "failed",
        "unknown",
    ) + MODULE_BUSY_STATES:
        assert state in states, f"state {state} has no word"
    for gone in ("enabled", "disabled", "enabling", "disabling", "removing"):
        assert gone not in states, f"state {gone} is not in the table any more"


# --- the three sections and the four panels ---


def test_the_three_sections_are_titled():
    for title in (
        'section_status: "Status"',
        'section_modules: "Modules"',
        'section_services: "Services"',
    ):
        assert title in PAGE_JS


def test_the_sections_render_in_hub_order():
    assert (
        "section(WORDS.ui.section_status"
        in PAGE_JS.split("section(WORDS.ui.section_modules")[0]
    )
    assert (
        "section(WORDS.ui.section_modules"
        in PAGE_JS.split("section(WORDS.ui.section_services")[0]
    )


def test_one_panel_per_service_type():
    for panel in (
        'panel_web: "Web"',
        'panel_ports: "Ports"',
        'panel_ai: "AI"',
        'panel_files: "Files"',
    ):
        assert panel in PAGE_JS


# --- greyed, never hidden ---


def test_the_connection_controls_grey_for_an_ordinary_caller():
    assert "leave.disabled = !isPrivileged" in PAGE_JS
    assert "input.disabled = !isPrivileged" in PAGE_JS
    assert "button.disabled = !isPrivileged" in PAGE_JS


def test_the_module_buttons_grey_for_scope_support_busy_and_operations():
    assert (
        "button.disabled = !isPrivileged || !m.is_supported || working || isHeld"
    ) in PAGE_JS


def test_the_unmount_button_greys_outside_the_records_scope():
    assert "record.account === state.caller.account" in PAGE_JS
    assert "button.disabled = !mayAct" in PAGE_JS


def test_the_browse_button_greys_where_mounts_are_drive_letters():
    assert "(state.mount_location_shape || 'path') === 'path'" in PAGE_JS
    assert "browse.disabled = !canBrowse" in PAGE_JS
    assert "browse.title = canBrowse ? '' : WORDS.ui.browse_drive_letter" in PAGE_JS
    assert (
        'browse_drive_letter: "This machine mounts at a drive letter, typed as Z:"'
        in PAGE_JS
    )


def test_greyed_controls_say_why():
    assert 'privileged_only: "Sign in as an administrator to change this."' in PAGE_JS
    assert PAGE_JS.count("WORDS.ui.privileged_only") >= 4


def test_an_unhealthy_entry_is_greyed_never_dropped():
    assert "'feat' : 'feat greyed'" in PAGE_JS
    assert 'unhealthy: "not reachable now"' in PAGE_JS


# --- busy states spin ---


def test_every_mount_busy_state_has_a_spinner_word():
    assert '<span class="spin">' in PAGE_JS
    for state in MOUNT_BUSY_STATES:
        assert f"{state}: WORDS.ui.mount_{state}" in PAGE_JS


def test_every_module_busy_state_words_as_ongoing():
    states = words_block("states")
    for state in MODULE_BUSY_STATES:
        assert states[state].endswith("…"), state


def test_a_busy_chip_and_module_button_are_disabled():
    assert "chip.disabled = isGated || isBusy || !entry.is_healthy" in PAGE_JS
    for state in MODULE_BUSY_STATES:
        assert f"'{state}'" in PAGE_JS


def test_every_busy_surface_shows_the_spinner():
    # Module rows, AI chips and mount records mark a transient the same way.
    assert "(working ? '<span class=\"spin\"></span>'" in PAGE_JS
    assert "(isBusy ? '<span class=\"spin\"></span>'" in PAGE_JS
    assert "busyWord ? '<span class=\"spin\"></span>'" in PAGE_JS


# --- the redraw guards ---


def test_the_redraw_guards_are_all_present():
    # Redraw only on a changed payload…
    assert "if (serialized === lastSerialized) return;" in PAGE_JS
    # …never over a selection, a focused field, or an open dialog.
    assert "getSelection" in PAGE_JS
    assert "activeElement" in PAGE_JS
    assert "openDialogs > 0" in PAGE_JS


def test_a_deferred_payload_is_replayed_when_the_guard_lifts():
    assert "pendingState = state; return;" in PAGE_JS
    assert "if (pendingState !== null && canRedraw())" in PAGE_JS


# --- the bridge adapter, staging, hygiene ---


def test_the_page_reaches_the_agent_only_through_the_bridge():
    # Both backends of the one adapter, and no direct network reach.
    assert "window.pywebview.api.request(request)" in PAGE_JS
    assert "window.webkit.messageHandlers.neutrino.postMessage" in PAGE_JS
    assert "window.neutrinoReply" in PAGE_JS
    assert "fetch(" not in PAGE_JS


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


def test_the_ai_panel_stages_chips_config_and_apply():
    for marker in (
        "aiStaged",
        "tool_configs",
        "'/api/services/'",
        "CLAUDE_SLOTS",
        "REASONING_EFFORTS",
    ):
        assert marker in PAGE_JS


def test_the_ai_knobs_mirror_the_agents_own():
    assert (
        "const CLAUDE_SLOTS = %s;" % str(list(AI_CLAUDE_SLOTS)).replace('"', "'")
        in PAGE_JS
    )
    assert (
        "const REASONING_EFFORTS = %s;"
        % str(list(AI_REASONING_EFFORTS)).replace('"', "'")
        in PAGE_JS
    )


def test_the_chip_seeding_mirrors_the_targets_exactly():
    # An explicit false stays off, an absent account seeds off, and no
    # account is preselected for the person.
    assert "targets[account] = !!(state.ai_targets || {})[account];" in PAGE_JS
    assert "ai_connect_account" not in PAGE_JS


def test_a_sent_mount_password_is_cleared_from_the_stage():
    assert "staged.password = '';" in PAGE_JS


def test_the_dead_wording_is_gone():
    assert "removal did not take" not in PAGE_JS
    assert "the uninstall finished, but the software is still there" in PAGE_JS
    # The service layers install nothing any more, so their install words
    # are gone with the code paths.
    assert "installing_tooling" not in PAGE_JS
    assert "tooling_install_failed" not in PAGE_JS
    assert "no_switcher_build" not in PAGE_JS
    # One verb pair everywhere: nothing switches any more.
    assert "switch_unconfirmed" not in PAGE_JS
    assert "remove_unconfirmed" not in PAGE_JS
    # The loopback page's token session is gone with its transport.
    assert "open_hint" not in PAGE_JS
    assert "stale_token" not in PAGE_JS
    assert "control_token_invalid" not in PAGE_JS
    assert "control_page_not_served" not in PAGE_JS


# --- the operation panel and the missing-modules gate ---


def test_the_operation_panel_closes_the_modules_section():
    assert 'operation_title: "Operation output"' in PAGE_JS
    # Present only while an operation is running or has just run; the hub
    # sends null otherwise and the panel does not render.
    assert "if (state.operation) modulePanels.push(drawOperation" in PAGE_JS
    assert "section(WORDS.ui.section_modules, modulePanels)" in PAGE_JS


def test_every_operation_state_has_a_word():
    words = words_block("operation")
    for state in ("queued", "fetching", "running", "done", "failed"):
        assert state in words, f"operation state {state} has no word"
    # A running order is worded by what it was asked to do.
    assert "install: 'installing'" in PAGE_JS
    assert "uninstall: 'uninstalling'" in PAGE_JS


def test_the_operation_output_renders_as_a_monospace_tail():
    assert "log.className = 'oplog'" in PAGE_JS
    assert "ui-monospace" in PAGE_CSS


def test_everything_greys_while_an_operation_runs():
    assert "const OPERATION_RUNNING_STATES = ['queued', 'fetching', 'installing'," in (
        PAGE_JS
    )
    assert "const isHeld = isOperationRunning(state);" in PAGE_JS
    assert "button.disabled = isOperationRunning(state);" in PAGE_JS


def test_a_service_with_missing_modules_is_gated_but_present():
    assert (
        'service_needs_modules: "Install these modules to enable this service: '
        '{modules}"'
    ) in PAGE_JS
    # The notice is the error color, the panel stays, and its controls grey.
    assert "note.className = 'err'" in PAGE_JS
    assert "config.disabled = isGated || !entry.is_healthy" in PAGE_JS
    assert "apply.disabled = isGated || !isDirty" in PAGE_JS
    assert "if (isGated) mount.disabled = true;" in PAGE_JS


def test_only_a_privileged_caller_gets_the_install_missing_button():
    gate = PAGE_JS.split("function missingModulesNotice")[1]
    gate = gate.split("async function installMissing")[0]
    assert "if (state.caller.is_privileged)" in gate
    assert "installMissing(missing.map((m) => m.name))" in gate


def test_installing_missing_modules_is_ordinary_asks_in_order():
    body = PAGE_JS.split("async function installMissing")[1]
    body = body.split("\n}")[0]
    assert "await send('/api/module', { name: name, is_enabled: true });" in body


def test_a_native_module_row_reads_built_in_and_offers_no_button():
    assert "if (m.is_native || m.installer === 'user') {" in PAGE_JS
    assert 'built_in: "built in"' in PAGE_JS
    assert "m.is_native ? WORDS.ui.built_in" in PAGE_JS


def test_an_absent_user_tier_row_words_the_tier_and_offers_no_button():
    # The person installs the software; the row only shows what is detected.
    assert (
        'user_tier: "Install it on the machine yourself; ' 'the hub only manages it"'
    ) in PAGE_JS
    assert "m.installer === 'user' && m.state === 'absent'" in PAGE_JS
    assert ("WORDS.states.absent + ' — ' + WORDS.ui.user_tier") in PAGE_JS


def test_the_impersonation_wording_is_gone_with_its_code():
    assert "module_fetch_unavailable" not in PAGE_JS


def test_uninstalling_the_ssh_server_asks_first():
    # Losing SSH can lock a person out, so the row's uninstall confirms.
    assert "m.kind === 'openssh' && isOn" in PAGE_JS
    assert "confirmDialog(WORDS.ui.uninstall_ssh_title" in PAGE_JS
    assert 'uninstall_ssh_title: "Uninstall the SSH server?"' in PAGE_JS
