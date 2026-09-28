"""The page's contract, checked on the frontend files it ships.

The page is plain HTML, CSS and JavaScript under ``client/frontend/``, so
what can be checked here is the contract's visible surface: the sidebar in
its order, one hub row per hub and the join row always there, one panel per
kind listing every hub's entries in hub order with the line each carries
while nothing is published, every entry's provider line, the one AI switch,
the staging keyed by service key, the redraw guards, the bridge adapter with no direct
network reach, and the word catalogs asserted complete: the two languages
carry the same keys, every key the page asks for is in them, and every
``{code}`` and every state token the client can emit is enumerated from the
source and must have a wording, so a new code or state without a word fails
this suite. Nothing of the agent's Modules section is left.
"""

import pathlib
import re

import neutrino_client
from neutrino_client import words
from neutrino_client.constants import CLIENT_LANGUAGES, CLIENT_THEMES
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
    re.compile(r'OverlayControlError\(\s*\n?\s*"([a-z][a-z0-9_]*)"'),
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

# The five kinds in the order the sidebar lists them: the catalog key stem,
# the type on the wire, the heading, the function drawing one entry, and the
# line the panel carries while no hub publishes the kind.
SERVICE_PANELS = (
    ("web", "web", "Web", "drawWebEntry", "no web service is published"),
    ("ports", "port", "Ports", "drawPortEntry", "no port is published"),
    ("ai", "ai", "AI", "drawAiEntry", "no AI service is published"),
    ("files", "file", "Files", "drawFileEntry", "no share is published"),
    (
        "desktops",
        "rdp",
        "Remote desktops",
        "drawDesktopEntry",
        "no remote desktop is shared right now",
    ),
)

# The sidebar's entries, top to bottom, by their title's key.
SIDEBAR_KEYS = (
    "ui.section_hubs",
    "ui.panel_web",
    "ui.panel_ports",
    "ui.panel_ai",
    "ui.panel_files",
    "ui.panel_terminals",
    "ui.panel_desktops",
)

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
    assert EN_WORDS["ui.section_hubs"] in document
    assert CATALOGS["zh-CN"]["ui.section_hubs"] in document
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
    built |= {f"ui.theme_name.{theme}" for theme in CLIENT_THEMES}

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


def test_nothing_of_the_unbind_causes_is_left():
    assert catalog_keys("cause.") == set()
    assert "self_unbound" not in PAGE_JS
    assert "self_unbound" not in catalog_keys("code.")


def test_the_one_refusal_that_unbinds_and_the_pin_mismatch_are_worded():
    assert EN_WORDS["code.binding_unknown"] == (
        "this hub no longer knows this client; join it again with a new link"
    )
    assert EN_WORDS["code.hub_untrusted"] == (
        "the hub's identity changed; if it was reset, join it again"
    )


# --- the two sections and the five panels ---


def test_a_sidebar_lists_the_hubs_and_every_kind_and_nothing_of_modules_is_left():
    side = PAGE_HTML.split('<aside class="side">')[1].split("</aside>")[0]
    head = PAGE_HTML.split('<div class="head">')[1].split('<div id="content">')[0]

    assert '<nav id="tabs"></nav>' in side
    assert "<h1>" in side
    assert 'id="refresh"' in head and 'id="settings"' in head
    assert head.index('id="page_title"') < head.index('id="refresh"')
    assert '<div id="content"></div>' in PAGE_HTML
    assert (
        "const TABS = ['hubs', 'web', 'port', 'ai', 'file', 'terminals', 'rdp'];"
        in (PAGE_JS)
    )
    assert [EN_WORDS[key] for key in SIDEBAR_KEYS] == [
        "Hubs",
        "Web",
        "Ports",
        "AI",
        "Files",
        "Terminals",
        "Remote desktops",
    ]
    assert [CATALOGS["zh-CN"][key] for key in SIDEBAR_KEYS] == [
        "中枢",
        "网页",
        "端口",
        "AI",
        "文件",
        "终端",
        "远程桌面",
    ]
    for gone in (
        "function section(",
        "function drawServices(",
        "function hubGroup(",
        "ui.section_services",
        "section_status",
        "section_modules",
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
    assert "ui.section_services" not in EN_WORDS


def test_the_open_tab_draws_the_hubs_a_kind_or_the_terminals():
    body = PAGE_JS.split("function draw(state)")[1].split("\n}")[0]

    assert "let openTab = 'hubs';" in PAGE_JS
    assert "content.appendChild(drawHubs(state));" in body
    assert "content.appendChild(drawTerminals(state));" in body
    assert "kindTab(state, KINDS.filter((kind) => kind[0] === openTab)[0])" in body
    assert "document.getElementById('page_title').textContent = tabTitle(openTab);" in (
        body
    )
    tabs = PAGE_JS.split("function drawTabs()")[1].split("\n}")[0]
    assert "button.className = tab === openTab ? 'tab on' : 'tab';" in tabs
    assert "button.onclick = () => { openTab = tab; redraw(); };" in tabs


def test_the_open_sidebar_entry_is_washed_in_the_accent_without_a_glow():
    assert "button.tab {" in PAGE_CSS
    tab_on = PAGE_CSS.split("button.tab.on {")[1].split("}")[0]
    bar = PAGE_CSS.split("button.tab.on::before {")[1].split("}")[0]
    assert "color: var(--color-accent)" in tab_on
    assert "var(--color-accent)" in bar
    assert "box-shadow" not in tab_on and "box-shadow" not in bar


def test_the_window_is_a_sidebar_beside_a_content_that_fills_the_width():
    wrap = PAGE_CSS.split(".wrap {")[1].split("}")[0]
    main = PAGE_CSS.split(".main {")[1].split("}")[0]
    content = PAGE_CSS.split("#content {")[1].split("}")[0]
    body = PAGE_CSS.split("body {")[1].split("}")[0]

    assert "grid-template-columns: 196px 1fr" in wrap
    assert "grid-template-rows: auto 1fr" in main
    assert "overflow-y: auto" in content
    assert "padding: 0" in body
    assert "max-width" not in PAGE_CSS.split(".modal {")[0]
    assert "kind_grid" not in PAGE_CSS and "kind_grid" not in PAGE_JS
    from neutrino_client.constants import (
        CLIENT_GUI_WINDOW_HEIGHT,
        CLIENT_GUI_WINDOW_WIDTH,
    )

    assert (CLIENT_GUI_WINDOW_WIDTH, CLIENT_GUI_WINDOW_HEIGHT) == (1080, 640)


def test_one_row_per_hub_names_it_its_standing_and_its_software():
    body = PAGE_JS.split("function hubRow(hub)")[1].split("\n}")[0]

    assert "for (const hub of hubs) card.appendChild(hubRow(hub));" in PAGE_JS
    assert "hubName(hub)" in body
    assert "return hub.hub_name || hub.gateway_url;" in PAGE_JS
    assert "t('ui.hub_software', { software: hub.hub_software })" in body
    assert "hub.connection_state === 'reconnecting'" in body
    assert "hub.is_disabled ? t('ui.disabled')" in body
    assert "wordError(hub.last_error)" in body
    assert "leave.onclick = () => askLeave(hub);" in body
    assert EN_WORDS["ui.disconnect"] == "Leave"


def test_leave_greys_and_spins_until_the_state_that_drops_the_row():
    body = PAGE_JS.split("function hubRow(hub)")[1].split("\n}")[0]
    asking = PAGE_JS.split("function askLeave(hub)")[1].split("\n}")[0]

    assert "if (leaveAsked[hubKey(hub)]) {" in body
    assert "leave.innerHTML = '<span class=\"spin\"></span>' + t('ui.disconnect');" in (
        body
    )
    assert "leave.disabled = true;" in body
    assert "leaveAsked[key] = true;" in asking
    assert "send('/api/leave', { hub_id: key })" in asking
    assert "delete leaveAsked[key];" in asking


def test_the_top_bar_carries_a_refresh_button_that_spins_until_a_push():
    button = PAGE_JS.split("function drawRefresh()")[1].split("\n}")[0]
    asking = PAGE_JS.split("function askRefresh()")[1].split("\n}")[0]
    push = PAGE_JS.split("window.neutrinoState = (state) => {")[1].split("\n};")[0]

    assert 'class="ghost refresh" id="refresh"' in PAGE_HTML
    assert "drawRefresh();" in PAGE_JS.split("function draw(state)")[1]
    assert "button.title = t('ui.refresh');" in button
    assert "button.textContent = '↻';" in button
    assert "button.innerHTML = '<span class=\"spin\"></span>';" in button
    assert "api('/api/refresh', {});" in asking
    assert "REFRESH_SPIN_MS = 3000;" in PAGE_JS
    assert "settleRefresh();" in push
    assert "button.refresh" in PAGE_CSS
    assert EN_WORDS["ui.refresh"] == "Refresh"
    assert CATALOGS["zh-CN"]["ui.refresh"] == "刷新"
    assert "hub_version" not in PAGE_JS
    assert "ui.hub_version" not in EN_WORDS


def test_a_hub_row_carries_no_target_radio_and_names_the_hub_the_tools_use():
    body = PAGE_JS.split("function hubRow(hub)")[1].split("\n}")[0]

    assert "radio" not in PAGE_JS
    assert "ui.hub_exit" not in EN_WORDS
    assert "t('ui.hub_is_exit')" in body
    assert EN_WORDS["ui.hub_is_exit"] == "the AI tools point at this hub"


def test_the_ai_panel_switches_one_gateway_on_and_every_other_off():
    entry = PAGE_JS.split("function drawAiEntry(card, state, hub, entry)")[1].split(
        "\n}"
    )[0]
    asking = PAGE_JS.split("async function askAiUse(hub, entry, isOn, noteKey)")[
        1
    ].split("\n}")[0]

    assert "const isInUse = isExit && !!ai.is_enabled;" in entry
    assert "toggle.className = isInUse ? 'chip on' : 'chip';" in entry
    assert "toggle.onclick = () => askAiUse(hub, entry, !isInUse, noteKey);" in entry
    assert "t('ui.ai_use')" in entry
    assert "if (isOn && !hub.is_exit) {" in asking
    assert "send('/api/exit/set', { hub_id: hubKey(hub) })" in asking
    assert "if (isEnabled) return;" in asking
    assert "is_enabled: isOn," in asking
    assert EN_WORDS["ui.ai_use"] == "The AI tools use this gateway"
    assert CATALOGS["zh-CN"]["ui.ai_use"] == "AI 工具使用此网关"
    assert EN_WORDS["code.no_exit_hub"]
    for gone in ("ui.apply", "ui.ai_enabled", "ui.ai_exit_is", "ui.ai_off"):
        assert gone not in EN_WORDS, gone


def test_the_join_row_is_always_there_and_words_a_refused_link():
    body = PAGE_JS.split("function joinRow(state)")[1].split("\n}")[0]

    assert "card.appendChild(joinRow(state));" in PAGE_JS
    assert "t('ui.add_hub')" in body and "t('ui.paste_hint')" in body
    assert "send('/api/join', { link: input.value })" in body
    assert "wordCode(state.error.code, state.error.params)" in body
    assert "input.onblur = settle;" in body
    assert EN_WORDS["ui.add_hub"] == "Join a hub"
    assert EN_WORDS["ui.connect"] == "Join"
    assert "t('ui.no_hubs')" in PAGE_JS
    assert "not_connected" not in PAGE_JS


def test_a_hub_is_keyed_by_its_id_and_by_its_binding_before_a_welcome():
    assert "function hubKey(hub) {\n  return hub.hub_id || hub.binding_id;" in PAGE_JS
    assert "function serviceKey(entry) {\n  return entry.hub_id + '/' + entry.id;" in (
        PAGE_JS
    )


# --- one panel per kind, in hub order ---


def test_a_kind_is_one_panel_listing_every_hubs_entries_in_hub_order():
    body = PAGE_JS.split("function kindTab(state, kind)")[1].split("\n}")[0]

    assert "const card = panelCard(t(titleKey), false);" in body
    assert body.count("panelCard(") == 1
    assert "for (const hub of hubs) {" in body
    assert "for (const entry of entriesOf(state, hub, type)) {" in body
    assert "build(card, state, hub, entry);" in body
    assert "hub.connection_state !== 'connected'" in body
    assert "card.appendChild(downRow(hub));" in body
    assert "hubBlock" not in PAGE_JS and "hub_title" not in PAGE_JS
    assert "entry.hub_id === hub.hub_id && entry.type === type" in PAGE_JS


def test_every_entry_names_its_hub_and_machine_with_the_address_behind():
    row = PAGE_JS.split("function entryRow(hub, entry, payloadText, extraNote)")[
        1
    ].split("\n}")[0]
    provider = PAGE_JS.split("function providerLine(hub, entry)")[1].split("\n}")[0]
    host = PAGE_JS.split("function entryHost(entry)")[1].split("\n}")[0]

    assert "providerLine(hub, entry)" in row
    assert "t('ui.provided_by', {" in provider
    assert "hub: hubName(hub), device: entry.device_name || entryHost(entry)," in (
        provider
    )
    assert "payload.url || payload.endpoint" in host
    assert "return payload.host || '';" in host
    for _, _, _, builder, _ in SERVICE_PANELS:
        body = PAGE_JS.split(f"function {builder}(card, state, hub, entry)")[1].split(
            "\n}"
        )[0]
        assert "entryRow(" in body and "hub, entry," in body, builder
    assert EN_WORDS["ui.provided_by"] == "from {hub}:{device}"
    assert CATALOGS["zh-CN"]["ui.provided_by"] == "由 {hub}:{device} 提供"


def test_every_action_names_the_entrys_hub():
    for sent in (
        "{ hub_id: entry.hub_id, id: entry.id }",
        "{ hub_id: entry.hub_id, id: entry.id, is_enabled: !isOn }",
        "{ action: 'connect', hub_id: entry.hub_id, id: entry.id }",
        "action: 'mount', hub_id: entry.hub_id, id: entry.id,",
        "{ action: 'mount', hub_id: entry.hub_id, record_id: record.record_id }",
        "{ action: 'unmount', hub_id: entry.hub_id, record_id: record.record_id }",
        "hub_id: entry.hub_id,\n    is_enabled: isOn,",
    ):
        assert sent in PAGE_JS, sent


def test_the_staging_is_keyed_by_service_key_and_the_tools_stage_is_one():
    assert "let aiStaged = null;" in PAGE_JS
    assert "function ensureAiStaged(state)" in PAGE_JS
    assert "aiStaged = null;" in PAGE_JS
    assert "const staged = fileStaged[key];" in PAGE_JS
    assert "(state.forwards || {})[serviceKey(entry)]" in PAGE_JS
    assert "(state.viewers || {})[serviceKey(entry)]" in PAGE_JS
    assert "record.hub_id === entry.hub_id && record.entry_id === entry.id" in PAGE_JS
    assert "serviceNotes[noteKey]" in PAGE_JS
    assert "serviceNotes.ai" not in PAGE_JS


def test_a_saved_config_is_sent_at_once_only_for_the_gateway_in_use():
    body = PAGE_JS.split("function drawAiEntry(card, state, hub, entry)")[1].split(
        "\n}"
    )[0]
    dialog = PAGE_JS.split("function openConfigDialog(staged, models, onSave)")[1]

    assert "() => { if (isInUse) askAiUse(hub, entry, true, noteKey); });" in body
    assert "onSave();" in dialog.split("save.onclick")[1].split("};")[0]
    assert "entryRow(hub, entry, payload.endpoint || '', note)" in body


def test_leaving_a_text_field_lets_a_held_state_draw():
    # The join link, the login pair, and the mount path.
    assert PAGE_JS.count("onblur = settle;") == 3


def test_one_tab_per_service_type():
    for stem, kind, heading, builder, empty in SERVICE_PANELS:
        assert EN_WORDS[f"ui.panel_{stem}"] == heading
        assert EN_WORDS[f"ui.empty_{stem}"] == empty
        assert f"['{kind}', 'ui.panel_{stem}', {builder}, 'ui.empty_{stem}']" in (
            PAGE_JS
        )


def test_the_kinds_stand_in_their_fixed_order():
    kinds = PAGE_JS.split("const KINDS = [")[1].split("];")[0]
    drawn = re.findall(r"\['([a-z]+)', 'ui\.panel_", kinds)

    assert drawn == [kind for _, kind, _, _, _ in SERVICE_PANELS]
    assert drawn == ["web", "port", "ai", "file", "rdp"]


def test_a_panel_with_no_entry_of_its_kind_draws_its_empty_line_once():
    body = PAGE_JS.split("function kindTab(state, kind)")[1].split("\n}")[0]

    assert "if (count === 0) card.appendChild(emptyRow(t(emptyKey)));" in body
    assert "function emptyRow(line)" in PAGE_JS
    assert "emptyPanel" not in PAGE_JS
    assert "services_empty" not in PAGE_JS


# --- the virtual network chip and the colour tiers ---


def test_a_hub_row_carries_the_virtual_network_chip_between_body_and_leave():
    body = PAGE_JS.split("function hubRow(hub)")[1].split("\n}")[0]
    chip = PAGE_JS.split("function overlayChip(hub)")[1].split("\n}")[0]
    asking = PAGE_JS.split("function askOverlay(hub, isOn)")[1].split("\n}")[0]

    assert body.index("row.appendChild(body);") < body.index("overlayChip(hub)")
    assert body.index("overlayChip(hub)") < body.index("row.appendChild(leave);")
    assert "if (!overlay) return null;" in chip
    assert "chip.className = isOn ? 'chip on' : 'chip';" in chip
    assert "chip.disabled = isMoving || isWorking || isHeld(hub);" in chip
    assert "marker(isMoving ? 'spin' : overlayTone(overlay))" in chip
    assert "connection_state" not in chip
    assert "isOn ? '/api/overlay/leave' : '/api/overlay/join'" in asking
    assert "{ hub_id: key }" in asking
    assert "wordCode(overlay.code, overlay.params)" in body
    assert EN_WORDS["ui.overlay"] == "Virtual network"
    assert CATALOGS["zh-CN"]["ui.overlay"] == "虚拟网"


def test_every_overlay_state_has_a_word():
    from neutrino_client.core.overlay import OVERLAY_STATES

    listed = PAGE_JS.split("const OVERLAY_STATES = [")[1].split("];")[0]
    assert re.findall(r"'([a-z]+)'", listed) == list(OVERLAY_STATES)
    for state in OVERLAY_STATES:
        assert EN_WORDS[f"ui.overlay_{state}"]
        assert CATALOGS["zh-CN"][f"ui.overlay_{state}"]
    for state in ("on", "joining", "leaving"):
        assert EN_WORDS[f"state.{state}"]


def code_tones() -> dict:
    """The page's code-to-colour table."""
    listed = PAGE_JS.split("const CODE_TONES = {")[1].split("};")[0]
    return dict(re.findall(r"([a-z_]+): '([a-z]+)'", listed))


# The codes a hub row or a chip can carry, and the colour each must be.
AMBER_CODES = {
    "hub_unreachable",
    "client_disabled",
    "overlay_other_network",
    "overlay_not_authorized",
}
RED_CODES = {
    "hub_untrusted",
    "binding_unknown",
    "protocol_too_old",
    "protocol_too_new",
    "hub_refused",
    "hub_reply_unreadable",
    "bundle_missing",
    "overlay_daemon_down",
    "overlay_join_failed",
}


def test_every_code_a_row_or_a_chip_carries_has_its_colour():
    tones = code_tones()
    overlay_codes = {
        code for code in catalog_keys("code.") if code.startswith("overlay_")
    }
    hub_codes = {
        "hello_invalid",
        "role_mismatch",
        "hub_unreachable",
        "hub_untrusted",
        "hub_refused",
        "hub_reply_unreadable",
        "binding_unknown",
        "client_disabled",
        "protocol_too_old",
        "protocol_too_new",
    }

    assert (overlay_codes | hub_codes | AMBER_CODES | RED_CODES) <= set(tones)
    for code in AMBER_CODES:
        assert tones[code] == "wait", code
    for code in RED_CODES:
        assert tones[code] == "bad", code
    assert set(tones.values()) <= {"wait", "bad"}


def test_the_hub_row_colours_by_the_fixed_tiers():
    tone = PAGE_JS.split("function hubTone(hub)")[1].split("\n}")[0]

    assert (
        "if (hub.connection_state === 'connected' && !hub.is_disabled) return 'ok';"
        in (tone)
    )
    assert "if (code) return codeTone(code);" in tone
    assert "return hub.hub_software ? 'spin' : 'off';" in tone
    assert "row.innerHTML = marker(tone);" in PAGE_JS
    for token in ("--color-signal-ok", "--color-signal-warn", "--color-signal-error"):
        assert token in PAGE_CSS
    assert ".spin.warn { border-top-color: var(--color-signal-warn); }" in PAGE_CSS


def test_the_ai_switch_sends_the_toggle_and_the_tool_configs_together():
    assert "tool_configs: ensureAiStaged(lastState).tool_configs," in PAGE_JS
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
    body = PAGE_JS.split("function drawDesktopEntry")[1].split("\n}")[0]
    assert "{ action: 'connect', hub_id: entry.hub_id, id: entry.id }" in body
    assert "password" not in body
    assert "share" not in body


# --- the language and the theme on the settings dialog ---


def test_the_header_button_opens_the_settings_dialog_with_the_language():
    body = PAGE_JS.split("function openSettingsDialog()")[1].split("\n}")[0]

    assert 'id="settings"' in PAGE_HTML
    assert "settings.onclick = openSettingsDialog;" in PAGE_JS
    assert "t('ui.settings_title')" in body
    assert "picker('language', languageOptions, draft.language" in body
    assert "send('/api/language', { language: draft.language })" in body
    assert "t('ui.save')" in body and "t('ui.cancel')" in body
    assert "ui.close" not in body
    assert "LANGUAGES.map(" in body
    assert "languageRow" not in PAGE_JS
    assert EN_WORDS["ui.language"] == "Language"
    for language in CLIENT_LANGUAGES:
        assert EN_WORDS[f"ui.language_name.{language}"]


def test_the_page_words_itself_in_the_language_the_state_names():
    assert "setLanguage(state.language);" in PAGE_JS
    assert "document.documentElement.lang = language;" in PAGE_JS


def test_the_settings_dialog_carries_the_theme_after_the_language():
    body = PAGE_JS.split("function openSettingsDialog()")[1].split("\n}")[0]

    assert body.index("picker('language'") < body.index("picker('theme'")
    assert "picker('theme', themeOptions, draft.theme" in body
    assert "send('/api/theme', { theme: draft.theme })" in body
    assert "THEMES.map(" in body
    assert EN_WORDS["ui.theme"] == "Theme"
    for theme in CLIENT_THEMES:
        assert EN_WORDS[f"ui.theme_name.{theme}"]


def test_the_page_draws_itself_in_the_theme_the_state_names():
    assert "setTheme(state.theme);" in PAGE_JS
    assert "const THEMES = ['system', 'dark', 'light'];" in PAGE_JS
    assert list(CLIENT_THEMES) == ["system", "dark", "light"]
    assert "document.documentElement.dataset.theme" in PAGE_JS
    assert "window.matchMedia('(prefers-color-scheme: dark)')" in PAGE_JS


def test_the_window_carries_both_palettes_and_starts_dark():
    assert 'data-theme="dark"' in PAGE_HTML
    assert '[data-theme="dark"] {' in PAGE_CSS
    assert '[data-theme="light"] {' in PAGE_CSS
    assert "html { color-scheme: var(--color-scheme); }" in PAGE_CSS


# --- greyed, never hidden ---


def test_an_unhealthy_entry_is_greyed_never_dropped():
    assert "'feat' : 'feat greyed'" in PAGE_JS
    assert EN_WORDS["ui.unhealthy"] == "not reachable now"


def test_everything_of_a_hub_greys_while_it_has_the_client_switched_off():
    assert "function isHeld(hub)" in PAGE_JS
    assert PAGE_JS.count("isHeld(hub)") >= 6
    assert "isHeld(state)" not in PAGE_JS
    assert EN_WORDS["ui.disabled"] == "Switched off by the hub"


def test_a_replaced_socket_shows_its_state_and_one_reconnect_button():
    body = PAGE_JS.split("function hubRow(hub)")[1].split("\n}")[0]

    assert "hub.connection_state === 'replaced'" in body
    assert "t('state.replaced')" in body
    assert "reconnect.textContent = t('ui.reconnect');" in body
    assert "send('/api/session/start', { hub_id: hubKey(hub) })" in body
    assert body.count("t('ui.reconnect')") == 1
    assert EN_WORDS["state.replaced"] == "Replaced by another client"
    assert EN_WORDS["ui.reconnect"] == "Reconnect"


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
    assert "if (serialized === lastSerialized) return false;" in PAGE_JS
    assert "getSelection" in PAGE_JS
    assert "activeElement" in PAGE_JS
    assert "openDialogs > 0" in PAGE_JS


def test_a_deferred_payload_is_replayed_when_the_guard_lifts():
    assert "pendingState = state; return false;" in PAGE_JS
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
    assert "work.step === 'connecting:' + serviceKey(entry)" in PAGE_JS
    assert EN_WORDS["code.busy"]


def test_a_failed_switch_leaves_the_switch_live_for_the_same_ask_again():
    body = PAGE_JS.split("function drawAiEntry(card, state, hub, entry)")[1].split(
        "\n}"
    )[0]
    assert "toggle.disabled = !entry.is_healthy || isHeld(hub) || isWorking;" in body
    assert "if (isExit && work.code) notes.push(wordCode(work.code, work.params));" in (
        body
    )


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


def test_an_entrys_origin_is_worded_from_its_code_with_the_sentence_as_fallback():
    """The hub sends a description code; an older hub sends only English."""
    assert "function describeEntry(entry)" in PAGE_JS
    assert "hasWord('ui.description.' + code)" in PAGE_JS
    assert "return entry.description || '';" in PAGE_JS
    for code in (
        "ai_gateway",
        "container",
        "declared",
        "device_share",
        "gitea_module",
        "samba_module",
    ):
        assert code in catalog_keys("ui.description.")


# --- the terminals page ---


def function_body(signature: str) -> str:
    """One top-level function's body, up to its closing brace."""
    return PAGE_JS.split(signature)[1].split("\n}")[0]


def test_the_terminals_page_is_a_machine_strip_over_a_panel_of_shells():
    body = function_body("function drawTerminals(state)")
    strip = function_body("function machineStrip(state)")

    assert "page.appendChild(machineStrip(state));" in body
    assert "page.appendChild(shellPanel());" in body
    assert body.index("machineStrip(state)") < body.index("shellPanel()")
    assert "machine.hub_id === hub.hub_id" in strip
    assert "chip.innerHTML = marker(machine.is_online ? 'ok' : 'off');" in strip
    assert "open.textContent = t('ui.terminal_new');" in strip
    assert (
        "open.disabled = !picked || !picked.machine.is_online || isHeld(picked.hub);"
        in strip
    )
    assert "card.appendChild(emptyRow(t('ui.empty_terminals')));" in strip
    assert (EN_WORDS["ui.terminal_new"], CATALOGS["zh-CN"]["ui.terminal_new"]) == (
        "New terminal",
        "新终端",
    )


def test_each_open_shell_is_a_tab_that_closes_its_shell():
    panel = function_body("function shellPanel()")
    tab = function_body("function shellTabButton(tab)")
    closing = function_body("function closeShell(tab)")
    tone = function_body("function shellTone(tab)")

    assert "for (const tab of shellTabs) head.appendChild(shellTabButton(tab));" in (
        panel
    )
    assert "panel.appendChild(shellSurfaceElement());" in panel
    assert "wrap.className = tab.key === activeShell ? 'term_tab on' : 'term_tab';" in (
        tab
    )
    assert "close.onclick = () => closeShell(tab);" in tab
    assert "api('/api/terminal/close', { terminal_id: tab.terminal_id });" in closing
    assert "if (tab.state === 'connecting') return 'spin';" in tone
    assert "return tab.isRefused ? 'bad' : 'off';" in tone
    assert EN_WORDS["ui.terminal_close"] == "Close {name}"


def test_a_shell_is_xterm_fitted_to_its_pane_and_opened_at_that_size():
    body = function_body("function openShell(hub, machine)")
    fit = function_body("function fitShell(tab)")

    assert "const term = new Terminal({" in body
    assert "const fit = new FitAddon.FitAddon();" in body
    assert body.index("term.open(pane);") < body.index("api('/api/terminal/open'")
    assert "cols: term.cols, rows: term.rows," in body
    assert "term.onData((data) => sendShellKeys(tab, data));" in body
    assert "api('/api/terminal/resize'," in body
    assert "proposed.cols === tab.term.cols && proposed.rows === tab.term.rows" in fit
    assert "new ResizeObserver(fitActiveShell).observe(shellSurface);" in PAGE_JS


def test_keys_go_one_request_at_a_time_and_output_comes_as_pushed_pieces():
    flush = function_body("function flushShellKeys(tab)")
    push = PAGE_JS.split("window.neutrinoState = (state) => {")[1].split("\n};")[0]
    piece = function_body("function takeShellPiece(piece)")

    assert "api('/api/terminal/input', { terminal_id: tab.terminal_id, data: " in flush
    assert ".then(() => flushShellKeys(tab));" in flush
    assert "if (state.terminal) { takeShellPiece(state.terminal); return; }" in push
    assert push.index("state.terminal") < push.index("present(state)")
    assert "tab.term.write(base64Bytes(piece.data));" in piece
    assert "earlyOutput[piece.id]" in piece


def test_the_shells_panes_outlive_a_redraw():
    surface = function_body("function shellSurfaceElement()")

    assert "if (!shellSurface) {" in surface
    assert "addEventListener('focusout'" in surface
    assert "const shellTabs = [];" in PAGE_JS


def test_nothing_launches_a_system_terminal_any_more():
    assert "/api/terminal/launch" not in PAGE_JS
    assert "ui.terminal_open" not in EN_WORDS
    assert "code.terminal_app_missing" not in EN_WORDS
    assert "askTerminal" not in PAGE_JS


def test_xterm_and_its_fit_addon_are_vendored_and_inlined():
    assert '<link rel="stylesheet" href="vendor/xterm.css">' in PAGE_HTML
    assert PAGE_HTML.index('src="vendor/xterm.js"') < PAGE_HTML.index(
        'src="vendor/addon-fit.js"'
    )
    assert PAGE_HTML.index('src="vendor/addon-fit.js"') < PAGE_HTML.index(
        'src="app.js"'
    )
    assert page.gui_asset("vendor/xterm.js").startswith("/* @xterm/xterm 5.5.0")
    assert page.gui_asset("vendor/addon-fit.js").startswith(
        "/* @xterm/addon-fit 0.10.0"
    )

    document = page.control_page_html()

    assert "<script src=" not in document
    assert "sourceMappingURL" not in document
    assert ".xterm-viewport" in document
