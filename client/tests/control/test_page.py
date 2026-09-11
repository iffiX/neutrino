"""The page's contract, checked on the frontend files it ships.

The page is plain HTML, CSS and JavaScript under ``client/frontend/``, so
what can be checked here is the contract's visible surface: the two
sections in order, the five service panels in their fixed order with the
line each carries while nothing is published, the redraw guards, the
bridge adapter with no direct network reach, and the word catalogs asserted
complete: the two languages carry the same keys, every key the page asks
for is in them, and every ``{code}`` and every state token the client can
emit is enumerated from the source and must have a wording, so a new code
or state without a word fails this suite. Nothing of the agent's Modules
section is left.
"""

import pathlib
import re

import neutrino_client
from neutrino_client import words
from neutrino_client.constants import CLIENT_LANGUAGES
from neutrino_client.control import page
from neutrino_client.services.ai import AI_CLAUDE_SLOTS, AI_REASONING_EFFORTS

PAGE_HTML = page.gui_asset("index.html")
PAGE_CSS = page.gui_asset("style.css")
PAGE_JS = page.gui_asset("app.js")
CATALOGS = words.catalogs()
EN_WORDS = CATALOGS["en"]

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

# Codes the page words through their params' own detail text.
DETAIL_FALLBACK_CODES = {
    "switch_failed",
    "reconcile_failed",
    "mount_failed",
    "unmount_failed",
    "forward_failed",
}

MOUNT_BUSY_STATES = ("queued", "mounting", "pending")

# The five service groups in the order the page draws them: the catalog key
# stem, the type on the wire, the heading, the builder, and the line the
# group carries while nothing is published.
SERVICE_PANELS = (
    ("web", "web", "Web", "drawWebPanel", "no web service is published"),
    ("ports", "port", "Ports", "drawPortsPanel", "no port is published"),
    ("ai", "ai", "AI", "drawAiPanel", "no AI service is published"),
    ("files", "file", "Files", "drawFilesPanel", "no share is published"),
    (
        "desktops",
        "rdp",
        "Remote desktops",
        "drawDesktopsPanel",
        "no remote desktop is shared right now",
    ),
)

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


def catalog_keys(prefix: str) -> set:
    """The English catalog's keys under one prefix, the prefix cut off."""
    cut = len(prefix)
    return {key[cut:] for key in EN_WORDS if key.startswith(prefix)}


def asked_keys() -> set:
    """Every catalog key the page asks for as a whole literal."""
    return set(re.findall(r"(?<![A-Za-z0-9_])t\('([a-z][a-z0-9_.]*)'\s*[,)]", PAGE_JS))


# --- the shipped files and the assembled document ---


def test_the_page_is_four_files_the_loader_assembles():
    assert '<link rel="stylesheet" href="style.css">' in PAGE_HTML
    assert page.GUI_WORDS_TAG in PAGE_HTML
    assert '<script src="app.js"></script>' in PAGE_HTML

    document = page.control_page_html()

    assert "href=" not in document.split("<body>")[0].split("<title>")[1]
    assert ".card" in document
    assert "const CATALOGS" in document
    assert "const WORDS" not in document


def test_the_document_carries_both_catalogs_so_the_page_fetches_nothing():
    document = page.control_page_html()

    for language in CLIENT_LANGUAGES:
        assert f'"{language}"' in document
    assert EN_WORDS["ui.section_status"] in document
    assert CATALOGS["zh-CN"]["ui.section_status"] in document
    assert "fetch(" not in document


def test_the_page_loads_from_the_checkout_when_nothing_is_built():
    assert page.gui_dir() == page.GUI_SOURCE_DIR
    assert page.GUI_SOURCE_DIR.name == "frontend"
    assert page.GUI_SOURCE_DIR.parent.name == "client"
    assert words.locales_dir() == words.LOCALES_SOURCE_DIR


# --- the catalogs are complete, and the page asks for nothing else ---


def test_both_languages_carry_the_same_keys():
    assert set(CATALOGS) == set(CLIENT_LANGUAGES)
    assert set(CATALOGS["zh-CN"]) == set(EN_WORDS)


def test_every_key_the_page_asks_for_is_in_the_catalog():
    # What the page builds from a token, which no whole literal carries.
    built = {f"ui.mount_{state}" for state in MOUNT_BUSY_STATES}
    built |= {f"ui.language_name.{language}" for language in CLIENT_LANGUAGES}

    missing = (asked_keys() | built) - set(EN_WORDS)

    assert missing == set(), f"keys the catalog has no wording for: {sorted(missing)}"


def test_nothing_of_the_old_words_table_is_left():
    assert "WORDS" not in PAGE_JS
    assert "const CATALOGS = JSON.parse(" in PAGE_JS


def test_a_key_no_catalog_carries_reads_as_itself():
    assert "return word === undefined ? key : fill(word, params);" in PAGE_JS


def test_the_language_falls_back_to_english_and_never_past_it():
    assert "CATALOGS[DEFAULT_LANGUAGE]" in PAGE_JS
    assert "const LANGUAGES = ['en', 'zh-CN'];" in PAGE_JS
    assert list(CLIENT_LANGUAGES) == ["en", "zh-CN"]


def test_every_code_the_client_emits_has_a_word():
    worded = catalog_keys("code.") | DETAIL_FALLBACK_CODES

    missing = emitted_codes() - worded

    assert missing == set(), f"codes with no wording on the page: {sorted(missing)}"


def test_every_state_token_the_client_emits_has_a_word():
    assert "record.is_attached" in PAGE_JS
    assert EN_WORDS["ui.not_attached"] == "not mounted"
    worded = catalog_keys("state.") | set(MOUNT_BUSY_STATES) | ATTACH_RENDERED_STATES

    missing = emitted_states() - worded

    assert missing == set(), f"states with no wording on the page: {sorted(missing)}"


def test_the_detail_fallback_names_each_of_its_codes():
    listed = PAGE_JS.split("const DETAIL_CODES = [")[1].split("];")[0]
    for code in DETAIL_FALLBACK_CODES:
        assert f"'{code}'" in listed
    assert "DETAIL_CODES.indexOf(code) >= 0" in PAGE_JS


def test_every_unbind_cause_has_a_word():
    assert catalog_keys("cause.") == {
        "hub_refused",
        "hub_untrusted",
        "client_newer_than_hub",
    }


# --- the two sections and the five panels ---


def test_the_two_sections_are_titled_and_nothing_of_modules_is_left():
    assert EN_WORDS["ui.section_status"] == "Status"
    assert EN_WORDS["ui.section_services"] == "Services"
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
        "section(t('ui.section_status')"
        in PAGE_JS.split("section(t('ui.section_services')")[0]
    )


def test_one_panel_per_service_type():
    for stem, kind, heading, builder, empty in SERVICE_PANELS:
        assert EN_WORDS[f"ui.panel_{stem}"] == heading
        assert EN_WORDS[f"ui.empty_{stem}"] == empty
        assert (
            f"['{kind}', t('ui.panel_{stem}'), {builder}, t('ui.empty_{stem}')]"
            in PAGE_JS
        )


def test_the_panels_draw_in_their_fixed_order():
    kinds = PAGE_JS.split("const kinds = [")[1].split("  ];")[0]
    drawn = re.findall(r"\['([a-z]+)', t\('ui\.panel_", kinds)

    assert drawn == [kind for _, kind, _, _, _ in SERVICE_PANELS]


def test_a_group_with_no_entry_draws_its_heading_and_its_empty_line():
    body = PAGE_JS.split("function drawServices")[1].split("\n}")[0]

    assert "entries.length === 0" in body
    assert "emptyPanel(title, empty)" in body
    assert "continue" not in body
    assert "function emptyPanel(title, line)" in PAGE_JS
    assert "services_empty" not in PAGE_JS


def test_the_ai_panel_is_one_toggle_config_and_apply():
    assert EN_WORDS["ui.ai_enabled"] == "Enabled"
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


# --- the language row on the Status card ---


def test_the_status_card_carries_a_language_row():
    body = PAGE_JS.split("function languageRow()")[1].split("\n}")[0]

    assert "conn.appendChild(languageRow());" in PAGE_JS
    assert "t('ui.language')" in body
    assert "picker('language', options, language" in body
    assert "send('/api/language', { language: value })" in body
    assert "LANGUAGES.map(" in body
    assert EN_WORDS["ui.language"] == "Language"
    for language in CLIENT_LANGUAGES:
        assert EN_WORDS[f"ui.language_name.{language}"]


def test_the_page_words_itself_in_the_language_the_state_names():
    assert "setLanguage(state.language);" in PAGE_JS
    assert "document.documentElement.lang = language;" in PAGE_JS


# --- greyed, never hidden ---


def test_an_unhealthy_entry_is_greyed_never_dropped():
    assert "'feat' : 'feat greyed'" in PAGE_JS
    assert EN_WORDS["ui.unhealthy"] == "not reachable now"


def test_everything_greys_while_the_hub_has_the_client_switched_off():
    assert "function isHeld(state)" in PAGE_JS
    assert PAGE_JS.count("isHeld(state)") >= 6
    assert EN_WORDS["ui.disabled"] == "Switched off by the hub"


def test_every_choice_the_page_offers_goes_through_the_one_picker():
    """One dropdown, five rows and a scroll, like the hub's own."""
    assert "function picker(id, options, chosen, onPick, isDisabled)" in PAGE_JS
    assert "createElement('select')" not in PAGE_JS
    for used in (
        "'mount_drive'",
        "'codex_effort'",
        "'codex_model'",
        "'gemini_model'",
        "'claude_' + slot",
        "'language'",
    ):
        assert used in PAGE_JS
    # An open list must outlive the poll that would redraw it away.
    assert "if (openPicker) return false;" in PAGE_JS
    # The list opens inside the field's own element, so a picker in a dialog
    # works without the page redraw a dialog holds back.
    assert "wrap.appendChild(list);" in PAGE_JS
    assert "function closeEveryPicker()" in PAGE_JS
    picker_body = PAGE_JS[
        PAGE_JS.index("function picker(") : PAGE_JS.index("function closeEveryPicker()")
    ]
    assert "redraw()" not in picker_body


def test_the_pickers_list_stops_at_five_rows_and_scrolls():
    assert ".picker_list" in PAGE_CSS
    assert "overflow-y: auto" in PAGE_CSS
    assert "max-height: 163px" in PAGE_CSS


def test_a_drive_letter_mount_is_picked_from_the_free_letters():
    """Where a mount is a drive letter there is no path to type or browse."""
    assert "(state.mount_location_shape || 'path') === 'drive_letter'" in PAGE_JS
    assert "function driveLetterLine(staged, state)" in PAGE_JS
    assert "state.mount_location_choices" in PAGE_JS
    assert "t('ui.mount_drive_caption')" in PAGE_JS
    # The browser belongs to the path shape alone, and is never a dead button.
    assert "browse.disabled" not in PAGE_JS
    assert "function mountPathLine(staged)" in PAGE_JS


# --- busy states spin ---


def test_every_mount_busy_state_has_a_spinner_word():
    assert '<span class="spin">' in PAGE_JS
    assert (
        "const MOUNT_BUSY_STATES = %s;" % str(list(MOUNT_BUSY_STATES)).replace('"', "'")
        in PAGE_JS
    )
    assert "t('ui.mount_' + state)" in PAGE_JS
    for state in MOUNT_BUSY_STATES:
        assert EN_WORDS[f"ui.mount_{state}"]


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


def test_the_page_draws_from_pushed_state_and_never_polls():
    """The resident pushes every change; the page asks once, for the first frame."""
    assert "window.neutrinoState = (state) =>" in PAGE_JS
    assert "bridgeReady().then(firstFrame);" in PAGE_JS
    assert "setInterval" not in PAGE_JS
    assert "POLL_INTERVAL" not in PAGE_JS


def test_a_redraw_the_person_caused_always_happens():
    assert "function redraw() {\n  if (lastState !== null) draw(lastState);" in PAGE_JS
    # What arrived while a dialog or a picker was open is drawn once it closes.
    assert "function settle() {" in PAGE_JS
    assert PAGE_JS.count("settle();") >= 2


def test_the_lanes_standing_greys_and_spins():
    assert "const isWorking = work.state === 'working';" in PAGE_JS
    assert "t('ui.ai_switching')" in PAGE_JS
    assert "t('ui.rdp_connecting')" in PAGE_JS
    assert "work.step === 'connecting:' + entry.id" in PAGE_JS
    assert EN_WORDS["code.busy"]


def test_a_failed_switch_leaves_apply_live_for_the_same_ask_again():
    assert "!(isDirty || work.code)" in PAGE_JS


def test_a_sent_mount_password_is_cleared_from_the_stage():
    assert "staged.password = '';" in PAGE_JS


def test_a_refused_link_is_worded_from_its_code():
    assert "wordCode(state.error.code, state.error.params)" in PAGE_JS


def test_the_page_offers_no_reassurance_prose():
    assert "the hub is never told it" not in PAGE_JS


def test_windows_is_given_the_icon_it_can_actually_load(tmp_path, monkeypatch):
    """Win32 loads an icon from an .ico and from nothing else."""
    gui_dir = tmp_path / "gui"
    gui_dir.mkdir()
    (gui_dir / "neutrino_client.png").write_bytes(b"png")
    (gui_dir / "neutrino_client.ico").write_bytes(b"ico")
    monkeypatch.setattr(page, "GUI_DATA_DIR", gui_dir)

    monkeypatch.setattr(page.os, "name", "nt")
    assert page.window_icon_path().endswith("neutrino_client.ico")

    monkeypatch.setattr(page.os, "name", "posix")
    assert page.window_icon_path().endswith("neutrino_client.png")
