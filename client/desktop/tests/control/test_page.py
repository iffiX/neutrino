"""The page's contract, checked on the frontend files it ships.

The page is plain HTML, CSS and JavaScript under ``client/desktop/frontend/``,
so what can be checked here is the contract's visible surface: the sidebar in
its order with a glyph on every entry and the settings entry below a rule, one
hub row per hub and the join row always there, the Apps page with one row per
app and its local port dialog, one panel per kind listing every hub's entries
in hub order with the line each carries while nothing is offered, every
entry's one provider line, the one AI switch, the staging keyed by service
key, the account picker of the terminals, the settings switch, the redraw
guards, the bridge adapter with no direct network reach, no word from outside
read as markup, and the word catalogs asserted complete: the two languages
carry the same keys, every key the page asks for is in them, and every
``{code}`` and every state token the client can emit is enumerated from the
source and must have a wording, so a new code or state without a word fails
this suite. Nothing of the agent's Modules section is left.
"""

import hashlib
import pathlib
import re

import pytest

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

# The words of client.md, by key, in both catalogs.
CONNECTION_STATES = (
    "connected",
    "connecting",
    "waiting",
    "replaced",
    "disabled",
)
WAIT_REASONS = (
    "hub_silent",
    "hub_off_overlay",
    "no_network",
    "untrusted",
    "admission_paused",
    "unknown_device",
    "too_old",
    "join_refused",
)
OVERLAY_STATES = ("off", "on")
JOB_WORDS = (
    "refreshing",
    "connecting",
    "disconnecting",
    "leaving",
    "joining",
    "mounting",
    "unmounting",
    "forwarding",
    "switching",
    "opening",
)
CLIENT_MD_WORDS = {
    "ui.state.connected": "Connected",
    "ui.state.connecting": "Connecting…",
    "ui.state.hub_silent": "The hub did not answer",
    "ui.state.hub_off_overlay": "The hub is not on the virtual network",
    "ui.state.no_network": "No network",
    "ui.state.untrusted": "Hub key mismatch",
    "ui.state.admission_paused": "The hub pauses new devices",
    "ui.state.unknown_device": "The hub does not know this device",
    "ui.state.too_old": "Version too old",
    "ui.action.update_client": "update the client",
    "ui.state.join_refused": "Join refused",
    "ui.action.retry_in": "retrying in {s} s",
    "ui.state.replaced": "Replaced by another client",
    "ui.state.disabled": "Disabled by the hub",
    "ui.overlay.off": "Not connected",
    "ui.overlay.on": "Connected · {address}",
    "ui.job.refreshing": "Refreshing…",
    "ui.job.connecting": "Connecting…",
    "ui.job.disconnecting": "Disconnecting…",
    "ui.job.leaving": "Leaving…",
    "ui.job.joining": "Joining…",
    "ui.job.mounting": "Mounting…",
    "ui.job.unmounting": "Unmounting…",
    "ui.job.forwarding": "Forwarding…",
    "ui.job.switching": "Switching tools…",
    "ui.job.opening": "Opening…",
}
# The Chinese column of client.md's Hubs table.
CLIENT_MD_CHINESE = {
    "ui.state.connecting": "连接中…",
    "ui.state.hub_silent": "中枢未响应",
    "ui.state.hub_off_overlay": "中枢未上虚拟网",
    "ui.state.no_network": "无网络",
    "ui.state.untrusted": "中枢密钥不符",
    "ui.state.admission_paused": "中枢暂停接纳",
    "ui.state.unknown_device": "中枢不认识本机",
    "ui.state.too_old": "版本太旧",
    "ui.action.update_client": "更新客户端",
    "ui.state.join_refused": "加入被拒",
    "ui.action.retry_in": "{s} 秒后重试",
    "ui.state.replaced": "已被替换",
    "ui.state.disabled": "已停用",
}

# The kinds with a page of their own, in the order the sidebar lists them:
# the catalog key stem, the type on the wire, the heading, the function
# drawing one entry, and the line the panel carries while no hub publishes
# the kind.
SERVICE_PANELS = (
    ("ai", "ai", "AI", "drawAiEntry", "No AI service yet"),
    ("files", "file", "Files", "drawFileEntry", "No shares yet"),
    (
        "desktops",
        "rdp",
        "Remote desktops",
        "drawDesktopEntry",
        "No shared remote desktops yet",
    ),
)

# The sidebar's entries, top to bottom, by their title's key.
SIDEBAR_KEYS = (
    "ui.section_hubs",
    "ui.panel_apps",
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
# states entry, and the one it words as its job.
ATTACH_RENDERED_STATES = {"mounted", "detached", "unmounting"}


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
    assert "parts" not in PAGE_HTML

    document = page.control_page_html()

    assert "href=" not in document.split("<body>")[0].split("<title>")[1]
    assert "NEUTRINO_PARTS" not in PAGE_JS
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
    assert page.GUI_SOURCE_DIR.parent.name == "desktop"
    assert words.locales_dir() == words.LOCALES_SOURCE_DIR


# --- the catalogs are complete, and the page asks for nothing else ---


def test_both_languages_carry_the_same_keys():
    assert set(CATALOGS) == set(CLIENT_LANGUAGES)
    assert set(CATALOGS["zh-CN"]) == set(EN_WORDS)


def test_every_key_the_page_asks_for_is_in_the_catalog():
    # What the page builds from a token, which no whole literal carries.
    built = {f"ui.job.{job}" for job in JOB_WORDS}
    built |= {f"ui.state.{state}" for state in CONNECTION_STATES if state != "waiting"}
    built |= {f"ui.state.{reason}" for reason in WAIT_REASONS}
    built |= {f"ui.overlay.{state}" for state in OVERLAY_STATES}
    built |= {f"ui.language_name.{language}" for language in CLIENT_LANGUAGES}
    built |= {f"ui.theme_name.{theme}" for theme in CLIENT_THEMES}
    built |= {f"ui.app_source.{source}" for source in ("module", "declared", "manual")}
    built |= {f"ui.entry_kind.{kind}" for kind in ("web", "port", "ssh")}

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
    assert EN_WORDS["ui.not_attached"] == "Not mounted"
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
        "This hub no longer knows this client; join it again with a new link"
    )
    assert EN_WORDS["code.hub_untrusted"] == (
        "The hub's key does not match; if it was reset, join it again."
    )


def test_every_line_a_code_or_a_row_word_draws_starts_with_a_capital():
    row_words = (
        "ui.ai_on",
        "ui.healthy",
        "ui.hub_is_exit",
        "ui.not_attached",
        "ui.rdp_open",
        "ui.unhealthy",
    )
    for key, wording in EN_WORDS.items():
        if key.startswith("code.") or key in row_words:
            assert wording[:1] == wording[:1].upper(), key


def test_a_desktop_row_says_its_health_or_that_its_viewer_is_open():
    desktop = body_of("drawDesktopEntry")
    assert "isOpen ? t('ui.rdp_open') : t('ui.healthy')" in desktop
    assert EN_WORDS["ui.healthy"] == "Reachable"
    assert EN_WORDS["ui.rdp_open"] == "Viewer open"


# --- the two sections and the five panels ---


def test_a_sidebar_lists_the_hubs_and_every_kind_and_nothing_of_modules_is_left():
    side = PAGE_HTML.split('<aside class="side">')[1].split("</aside>")[0]
    head = PAGE_HTML.split('<div class="head">')[1].split('<div id="content">')[0]

    assert '<nav id="tabs"></nav>' in side
    assert "<h1>" in side
    assert 'id="refresh"' in head
    assert 'id="settings"' not in PAGE_HTML
    assert head.index('id="page_title"') < head.index('id="refresh"')
    assert '<div id="content"></div>' in PAGE_HTML
    assert "const TABS = ['hubs', 'apps', 'ai', 'file', 'terminals', 'rdp'];" in (
        PAGE_JS
    )
    assert [EN_WORDS[key] for key in SIDEBAR_KEYS] == [
        "Hubs",
        "Apps",
        "AI",
        "Files",
        "Terminals",
        "Remote desktops",
    ]
    assert [CATALOGS["zh-CN"][key] for key in SIDEBAR_KEYS] == [
        "中枢",
        "应用",
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
        "drawWebEntry",
        "drawPortEntry",
        "ui.panel_web",
        "ui.panel_ports",
        "/api/forward/configure",
        "/api/services/web",
        "/api/services/port",
    ):
        assert gone not in PAGE_JS, gone
    assert "ui.section_services" not in EN_WORDS
    for gone in ("ui.panel_web", "ui.panel_ports", "ui.empty_web", "ui.empty_ports"):
        assert gone not in EN_WORDS and gone not in CATALOGS["zh-CN"], gone


def test_every_sidebar_entry_carries_its_glyph_before_its_name():
    tab = PAGE_JS.split("function tabButton(tab)")[1].split("\n}")[0]
    glyphs = PAGE_JS.split("const TAB_ICONS = {")[1].split("};")[0]
    shapes = PAGE_JS.split("const ICON_SHAPES = {")[1].split("};")[0]
    drawing = PAGE_JS.split("function icon(name, size)")[1].split("\n}")[0]

    attributes = PAGE_JS.split("const ICON_ATTRIBUTES = {")[1].split("};")[0]

    assert tab.index("icon(TAB_ICONS[tab], 17)") < tab.index("tabTitle(tab)")
    assert "button.appendChild(icon(TAB_ICONS[tab], 17));" in tab
    assert dict(re.findall(r"([a-z]+): '([a-z]+)'", glyphs)) == {
        "hubs": "server",
        "apps": "grid",
        "ai": "sparkles",
        "file": "folder",
        "terminals": "terminal",
        "rdp": "desktop",
        "settings": "settings",
    }
    for name in ("server", "grid", "sparkles", "folder", "terminal", "desktop"):
        assert f"  {name}: [" in shapes, name
    assert "  settings: [" in shapes
    assert "stroke: 'currentColor', 'stroke-width': '1.6'," in attributes
    assert "viewBox: '0 0 24 24'" in attributes
    assert "document.createElementNS(SVG_NAMESPACE, 'svg')" in drawing
    assert "document.createElementNS(SVG_NAMESPACE, tag)" in drawing
    assert "button.tab { position: relative; display: flex; gap: 12px;" in PAGE_CSS


def test_the_settings_entry_stands_below_a_rule_after_the_kinds():
    tabs = PAGE_JS.split("function drawTabs()")[1].split("\n}")[0]

    assert "for (const tab of TABS) nav.appendChild(tabButton(tab));" in tabs
    assert tabs.index("rule.className = 'tab_rule';") < tabs.index(
        "nav.appendChild(tabButton('settings'));"
    )
    assert "if (tab === 'settings') return t('ui.settings');" in PAGE_JS
    rule = PAGE_CSS.split(".tab_rule {")[1].split("}")[0]
    assert "border-top: 1px solid var(--color-border)" in rule
    assert (EN_WORDS["ui.settings"], CATALOGS["zh-CN"]["ui.settings"]) == (
        "Settings",
        "设置",
    )


def test_the_open_sidebar_entry_is_washed_in_the_accent_without_a_glow():
    assert "button.tab {" in PAGE_CSS
    tab_on = PAGE_CSS.split("button.tab.on {")[1].split("}")[0]
    bar = PAGE_CSS.split("button.tab.on::before {")[1].split("}")[0]
    assert "color: var(--color-accent)" in tab_on
    assert "var(--color-accent)" in bar
    assert "box-shadow" not in tab_on and "box-shadow" not in bar


def test_a_row_whose_actions_do_not_fit_puts_them_on_a_line_of_their_own():
    """The narrow window of a small screen: Leave and Join stay in reach."""
    row = PAGE_CSS.split(".feat {")[1].split("}")[0]
    body = PAGE_CSS.split(".feat .body {")[1].split("}")[0]
    actions = PAGE_CSS.split(".row_actions {")[1].split("}")[0]

    assert "flex-wrap: wrap" in row
    assert "flex: 1 1 200px" in body and "min-width: 0" in body
    assert "flex: 0 1 auto" in actions and "flex-wrap: wrap" in actions
    assert "margin-left: auto" in actions


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


def test_a_hub_row_carries_no_target_radio_and_names_the_hub_the_tools_use():
    body = PAGE_JS.split("function hubRow(hub, isOtherNetworkInUse)")[1].split("\n}")[0]

    assert "radio" not in PAGE_JS
    assert "ui.hub_exit" not in EN_WORDS
    assert "t('ui.hub_is_exit')" in body
    assert EN_WORDS["ui.hub_is_exit"] == "The AI tools point at this hub"


def test_a_connected_hub_row_shows_its_way_in_and_its_round_trip_as_tags():
    tags = PAGE_JS.split("function hubTags(hub)")[1].split("\n}")[0]
    row = PAGE_JS.split("function hubRow(hub, isOtherNetworkInUse)")[1].split("\n}")[0]

    assert "hub.connection !== 'connected'" in tags
    assert "t('ui.state.rtt', { ms: Math.round(hub.rtt_ms) })" in tags
    assert "tags: tags," in row
    assert CATALOGS["en"]["ui.state.rtt"] == CATALOGS["zh-CN"]["ui.state.rtt"]
    assert EN_WORDS["ui.state.rtt"] == "{ms} ms"


def test_a_client_too_old_for_its_hub_says_to_update_the_client():
    wait = PAGE_JS.split("function waitWord(hub)")[1].split("\n}")[0]

    assert "hub.wait_code.code === 'protocol_too_old'" in wait
    assert "return word + ' · ' + t('ui.action.update_client');" in wait


def test_a_hub_is_keyed_by_its_id_and_by_its_binding_before_a_welcome():
    assert "function hubKey(hub) {\n  return hub.hub_id || hub.binding_id;" in PAGE_JS
    assert "function serviceKey(entry) {\n  return entry.hub_id + '/' + entry.id;" in (
        PAGE_JS
    )


# --- one panel per kind, in hub order ---


def test_every_action_names_the_entrys_hub():
    for sent in (
        "{ action: 'connect', hub_id: entry.hub_id, id: entry.id }",
        "{ action: 'mount', hub_id: entry.hub_id, id: entry.id, path: '' }",
        "{ action: 'mount', hub_id: entry.hub_id, id: entry.id, path: staged.path }",
        "{ action: 'mount', hub_id: entry.hub_id, record_id: record.record_id }",
        "{ action: 'unmount', hub_id: entry.hub_id, record_id: record.record_id }",
        "action: 'set', hub_id: entry.hub_id, record_id: record.record_id,",
        "hub_id: entry.hub_id,\n    is_enabled: isOn,",
        "{ hub_id: app.hub_id, app_id: app.id }",
        "{ hub_id: app.hub_id, app_id: app.id, ports: changes() }",
    ):
        assert sent in PAGE_JS, sent


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
    assert drawn == ["ai", "file", "rdp"]


def test_a_panel_with_no_entry_of_its_kind_draws_its_empty_line_once():
    body = PAGE_JS.split("function kindTab(state, kind)")[1].split("\n}")[0]

    assert "if (count === 0) card.appendChild(emptyRow(t(emptyKey)));" in body
    assert "function emptyRow(line)" in PAGE_JS
    assert "emptyPanel" not in PAGE_JS
    assert "services_empty" not in PAGE_JS


# --- the virtual network chip and the colour tiers ---


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


# --- the language and the theme on the settings page ---


def test_the_page_words_itself_in_the_language_the_state_names():
    assert "setLanguage(state.language);" in PAGE_JS
    assert "document.documentElement.lang = language;" in PAGE_JS


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
        "'terminal_account'",
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


def test_a_pickers_list_opens_above_its_field_when_there_is_no_room_under_it():
    """The theme picker at the foot of Settings: every choice stays in the window."""
    picker_body = PAGE_JS[
        PAGE_JS.index("function picker(") : PAGE_JS.index("function placeList(")
    ]
    place = PAGE_JS.split("function placeList(wrap, list) {")[1].split("\n}\n")[0]
    above = PAGE_CSS.split(".picker_list.above {")[1].split("}")[0]

    assert "placeList(wrap, list)" in picker_body
    assert "window.innerHeight" in place
    assert "overflowY === 'visible'" in place
    assert "below < height && above > below" in place
    assert "list.classList.toggle('above', isAbove);" in place
    assert "Math.max(PICKER_LIST_LEAST_PX, room)" in place
    assert "top: auto" in above and "bottom: calc(100% + 4px)" in above


# --- busy states spin ---


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


def test_a_sent_mount_keeps_its_form_until_the_share_is_mounted():
    button = body_of("mountButton")
    assert "staged.password = '';" not in PAGE_JS
    assert "delete fileStaged[serviceKey(entry)];" not in button
    assert "button.onclick = () => sendFileMount(entry, staged);" in button
    sent = body_of("sendFileMount")
    assert "staged.is_open = false;\n  staged.is_sent = true;" in sent
    files = body_of("drawFileEntry")
    assert (
        "if (record && record.is_attached && !entry.job && fileStaged[key]\n"
        "    && fileStaged[key].is_sent && !fileStaged[key].is_open) {\n"
        "    delete fileStaged[key];" in files
    )


def test_the_files_form_has_save_and_cancel_and_the_button_says_configure():
    form = body_of("drawFileForm")
    assert "save.textContent = t('ui.save');" in form
    assert "cancel.textContent = t('ui.cancel');" in form
    assert "cancel.onclick = () => { cancelFileForm(key); redraw(); };" in form
    assert "staged.before = null;" in form
    assert "Object.assign({}, staged.before, { is_open: false })" in body_of(
        "cancelFileForm"
    )
    assert "t('ui.configure')" in body_of("drawFileEntry")
    assert "t('ui.configure')" in body_of("drawAiEntry")
    assert "ui.config'" not in PAGE_JS
    assert "ui.config" not in EN_WORDS
    for wording in EN_WORDS.values():
        assert "Config " not in wording and not wording.endswith("Config")


def test_the_reason_line_follows_the_mount_button():
    reason = body_of("mountReason")
    assert "if (!mount.disabled || entryWork(hub, entry)) return '';" in reason
    files = body_of("drawFileEntry")
    assert "setReasonLine(row, mountReason(hub, entry, record, mount));" in files
    assert "if (line) line.remove();" in body_of("setReasonLine")


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


def test_an_entrys_module_is_named_from_its_origin_code_and_its_title_behind():
    """The hub sends an origin code; a declared record and an older hub name
    the entry by its own title."""
    body = PAGE_JS.split("function entryModule(entry)")[1].split("\n}")[0]
    modules = PAGE_JS.split("const ENTRY_MODULES = {")[1].split("};")[0]
    keys = PAGE_JS.split("const ENTRY_MODULE_KEYS = {")[1].split("};")[0]

    assert dict(re.findall(r"([a-z_]+): '([A-Za-z -]+)'", modules)) == {
        "gitea_module": "Gitea",
        "vscode_module": "VS Code",
        "code_server_module": "code-server",
        "cloudcli_module": "CloudCLI",
        "codeg_module": "Codeg",
    }
    assert dict(re.findall(r"([a-z_]+): '([a-z_.]+)'", keys)) == {
        "ai_gateway": "ui.module_ai_gateway",
        "samba_module": "ui.module_title.samba",
        "device_share": "ui.module_title.remote_desktop",
    }
    assert "if (ENTRY_MODULE_KEYS[code]) return t(ENTRY_MODULE_KEYS[code]);" in body
    assert "(entry.description_params || {}).image" in body
    assert "return ENTRY_MODULES[code] || entry.title;" in body
    assert [
        (EN_WORDS[key], CATALOGS["zh-CN"][key])
        for key in (
            "ui.module_ai_gateway",
            "ui.module_title.samba",
            "ui.module_title.remote_desktop",
        )
    ] == [
        ("AI gateway", "AI 网关"),
        ("File share", "文件共享"),
        ("Remote desktop", "远程桌面"),
    ]
    assert catalog_keys("ui.description.") == set()


# --- the terminals page ---


def function_body(signature: str) -> str:
    """One top-level function's body, up to its closing brace."""
    return PAGE_JS.split(signature)[1].split("\n}")[0]


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


def test_the_menus_clear_sends_ctrl_c_before_it_clears_the_screen():
    menu = function_body("function openTerminalMenu(tab, x, y)")
    clear = function_body("function clearTerminal(tab)")

    assert "[t('ui.menu.clear'), false, () => clearTerminal(tab)]," in menu
    assert "showClearing(tab, true);" in clear
    assert "tab.isClearAsked = true;" in clear
    flush = function_body("function flushShellKeys(tab)")
    # What was typed before the Clear goes first; the resident sends Ctrl+C.
    assert flush.index("if (!tab.typed && tab.isClearAsked) {") < flush.index(
        "const text = tab.typed;"
    )
    assert "api('/api/terminal/clear', { terminal_id: tab.terminal_id })" in flush


def test_the_clearing_word_covers_the_terminal_while_the_resident_drops():
    piece = function_body("function takeShellPiece(piece)")
    assert "if (piece.clearing !== undefined) {" in piece
    assert "showClearing(tab, piece.clearing === true);" in piece
    # Output read before the drop began reaches the page after it began, and
    # is not drawn.
    assert "if (!tab.isClearing) tab.term.write(base64Bytes(piece.data));" in piece
    assert "if (tab.isClearing) showClearing(tab, false);" in piece
    shown = function_body("function showClearing(tab, isClearing)")
    assert "t('ui.job.clearing')" in shown
    assert "tab.isClearing = isClearing;" in shown
    assert "tab.term.write(TERMINAL_ERASE);" in shown
    assert "const TERMINAL_ERASE = '\\x1b[2J\\x1b[3J\\x1b[H';" in PAGE_JS
    flush = function_body("function flushShellKeys(tab)")
    assert "if (!reply || reply.code) showClearing(tab, false);" in flush
    assert EN_WORDS["ui.job.clearing"] == "Clearing…"
    assert CATALOGS["zh-CN"]["ui.job.clearing"] == "清屏中…"
    assert ".term_clearing {" in PAGE_CSS


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


# The 16 ANSI colours of client.md's terminal colours table, by xterm.js's key.
TERMINAL_PALETTE = {
    "black": "#2e3436",
    "red": "#cc0000",
    "green": "#4e9a06",
    "yellow": "#c4a000",
    "blue": "#3465a4",
    "magenta": "#75507b",
    "cyan": "#06989a",
    "white": "#d3d7cf",
    "brightBlack": "#555753",
    "brightRed": "#ef2929",
    "brightGreen": "#8ae234",
    "brightYellow": "#fce94f",
    "brightBlue": "#729fcf",
    "brightMagenta": "#ad7fa8",
    "brightCyan": "#34e2e2",
    "brightWhite": "#eeeeec",
}


def test_the_shells_draw_the_16_colours_fixed_and_the_rest_from_the_theme():
    palette = PAGE_JS.split("const TERMINAL_PALETTE = {")[1].split("};")[0]
    theme = function_body("function terminalTheme()")

    assert dict(re.findall(r"(\w+): '(#[0-9a-f]{6})'", palette)) == TERMINAL_PALETTE
    assert "}, TERMINAL_PALETTE);" in theme
    for token in ("--color-bg", "--color-text", "--color-terminal-selection"):
        assert f"token('{token}')" in theme
    assert theme.count("token('--color-accent')") == 1
    for token in ("--color-error", "--color-ok", "--color-warn"):
        assert token not in theme


def test_bold_text_keeps_its_own_colour():
    tab = function_body("function newTab(hubId, machine, sessionId)")

    assert "drawBoldTextInBrightColors: false," in tab


def test_every_open_shell_takes_a_new_theme_at_once():
    paint = function_body("function paintShells()")

    assert "paintShells();" in function_body("function setTheme(chosen)")
    assert "DARK_SCHEME.addEventListener('change', () => setTheme(theme));" in PAGE_JS
    assert (
        "for (const tab of shellTabs) tab.term.options.theme = terminalTheme();"
        in paint
    )


# --- the terminal's font and the paste ---

# The two faces as romkatv/powerlevel10k-media v2.3.3 publishes them.
MESLO_SHA256 = {
    "regular": "d97946186e97f8d7c0139e8983abf40a1d2d086924f2c5dbf1c29bd8f2c6e57d",  # scan: allow
    "bold": "b6c0199cf7c7483c8343ea020658925e6de0aeb318b89908152fcb4d19226003",  # scan: allow
}


@pytest.mark.parametrize("face", sorted(MESLO_SHA256))
def test_meslolgs_nf_is_vendored_byte_for_byte(face):
    data = (page.gui_dir() / page.GUI_TERMINAL_FONTS[face]).read_bytes()

    assert hashlib.sha256(data).hexdigest() == MESLO_SHA256[face]


def test_the_font_is_not_inlined_into_the_document():
    assert len(page.control_page_html().encode("utf-8")) < 2 * 1024 * 1024


# --- the persistent sessions ---


def body_of(name: str) -> str:
    """One function of the page's script, from its line to the next one's."""
    start = PAGE_JS.index(f"function {name}(")
    following = PAGE_JS.find("\nfunction ", start + 1)
    following_async = PAGE_JS.find("\nasync function ", start + 1)
    ends = [end for end in (following, following_async) if end > 0]
    return PAGE_JS[start : min(ends) if ends else len(PAGE_JS)]


# --- the words and the colours of client.md ---


def test_every_word_of_client_md_is_in_both_catalogs_as_written():
    for key, english in CLIENT_MD_WORDS.items():
        assert EN_WORDS[key] == english
        assert CATALOGS["zh-CN"][key]
    for key, chinese in CLIENT_MD_CHINESE.items():
        assert CATALOGS["zh-CN"][key] == chinese
    assert CATALOGS["zh-CN"]["ui.overlay.on"] == "已连接 · {address}"
    for words in CATALOGS.values():
        assert "ui.state.down" not in words and "ui.state.pending" not in words


def test_the_page_names_the_five_connections_the_reasons_and_the_network_states():
    listed = PAGE_JS.split("const CONNECTION_STATES = [")[1].split("];")[0]
    assert re.findall(r"'([a-z]+)'", listed) == list(CONNECTION_STATES)
    listed = PAGE_JS.split("const WAIT_REASONS = [")[1].split("];")[0]
    assert re.findall(r"'([a-z_]+)'", listed) == list(WAIT_REASONS)
    listed = PAGE_JS.split("const OVERLAY_STATES = [")[1].split("];")[0]
    assert re.findall(r"'([a-z]+)'", listed) == list(OVERLAY_STATES)
    from neutrino_client.core.overlay import OVERLAY_STATES as CORE_OVERLAY
    from neutrino_client.core.session import CONNECTION_STATES as CORE_CONNECTION
    from neutrino_client.core.session import WAIT_REASONS as CORE_REASONS

    assert tuple(CORE_OVERLAY) == OVERLAY_STATES
    assert tuple(CORE_CONNECTION) == CONNECTION_STATES
    assert tuple(CORE_REASONS) == WAIT_REASONS


def test_the_hub_dot_follows_the_colour_table():
    tone = body_of("hubTone")
    assert (
        "if (jobs.is_refreshing || jobs.is_leaving || jobs.overlay_job\n"
        "    || jobs.is_opening_panel) return 'pulse';" in tone
    )
    assert "if (hub.connection === 'connecting') return 'pulse';" in tone
    assert "if (hub.connection === 'connected') return 'ok';" in tone
    assert "if (PERSON_REASONS.indexOf(hub.wait_reason) >= 0) return 'bad';" in tone
    assert "hub.software" not in tone
    assert "  }\n  return 'wait';\n}" in tone
    listed = PAGE_JS.split("const PERSON_REASONS = [")[1].split("];")[0]
    assert set(re.findall(r"'([a-z_]+)'", listed)) == {
        "untrusted",
        "unknown_device",
        "too_old",
        "join_refused",
    }


def test_a_pulsing_dot_is_the_amber_one_animated():
    assert "(tone === 'pulse' ? 'wait pulse' : tone)" in PAGE_JS
    assert ".dot.pulse { animation: pulse" in PAGE_CSS


def test_the_busy_code_reaches_no_word_on_the_page():
    assert "busy" not in PAGE_JS


# --- one state, pushed ---


def test_the_page_keeps_no_refresh_timer_and_no_remembered_outcome():
    for gone in (
        "REFRESH_SPIN_MS",
        "refreshTimer",
        "leaveAsked",
        "overlayNotes",
        "serviceNotes",
        "fileAsked",
        "isHeld",
    ):
        assert gone not in PAGE_JS


def test_the_refresh_button_spins_while_any_hub_refreshes():
    refresh = body_of("drawRefresh")
    assert "if (isAnyRefreshing(state)) {" in refresh
    assert "button.disabled = true;" in refresh
    assert "button.onclick = () => send('/api/refresh', {});" in refresh


def test_every_entry_of_a_refreshing_hub_pulses_with_its_actions_off():
    assert "return isRefreshing(hub) ? 'refreshing' : '';" in body_of("entryWork")
    assert "return !entryWork(hub, entry) && hub.connection !== 'disabled';" in (
        body_of("isEntryFree")
    )
    assert "if (entryWork(hub, entry)) return 'pulse';" in body_of("entryTone")


def test_a_button_that_starts_a_job_is_its_indicator():
    button = body_of("jobButton")
    assert "button.appendChild(spinner());" in button
    assert "t('ui.job.' + job)" in button
    assert "button.disabled = true;" in button


def test_a_failed_job_is_worded_on_its_rows_error_line():
    assert "error: wordError(entry.last_error)," in body_of("entryRow")


# --- the Hubs page ---


def test_a_hub_row_draws_its_word_its_network_line_and_its_controls_in_order():
    row = body_of("hubRow")
    assert row.index("overlayPicker(hub)") < row.index(
        "overlayButton(hub, isOtherNetworkInUse)"
    )
    assert row.index("overlayButton(hub, isOtherNetworkInUse)") < row.index(
        "t('ui.reconnect')"
    )
    assert row.index("t('ui.reconnect')") < row.rindex("leaveButton(hub)")
    assert "if (hub.connection === 'replaced') {" in row
    assert "if (hub.is_exit) extras.push(noteLine(t('ui.hub_is_exit')));" in row
    word = body_of("hubWord")
    assert "if (jobs.is_leaving) return t('ui.job.leaving');" in word
    assert "if (jobs.is_refreshing) return t('ui.job.refreshing');" in word
    assert "if (connection === 'waiting') return waitWord(hub);" in word
    assert "return t('ui.state.' + connection);" in word


def test_a_join_refused_and_an_unknown_device_offer_only_leave():
    assert "LEAVE_ONLY_REASONS.indexOf(hub.wait_reason) >= 0" in body_of("isLeaveOnly")
    listed = PAGE_JS.split("const LEAVE_ONLY_REASONS = [")[1].split("];")[0]
    assert re.findall(r"'([a-z_]+)'", listed) == ["unknown_device", "join_refused"]
    row = body_of("hubRow")
    refused = row[row.index("if (isLeaveOnly(hub)) {") :]
    refused = refused[: refused.index("\n  }\n")]
    assert "actions: [leaveButton(hub)]," in refused


def test_leave_arms_on_the_first_press_and_shows_its_job():
    leave = body_of("leaveButton")
    assert (
        "if ((hub.jobs || {}).is_leaving) return jobButton('', 'leaving', 'danger');"
        in (leave)
    )
    assert "armedButton(key, t('ui.leave'), t('ui.leave_armed')," in leave
    armed = body_of("armedButton")
    assert "if (!isArmed(key)) { arm(key); return; }" in armed
    assert "const ARM_MS = 5000;" in PAGE_JS
    assert "button.danger.armed {" in PAGE_CSS
    assert "confirm(" not in PAGE_JS


def test_the_network_button_is_connect_cancel_or_disconnect():
    button = body_of("overlayButton")
    assert (
        "if (jobs.overlay_job === 'disconnecting') return jobButton('', 'disconnecting');"
        in (button)
    )
    assert "send('/api/overlay/cancel', { hub_id: key })" in button
    assert "send('/api/overlay/disconnect', { hub_id: key })" in button
    assert "send('/api/overlay/connect', { hub_id: key })" in button
    assert "/api/overlay/join" not in PAGE_JS and "/api/overlay/leave" not in PAGE_JS


def test_the_picker_shows_with_two_networks_and_picks_only_while_off():
    chooser = body_of("overlayPicker")
    assert "if (networks.length < 2) return null;" in chooser
    assert (
        "const isLocked = overlay.state !== 'off' || !!(hub.jobs || {}).overlay_job"
        in (chooser)
    )
    assert "send('/api/overlay/pick', { hub_id: key, provider: provider });" in chooser


def test_a_hub_with_one_network_names_that_engine_on_its_line():
    line = body_of("overlayLine")
    assert "const name = networks.length === 1" in line
    assert "t('ui.overlay.' + state, { address: overlay.address || '' })" in line


def test_a_disabled_network_button_says_why():
    reason = body_of("overlayReason")
    assert "t('ui.reason.disabled')" in reason
    assert "ui.reason.no_network" not in PAGE_JS
    for words in CATALOGS.values():
        assert "ui.reason.no_network" not in words


def run_hub_row(hub: dict) -> dict:
    """The page's own hubRow and overlayReason, run in node with the row's
    pieces stubbed, returning what the row is drawn with."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to run the page's script")
    script = "\n".join(
        [
            "const t = (key) => key;",
            "const noteLine = (text) => 'note:' + text;",
            "const reasonLine = (text) => ({classList: {add: () => {}},",
            "  dataset: {}, text: 'reason:' + text});",
            "const errorLine = (text) => 'error:' + text;",
            "const wordError = (error) => error.code;",
            "const overlayLine = () => 'network line';",
            "const overlayStage = () => '';",
            "const overlayPicker = () => null;",
            "const overlayButton = (hub) => ({name: 'network button',",
            "  disabled: hub.connection === 'disabled'});",
            "const panelButton = () => ({name: 'panel'});",
            "const leaveButton = () => ({name: 'leave'});",
            "const isLeaveOnly = () => false;",
            "const hubKey = (hub) => hub.hub_id || hub.binding_id;",
            "const hubTone = () => 'ok';",
            "const hubName = (hub) => hub.hub_name;",
            "const hubWord = () => 'connected';",
            "const rowElement = (options) => options;",
            "function hubTags(hub)" + function_body("function hubTags(hub)") + "\n}",
            "function hubRow(hub, isOtherNetworkInUse)"
            + function_body("function hubRow(hub, isOtherNetworkInUse)")
            + "\n}",
            "function overlayReason(hub, isOtherNetworkInUse)"
            + function_body("function overlayReason(hub, isOtherNetworkInUse)")
            + "\n}",
            "const row = hubRow(" + json.dumps(hub) + ");",
            "console.log(JSON.stringify({extras: row.extras, reason: row.reason,",
            "  actions: row.actions.map((action) => action.name),",
            "  tags: row.tags, word: row.word}));",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


HUB_ROW = {
    "hub_name": "home",
    "gateway_url": "https://hub:8443",
    "connection": "connected",
    "jobs": {},
}


def run_state_line(hub: dict, now: float) -> dict:
    """The page's own hubWord and hubTone, run in node at one moment with the
    English catalog, returning the line and the dot drawn."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to run the page's script")
    constants = "\n".join(
        f"const {name} = " + PAGE_JS.split(f"const {name} = ")[1].split(";\n")[0] + ";"
        for name in (
            "CONNECTION_STATES",
            "WAIT_REASONS",
            "PERSON_REASONS",
            "THROUGH_WAYS",
        )
    )
    script = "\n".join(
        [
            "const CATALOG = " + json.dumps(EN_WORDS) + ";",
            "function fill(template, params)"
            + function_body("function fill(template, params)")
            + "\n}",
            "const t = (key, params) => fill(CATALOG[key] || key, params);",
            "const wordError = (e) => t('code.' + e.code, e.params);",
            f"Date.now = () => {now} * 1000;",
            constants,
            "function secondsLeft(hub)"
            + function_body("function secondsLeft(hub)")
            + "\n}",
            "function hubWord(hub)" + function_body("function hubWord(hub)") + "\n}",
            "function waitWord(hub)" + function_body("function waitWord(hub)") + "\n}",
            "function hubTone(hub)" + function_body("function hubTone(hub)") + "\n}",
            "const hub = " + json.dumps(hub) + ";",
            "console.log(JSON.stringify({line: hubWord(hub), tone: hubTone(hub)}));",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "reason, next_round_at, line, tone",
    [
        ("hub_silent", 1005.0, "The hub did not answer · retrying in 5 s", "wait"),
        (
            "hub_off_overlay",
            1004.2,
            "The hub is not on the virtual network · retrying in 5 s",
            "wait",
        ),
        ("no_network", None, "No network", "wait"),
        ("untrusted", 1060.0, "Hub key mismatch · retrying in 60 s", "bad"),
        (
            "admission_paused",
            1042.0,
            "The hub pauses new devices · retrying in 42 s",
            "wait",
        ),
        ("unknown_device", None, "The hub does not know this device", "bad"),
        ("too_old", None, "Version too old", "bad"),
    ],
)
def test_a_waiting_hub_says_its_reason_and_counts_down(
    reason, next_round_at, line, tone
):
    hub = {
        "connection": "waiting",
        "wait_reason": reason,
        "next_round_at": next_round_at,
        "jobs": {},
    }

    assert run_state_line(hub, 1000.0) == {"line": line, "tone": tone}


def test_a_countdown_at_0_reads_connecting_with_a_pulsing_dot():
    hub = {
        "connection": "waiting",
        "wait_reason": "hub_silent",
        "next_round_at": 1005.0,
        "jobs": {},
    }

    assert run_state_line(hub, 1004.5)["line"].endswith("retrying in 1 s")
    assert run_state_line(hub, 1005.0) == {"line": "Connecting…", "tone": "pulse"}


def test_a_refused_join_says_the_codes_wording():
    hub = {
        "connection": "waiting",
        "wait_reason": "join_refused",
        "wait_code": {"code": "ticket_spent", "params": {}},
        "next_round_at": None,
        "jobs": {},
    }

    assert run_state_line(hub, 1000.0) == {
        "line": "Join refused · " + EN_WORDS["code.ticket_spent"],
        "tone": "bad",
    }


@pytest.mark.parametrize(
    "connection, line, tone",
    [
        ("connecting", "Connecting…", "pulse"),
        ("replaced", "Replaced by another client · Reconnect", "wait"),
        ("disabled", "Disabled by the hub", "wait"),
        ("connected", "Connected · LAN", "ok"),
    ],
)
def test_the_other_state_lines(connection, line, tone):
    hub = {"connection": connection, "reached_through": "lan", "jobs": {}}

    assert run_state_line(hub, 1000.0) == {"line": line, "tone": tone}


def test_a_hub_never_reached_waits_with_a_grey_dot():
    hub = {
        "connection": "waiting",
        "wait_reason": "hub_silent",
        "next_round_at": 1005.0,
        "is_pending": True,
        "jobs": {},
    }

    assert run_state_line(hub, 1000.0) == {
        "line": "The hub did not answer · retrying in 5 s",
        "tone": "off",
    }
    hub["wait_reason"] = "join_refused"
    hub["next_round_at"] = None
    assert run_state_line(hub, 1000.0)["tone"] == "bad"


def test_the_countdown_redraws_the_state_lines_once_a_second_in_place():
    tick = body_of("tickCountdowns")
    assert "document.querySelectorAll('[data-state-line]')" in tick
    assert "line.textContent = hubWord(hub);" in tick
    assert "dot.className = dotClass(hubTone(hub));" in tick
    schedule = body_of("scheduleCountdowns")
    assert "if (!(lastState.hubs || []).some(isCountingDown)) return;" in schedule
    assert "countdownTimer = setTimeout(tickCountdowns, 1000);" in schedule
    assert "scheduleCountdowns();\n}" in body_of("draw")
    assert "api(" not in tick and "send(" not in tick
    assert "if (parts.stateKey) row.dataset.stateLine = parts.stateKey;" in (
        body_of("rowElement")
    )
    assert "stateKey: hubKey(hub)," in body_of("hubRow")


def test_a_hub_that_publishes_no_network_draws_no_network_line():
    row = run_hub_row(
        dict(HUB_ROW, overlay={"networks": [], "state": "off", "error": None})
    )

    assert (row["extras"], row["reason"], row["actions"]) == ([], "", ["leave"])


@pytest.mark.parametrize(
    "changes, tags, word",
    [
        ({"rtt_ms": 12}, ["connected", "ui.state.rtt"], ""),
        ({"rtt_ms": None}, ["connected"], ""),
        ({"connection": "connecting", "rtt_ms": 12}, None, "connected"),
        ({"jobs": {"is_refreshing": True}, "rtt_ms": 12}, None, "connected"),
    ],
)
def test_only_a_connected_hub_row_carries_its_tags(changes, tags, word):
    row = run_hub_row(dict(HUB_ROW, overlay={"networks": []}, **changes))

    assert (row["tags"], row["word"]) == (tags, word)


def test_a_hub_that_publishes_a_network_draws_its_line_and_button():
    row = run_hub_row(
        dict(HUB_ROW, overlay={"networks": [{"provider": "netbird"}], "state": "off"})
    )

    assert row["extras"] == ["network line"]
    assert row["actions"] == ["network button", "leave"]


def test_a_disabled_hub_with_no_network_still_says_it_is_switched_off():
    row = run_hub_row(dict(HUB_ROW, connection="disabled", overlay={"networks": []}))

    assert row["reason"] == "ui.reason.disabled"
    assert row["actions"] == ["leave"]


def run_hubs_page(hubs: list) -> list:
    """The page's own drawHubs, hubRow, overlayButton and overlayReason, run
    in node with the English catalog, returning each row's network button
    and reason."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to run the page's script")
    script = "\n".join(
        [
            "const CATALOG = " + json.dumps(EN_WORDS) + ";",
            "function fill(template, params)"
            + function_body("function fill(template, params)")
            + "\n}",
            "const t = (key, params) => fill(CATALOG[key] || key, params);",
            "const hasWord = (key) => CATALOG[key] !== undefined;",
            "const DETAIL_CODES = [];",
            "const OVERLAY_TITLES = {};",
            "function wordCode(code, params)"
            + function_body("function wordCode(code, params)")
            + "\n}",
            "const element = () => ({children: [], disabled: false,",
            "  appendChild(child) { this.children.push(child); }});",
            "const document = {createElement: element,",
            "  createTextNode: (text) => text};",
            "const send = () => {};",
            "const spinner = () => 'spin';",
            "const noticeLine = () => null;",
            "const joinRow = () => null;",
            "const noteLine = (text) => text;",
            "const reasonLine = (text) => text;",
            "const errorLine = (text) => text;",
            "const wordError = (error) => error.code;",
            "const overlayLine = () => 'network line';",
            "const overlayStage = () => '';",
            "const overlayPicker = () => null;",
            "const panelButton = () => ({name: 'panel'});",
            "const leaveButton = () => ({name: 'leave'});",
            "const isLeaveOnly = () => false;",
            "const hubKey = (hub) => hub.hub_id;",
            "const hubTone = () => 'ok';",
            "const hubName = (hub) => hub.hub_name;",
            "const hubWord = () => 'connected';",
            "const hubTags = () => null;",
            "const rowElement = (options) => options;",
            "function drawHubs(state)"
            + function_body("function drawHubs(state)")
            + "\n}",
            "function hubRow(hub, isOtherNetworkInUse)"
            + function_body("function hubRow(hub, isOtherNetworkInUse)")
            + "\n}",
            "function isNetworkInUse(hub)"
            + function_body("function isNetworkInUse(hub)")
            + "\n}",
            "function overlayButton(hub, isOtherNetworkInUse)"
            + function_body("function overlayButton(hub, isOtherNetworkInUse)")
            + "\n}",
            "function overlayReason(hub, isOtherNetworkInUse)"
            + function_body("function overlayReason(hub, isOtherNetworkInUse)")
            + "\n}",
            "const card = drawHubs({hubs: " + json.dumps(hubs) + "});",
            "console.log(JSON.stringify(card.children.filter((row) => row)",
            "  .map((row) => ({button: row.actions[0].textContent,",
            "    is_disabled: row.actions[0].disabled, reason: row.reason}))));",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def network_hub(hub_id: str, state: str, job: str = "") -> dict:
    """A connected hub row that publishes one EasyTier network."""
    return dict(
        HUB_ROW,
        hub_id=hub_id,
        jobs={"overlay_job": job} if job else {},
        overlay={
            "network": "easytier",
            "networks": [{"provider": "easytier", "network": hub_id + "-net"}],
            "state": state,
            "error": None,
        },
    )


@pytest.mark.parametrize("state, job", [("on", ""), ("off", "connecting")])
def test_connect_on_another_hub_is_disabled_while_one_network_is_not_off(state, job):
    rows = run_hubs_page([network_hub("h1", state, job), network_hub("h2", "off")])

    assert rows[0]["is_disabled"] is False
    assert rows[1] == {
        "button": "Connect",
        "is_disabled": True,
        "reason": EN_WORDS["code.overlay_other_network"].replace("{network}", "h2-net"),
    }


def test_connect_is_enabled_on_every_hub_while_every_network_is_off():
    rows = run_hubs_page([network_hub("h1", "off"), network_hub("h2", "off")])

    assert [(row["is_disabled"], row["reason"]) for row in rows] == [
        (False, ""),
        (False, ""),
    ]


def test_the_join_button_shows_joining_and_a_refusal_under_the_input():
    row = body_of("joinRow")
    assert "jobButton(t('ui.join'), isJoining ? 'joining' : '')" in row
    assert "joinError = reply && reply.error ? reply.error : null;" in row
    assert "error: joinError ? wordCode(joinError.code, joinError.params) : ''," in row


def test_a_notice_stands_above_the_hubs_with_a_close_button():
    hubs = body_of("drawHubs")
    assert (
        "for (const notice of state.notices || []) card.appendChild(noticeLine(notice));"
        in hubs
    )
    line = body_of("noticeLine")
    assert "errorLine(wordCode(notice.code, notice.params))" in line
    assert "close.title = t('ui.notice_close');" in line
    assert "close.onclick = () => send('/api/notice/close', { id: notice.id });" in line


def test_the_network_line_reads_on_or_off_and_a_connect_is_its_job():
    line = body_of("overlayLine")
    assert "jobs.overlay_job === 'connecting' ? t('ui.job.connecting')" in line
    assert "t('ui.overlay.' + state, { address: overlay.address || '' })" in line
    stage = body_of("overlayStage")
    assert "if (overlay.stage !== 'login') return '';" in stage
    assert "t('ui.reason.console_waiting')" in stage
    assert "if (jobs.overlay_job === 'connecting') {" in body_of("overlayButton")
    for gone in ("stage_clock", "stage_since", "ui.stage.hub", "ui.overlay.connecting"):
        assert gone not in PAGE_JS
    for language in CLIENT_LANGUAGES:
        assert "ui.stage.hub" not in CATALOGS[language]
        assert "ui.overlay.connecting" not in CATALOGS[language]


def test_every_entry_is_one_row_with_its_provider_line():
    row = body_of("entryRow")
    assert "provider: providerLine(hub, entry)," in row
    for build in ("drawAiEntry", "drawFileEntry", "drawDesktopEntry"):
        assert "entryRow(hub, entry," in body_of(build)


def test_the_hub_row_says_the_way_in_and_offers_the_panel():
    word = body_of("hubWord")
    assert "t('ui.state.connected_through'," in word
    assert "{ way: t('ui.through.' + hub.reached_through) }" in word
    # Every way the hub names has its word; a way the list lacks reads as
    # the plain connected word.
    assert (
        "const THROUGH_WAYS = ["
        "'lan', 'netbird', 'easytier', 'ssh_relay', 'direct', 'sakurafrp', 'openfrp'];"
        in PAGE_JS
    )
    assert (
        "if (connection === 'connected' && "
        "THROUGH_WAYS.indexOf(hub.reached_through) >= 0) {" in word
    )
    assert "  return t('ui.state.' + connection);\n}" in word
    row = body_of("hubRow")
    assert "if (hub.is_panel_allowed) actions.push(panelButton(hub));" in row
    assert row.index("actions.push(network);") < row.index("panelButton(hub)")
    assert row.index("panelButton(hub)") < row.index("actions.push(leaveButton(hub));")
    panel = body_of("panelButton")
    assert "jobs.is_opening_panel ? 'opening' : ''" in panel
    assert "send('/api/panel/open', { hub_id: hubKey(hub) })" in panel
    assert "hub.connection !== 'connected'" in panel
    for way, english, chinese in (
        ("lan", "LAN", "局域网"),
        ("netbird", "NetBird", "NetBird"),
        ("easytier", "EasyTier", "EasyTier"),
        ("ssh_relay", "SSH relay", "SSH 中继"),
        ("direct", "Direct", "直连"),
        ("sakurafrp", "SakuraFrp", "SakuraFrp"),
        ("openfrp", "OpenFrp", "OpenFrp"),
    ):
        assert EN_WORDS["ui.through." + way] == english
        assert CATALOGS["zh-CN"]["ui.through." + way] == chinese
    assert "ui.through.relay" not in EN_WORDS
    assert EN_WORDS["ui.state.connected_through"] == "Connected · {way}"
    assert EN_WORDS["ui.hub_panel"] == "Panel"
    assert CATALOGS["zh-CN"]["ui.hub_panel"] == "面板"


def test_the_ai_row_shows_its_forward_and_that_the_tools_need_the_client():
    ai = body_of("drawAiEntry")
    assert "(payload.endpoint || '') + forwardedTo(entry)" in ai
    assert "const extras = [noteLine(t('ui.ai_needs_client'))];" in ai
    assert EN_WORDS["ui.ai_needs_client"] == (
        "The tools reach the gateway only while this client runs."
    )


def test_after_a_refused_login_save_mounts_at_once():
    files = body_of("drawFileEntry")
    assert "const onSave = isLoginRefused(entry, record) && !entry.job" in files
    assert "? () => sendFileLogin(entry, record, staged) : null;" in files
    form = body_of("drawFileForm")
    assert "if (onSave && isMountFormFilled(staged, entry)) { onSave(); return; }" in (
        form
    )
    refused = body_of("isLoginRefused")
    assert "!!entry.is_declared && !!record" in refused
    login = body_of("sendFileLogin")
    assert "username: staged.username, password: staged.password," in login


def test_only_a_false_health_is_unhealthy_on_every_page():
    """Empty health, a record no probe has reached, keeps every action
    enabled and carries no health word."""
    assert "return entry.is_healthy === false;" in body_of("isUnhealthy")
    assert PAGE_JS.count("is_healthy") == 1
    assert "return isUnhealthy(entry) ? 'wait' : 'ok';" in body_of("entryTone")
    assert "if (isUnhealthy(entry)) return t('ui.unhealthy');" in body_of("entryWord")


def test_empty_health_leaves_connect_enabled_when_the_page_runs_it():
    """The page's own functions, run: Connect on a port entry with empty
    health is enabled and its dot is green; only false disables it."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to run the page's script")
    script = "\n".join(
        [
            "function isUnhealthy(entry)"
            + function_body("function isUnhealthy(entry)")
            + "\n}",
            "function isRefreshing(hub)"
            + function_body("function isRefreshing(hub)")
            + "\n}",
            "function entryWork(hub, entry)"
            + function_body("function entryWork(hub, entry)")
            + "\n}",
            "function isEntryFree(hub, entry)"
            + function_body("function isEntryFree(hub, entry)")
            + "\n}",
            "function entryTone(hub, entry)"
            + function_body("function entryTone(hub, entry)")
            + "\n}",
            "const hub = {connection: 'connected', jobs: {}};",
            "const out = [true, false, null, undefined].map((health) => {",
            "  const entry = {is_healthy: health, job: ''};",
            "  const isConnectDisabled = !isEntryFree(hub, entry)",
            "    || (isUnhealthy(entry) && true);",
            "  return [isConnectDisabled, entryTone(hub, entry)];",
            "});",
            "console.log(JSON.stringify(out));",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=30
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        [False, "ok"],
        [True, "wait"],
        [False, "ok"],
        [False, "ok"],
    ]


def test_the_ai_row_names_its_forward_after_the_gateway():
    assert "return (entry.payload || {}).protocol === 'udp' ? '/udp' : '';" in (
        body_of("protocolSuffix")
    )
    assert (
        "t('ui.forwarding_to', { port: entry.forward }) + protocolSuffix(entry)"
        in body_of("forwardedTo")
    )


def test_the_ai_switch_and_configure_wait_for_any_switch_running():
    ai = body_of("drawAiEntry")
    assert "&& !isAiSwitching(state);" in ai
    assert "t('ui.job.switching')" in ai


def test_a_machines_share_mounts_at_the_first_press_and_a_declared_one_waits():
    button = body_of("mountButton")
    assert (
        "button.disabled = !isFree || isUnhealthy(entry) || !!entry.is_declared;"
        in (button)
    )
    assert "{ action: 'mount', hub_id: entry.hub_id, id: entry.id, path: '' }" in button
    assert "!isMountFormFilled(staged, entry)" in button
    assert "!isMountFormFilled(staged, entry)" in body_of("drawFileEntry")
    assert "return !entry.is_declared || !!staged.username;" in body_of(
        "isMountFormFilled"
    )
    reason = body_of("mountReason")
    assert "(entry.is_declared ? t('ui.reason.mount_user') : '')" in reason
    assert EN_WORDS["ui.reason.mount_user"] == "Enter a user name in Configure first."
    for gone in (
        "asksMountPlace",
        "mountDefaultPath",
        "MOUNT_FORM_REASONS",
        "'volume'",
    ):
        assert gone not in PAGE_JS, gone
    for gone in (
        "ui.reason.mount_form",
        "ui.reason.mount_form_drive",
        "ui.reason.mount_form_volume",
        "ui.mount_volume_caption",
    ):
        assert gone not in EN_WORDS, gone


def test_the_form_holds_the_place_and_a_declared_shares_login():
    form = body_of("drawFileForm")
    assert form.index("if (entry.is_declared) {") < form.index("['username',")
    assert "form.appendChild(driveLetterLine(staged, state, entry));" in form
    assert "form.appendChild(mountPathLine(staged, changed));" in form
    assert "line.appendChild(userList(input, users, 'users_' + key));" in form
    users = body_of("userList")
    assert "document.createElement('datalist')" in users
    assert "option.value = user;" in users
    opened = body_of("openFileForm")
    assert (
        "path: record && record.path ? record.path : (entry.mount_default || ''),"
        in (opened)
    )
    drive = body_of("driveLetterLine")
    assert (
        "staged.path = staged.path || entry.mount_default || (letters[0] || '');"
        in (drive)
    )
    assert "t('ui.mount_drive_caption')" in drive


def test_a_mounted_share_on_a_mac_names_the_server_the_finder_lists_it_under():
    files = body_of("drawFileEntry")
    assert "if (isMac() && each.is_attached && each.path) {" in files
    assert (
        "noteLine(t('ui.mount_finder', { server: each.server || LOOPBACK_SERVER }))"
        in files
    )
    assert EN_WORDS["ui.mount_finder"] == "In the Finder it is under {server}."


def test_an_unmounting_record_is_its_job_on_the_button_and_the_line():
    button = body_of("mountButton")
    assert "if (record && record.state === 'unmounting') {" in button
    assert "return jobButton('', 'unmounting', 'danger');" in button
    assert "isUnmounting ? t('ui.job.unmounting')" in body_of("drawMountRecord")


def test_a_desktop_connects_once_while_no_viewer_runs():
    desktop = body_of("drawDesktopEntry")
    assert "|| isOpen;" in desktop
    assert "jobButton(t('ui.rdp_connect'), entry.job)" in desktop


def test_a_mac_desktop_carries_a_standing_hint_under_the_provider_line():
    """No Mac reports whether RustDesk was granted its permissions, so the
    hint stands on every Mac entry, healthy or not."""
    desktop = body_of("drawDesktopEntry")
    assert "payload.platform_os === 'darwin'" in desktop
    assert "noteLine(t('ui.rdp_mac_hint'))" in desktop
    assert "[connect], reason, extras)" in desktop


# --- the terminals ---


def test_the_listed_sessions_become_tabs_and_a_gone_one_ends():
    merge = body_of("mergeSessions")
    assert "if (tab.isListed && !isListedNow" in merge
    assert "endTab(tab, t('ui.terminal_ended'));" in merge
    assert "const tab = newTab(row.hub_id, machine, row.session_id);" in merge
    assert "tab.state = 'idle';" in merge
    assert "activeShell = shellTabs[0].key;" in merge


def test_the_active_listed_tab_attaches_when_the_page_opens():
    assert "if (active && active.state === 'idle') {" in body_of("drawTerminals")
    assert "if (tab.state === 'idle') attachShell(tab);" in body_of("selectTab")


def test_a_dropped_channel_keeps_the_tab_and_its_session():
    piece = body_of("takeShellPiece")
    assert "if (end.code === 'hub_unreachable' && tab.session_id) {" in piece
    assert "loseShell(tab, wordCode(end.code, end.params));" in piece
    lose = body_of("loseShell")
    assert "tab.state = 'idle';" in lose
    assert "tab.isDropped = true;" in lose
    assert "tab.droppedAt = stateSerial;" in lose
    assert "session_id" not in lose
    start = body_of("startShell")
    assert "if (reply && reply.code === 'hub_unreachable' && tab.session_id) {" in start


def test_a_dropped_tab_attaches_again_by_session_id_when_its_hub_lists_it():
    merge = body_of("mergeSessions")
    dropped = merge[merge.index("if (tab.isDropped) {") :]
    dropped = dropped[: dropped.index("      continue;\n    }")]
    assert "if (stateSerial <= tab.droppedAt) continue;" in dropped
    assert dropped.index("isListedNow") < dropped.index("reattachShell(tab);")
    assert "endTab(tab, t('ui.terminal_ended'));" in dropped
    assert "if (state !== lastState) stateSerial += 1;" in body_of("draw")
    reattach = body_of("reattachShell")
    assert "tab.term.reset();" in reattach
    assert "attachShell(tab)" in reattach


def test_a_dropped_tab_never_attaches_while_its_hub_is_away():
    assert "if (tab.state !== 'idle' || tab.isDropped) return;" in body_of(
        "attachShell"
    )
    assert "if (tab.isDropped) return 'wait';" in body_of("shellTone")
    assert ": tab.isDropped ? tab.note" in body_of("statusLine")


def test_a_session_the_machine_no_longer_keeps_reads_ended():
    piece = body_of("takeShellPiece")
    gone = piece[piece.index("if (end.code === 'session_unknown') {") :]
    assert gone.index("endTab(tab, t('ui.terminal_ended'));") < gone.index("return;")


def test_the_active_tab_is_marked_with_the_accent_on_the_elevated_surface():
    assert "tab.key === activeShell ? 'term_tab on' : 'term_tab'" in body_of(
        "shellTabButton"
    )
    rule = PAGE_CSS[PAGE_CSS.index(".term_tab.on {") :]
    rule = rule[: rule.index("}")]
    assert "border-color: var(--color-accent);" in rule
    assert "background: var(--color-elevated);" in rule
    plain = PAGE_CSS[PAGE_CSS.index(".term_tab {") :]
    assert "border: 1px solid var(--color-border);" in plain[: plain.index("}")]
    assert PAGE_CSS.count("--color-elevated: #") == 2


def test_a_tab_shows_its_badges():
    tab = body_of("shellTabButton")
    assert (
        "if (flags.is_persistent) label.appendChild(badge(t('ui.badge.kept')));" in tab
    )
    assert "if (flags.is_shared) label.appendChild(badge(t('ui.badge.shared')));" in tab
    assert "if ((flags.attached_count || 0) > 1)" in tab


def test_the_two_switches_act_only_for_the_owner_of_an_open_tab():
    status = body_of("statusLine")
    assert "const isEnabled = isOpen && flags.is_owned;" in status
    assert "t('ui.reason.not_owned', { owner: flags.owner_name || flags.owner })" in (
        status
    )
    assert (
        "t('ui.terminal_persistent')" in status and "t('ui.terminal_shared')" in status
    )
    persist = body_of("askPersist")
    assert (
        "terminal_id: tab.terminal_id, is_persistent: isPersistent, is_shared: isShared,"
        in (persist)
    )


def test_a_switch_that_cannot_act_draws_no_accent():
    assert "button.switch:disabled { opacity: 1; color: var(--color-text-muted); }" in (
        PAGE_CSS
    )
    disabled_track = PAGE_CSS.split("button.switch:disabled .switch_track {")[1]
    assert disabled_track.split("}")[0].count("var(--color-text-faint)") == 1
    disabled_thumb = PAGE_CSS.split("button.switch:disabled .switch_thumb {")[1]
    assert "var(--color-text-faint)" in disabled_thumb.split("}")[0]
    assert PAGE_CSS.index("button.switch:disabled .switch_thumb") > PAGE_CSS.index(
        "button.switch.on .switch_thumb"
    )
    assert "button.switch:disabled .switch_thumb { background" in PAGE_CSS
    assert "transform" not in disabled_thumb.split("}")[0]


def test_a_plain_session_closes_and_a_kept_or_shared_one_arms():
    guarded = body_of("isGuarded")
    assert "(flags.is_persistent || flags.is_shared)" in guarded
    close = body_of("pressClose")
    assert "if (!isGuarded(tab)) { closeShell(tab); return; }" in close
    assert (
        "api('/api/terminal/stop', { hub_id: tab.hub_id, session_id: tab.session_id })"
        in (close)
    )


def test_a_middle_click_closes_a_tab_and_a_double_click_opens_one():
    assert "if (event.button !== 1) return;" in body_of("shellTabButton")
    assert "head.ondblclick = (event) => {" in body_of("shellPanel")


def test_the_right_click_opens_the_menu_at_the_pointer():
    assert "openTerminalMenu(tab, event.clientX, event.clientY);" in body_of(
        "wireShell"
    )
    menu = body_of("openTerminalMenu")
    for key in ("ui.menu.copy", "ui.menu.paste", "ui.menu.select_all", "ui.menu.clear"):
        assert f"t('{key}')" in menu
    assert "!tab.term.hasSelection()" in menu
    assert "if (event.key === 'Escape') closeTerminalMenu();" in PAGE_JS


def test_the_copy_and_paste_chords_follow_each_system():
    chord = body_of("terminalChord")
    assert (
        "(event.ctrlKey && event.shiftKey && key === 'c') || (isCommand && key === 'c')"
        in (chord)
    )
    assert (
        "(event.ctrlKey && event.shiftKey && key === 'v') || (isCommand && key === 'v')"
        in (chord)
    )
    assert "const isCommand = isMac() && event.metaKey && !event.ctrlKey;" in chord
    assert "api('/api/clipboard', { text: text })" in body_of("copySelection")
    assert "api('/api/clipboard').then(" in body_of("pasteClipboard")
    assert "if (event.button !== 1 || !isLinux()) return;" in body_of("wireShell")


def test_shift_page_keys_page_and_ctrl_plus_minus_keep_the_font_size():
    chord = body_of("terminalChord")
    assert "key === 'pageup') return 'page_up';" in chord
    assert "key === 'pagedown') return 'page_down';" in chord
    run = body_of("runTerminalChord")
    assert "tab.term.scrollPages(-1)" in run
    assert "send('/api/terminal/font', { size: terminalFontSize() + 1 })" in run


def test_the_terminal_draws_in_meslolgs_nf_loaded_through_the_resident():
    assert "const TERMINAL_FONT_FAMILY = 'MesloLGS NF';" in PAGE_JS
    assert "const TERMINAL_FONT = '\"' + TERMINAL_FONT_FAMILY + '\", ui-monospace" in (
        PAGE_JS
    )
    assert "loadTerminalFont();" in body_of("newTab")
    assert "api('/api/font?name=' + name + '&offset=' + offset)" in body_of("fontBytes")


def test_no_session_taken_handling_is_left():
    assert "session_taken" not in PAGE_JS
    assert "code.session_taken" not in EN_WORDS
    assert EN_WORDS["code.session_not_owned"]


# --- the settings page ---


def test_the_settings_card_carries_the_language_the_theme_and_the_ssh_switch():
    settings = body_of("drawSettings")
    assert settings.index("t('ui.language')") < settings.index("t('ui.theme')")
    assert settings.index("t('ui.theme')") < settings.index(
        "t('ui.settings.ssh_include')"
    )
    assert "send('/api/settings/set', {" in settings
    assert "is_ssh_include_enabled: draft.is_ssh_include_enabled," in settings
    assert "is_ssh_include_enabled: !!state.is_ssh_include_enabled," in settings
    assert "t('ui.settings.ssh_include_hint')" in settings
    assert "save.disabled = !isDirty;" in settings
    assert "/api/language" not in PAGE_JS and "/api/theme'" not in PAGE_JS
    assert settings.index("page.appendChild(aboutSection(state));") < settings.index(
        "page.appendChild(card);"
    )


def test_about_is_the_panels_card_of_two_groups_with_no_page_of_its_own():
    about = body_of("aboutSection")
    assert "header.className = 'card_header';" in about
    assert "document.createElement('h2')" in about
    groups = [
        about.index(f"t('{key}')")
        for key in ("ui.about_this_machine", "ui.about_carried")
    ]
    assert groups == sorted(groups)
    assert "ui.about_sources" not in about
    for key in ("ui.about", "ui.about_machine", "ui.about_platform"):
        assert f"t('{key}')" in about
    assert "state.hostname" in about
    assert "platform.os + '/' + platform.arch" in about
    assert "state.carried_versions" in about
    group = body_of("aboutGroup")
    assert "heading.className = 'section_label';" in group
    assert "about_key" in group and "about_value" in group
    assert "api('/api/open_link', { url: url });" in body_of("aboutLink")


def test_about_carries_the_client_and_each_core_as_credits_rows_with_a_source_word():
    about = body_of("aboutSection")
    assert "['Neutrino client ' + state.version, CLIENT_LICENCE," in about
    assert "[[source, CLIENT_SOURCES[state.edition] || CLIENT_SOURCES.intl]]]" in about
    assert "version ? core.name + ' ' + version : core.name" in about
    assert "const source = t('ui.about_source_link');" in about
    assert "text.textContent = (value || '') + (links.length ? ' — ' : '');" in (
        body_of("aboutGroup")
    )
    assert "link.textContent = word;" in body_of("aboutLink")
    for language in CLIENT_LANGUAGES:
        assert CATALOGS[language]["ui.about_source_link"]
        assert CATALOGS[language]["ui.about_patch_link"]
    assert EN_WORDS["ui.about_source_link"] == "Source"
    assert EN_WORDS["ui.about_patch_link"] == "Patch"
    value_rule = PAGE_CSS[PAGE_CSS.index(".about_value {") :]
    assert "monospace" in value_rule[: value_rule.index("}")]
    row_rule = PAGE_CSS[PAGE_CSS.index(".about_row {") :]
    assert "var(--color-border) 60%" in row_rule[: row_rule.index("}")]
    label_rule = PAGE_CSS[PAGE_CSS.index(".section_label {") :]
    assert "text-transform: uppercase" in label_rule[: label_rule.index("}")]
    assert "const CLIENT_LICENCE = 'MIT';" in PAGE_JS
    assert "intl: 'https://github.com/iffiX/neutrino'," in PAGE_JS
    assert "cn: 'https://cnb.cool/iffi-X/neutrino'," in PAGE_JS
    assert "const CARRIED = [" in PAGE_JS
    for name, licence in (
        ("NetBird", "BSD-3-Clause"),
        ("EasyTier", "LGPL-3.0"),
        ("RustDesk", "AGPL-3.0"),
        ("cc-switch", "MIT"),
    ):
        assert f"name: '{name}'" in PAGE_JS and f"licence: '{licence}'" in PAGE_JS
    assert "{ name: 'tun2socks', key: 'tun2socks', licence: 'MIT'," in PAGE_JS
    assert "os: 'windows' }" in PAGE_JS
    assert "CARRIED.filter((core) => !core.os || core.os === platform.os)" in (
        body_of("aboutSection")
    )
    carried = body_of("carriedSource")
    assert "(edition === 'cn' && core.mainland) || core.repository" in carried
    assert "repository + '/tree/' + fill(core.tag, { version: version })" in carried
    assert "carriedSource(core, version, state.edition)" in body_of("aboutSection")
    assert "mainland: 'https://gitee.com/easytier/EasyTier', tag: 'v{version}' }" in (
        PAGE_JS
    )
    assert "mainland: 'https://gitee.com/mirrors/rustdesk', tag: '{version}' }" in (
        PAGE_JS
    )


def test_the_sidebar_carries_only_the_pages_and_no_foot():
    assert 'id="ident"' not in PAGE_HTML
    assert ".ident" not in PAGE_CSS
    assert "getElementById('ident')" not in PAGE_JS


def run_ai_row(*, is_managed: bool) -> dict:
    """The page's own drawAiEntry, run in node on a healthy entry of the exit
    hub with the chip on, returning the row it draws."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to run the page's script")
    signature = "function drawAiEntry(card, state, hub, entry)"
    script = "\n".join(
        [
            "const document = {createElement: () => ({appendChild: () => {}}),",
            "  createTextNode: () => ({})};",
            "const t = (key) => key;",
            "const ensureAiStaged = () => ({});",
            "const isAiSwitching = () => false;",
            "const isEntryFree = () => true;",
            "const isUnhealthy = () => false;",
            "const entryWork = () => '';",
            "const entryReason = () => 'other';",
            "const marker = () => '';",
            "const noteLine = (text) => text;",
            "const errorLine = (text) => text;",
            "const wordCode = (code) => code;",
            "const forwardedTo = () => ' -> 21001';",
            "let row = null;",
            "function entryRow(hub, entry, address, word, actions, reason, extras) {",
            "  row = {address, disabled: actions.map((a) => a.disabled), reason};",
            "  return row;",
            "}",
            signature + function_body(signature) + "\n}",
            "const state = {ai: {is_enabled: false, is_active: false,",
            "  is_managed: " + json.dumps(is_managed) + "}};",
            "drawAiEntry({appendChild: () => {}}, state, {is_exit: true},",
            "  {payload: {endpoint: 'http://hub:8080'}, job: ''});",
            "console.log(JSON.stringify(row));",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_with_the_agent_installed_the_ai_row_shows_but_holds_still():
    row = run_ai_row(is_managed=True)

    assert row == {
        "address": "http://hub:8080 -> 21001",
        "disabled": [True, True],
        "reason": "ui.reason.ai_managed",
    }


def test_without_the_agent_the_ai_row_is_usable_again():
    row = run_ai_row(is_managed=False)

    assert row["disabled"] == [False, False]
    assert row["reason"] == ""


def test_the_managed_reason_is_one_text_with_its_code_in_both_languages():
    for words in CATALOGS.values():
        assert words["ui.reason.ai_managed"] == words["code.ai_tools_managed"]
    assert EN_WORDS["ui.reason.ai_managed"] == (
        "This is a managed device: set its AI tools on the hub's panel, "
        "under Modules, Global configuration."
    )
    assert CATALOGS["zh-CN"]["ui.reason.ai_managed"] == (
        "这是已管理的设备，请到中枢面板的“模块”页，在“全局配置”里设置它的 AI 工具。"
    )


def page_constant(name: str) -> str:
    """One top-level constant of the page's script, as written there."""
    body = PAGE_JS.split(f"const {name} = {{")[1].split("\n};")[0]
    return f"const {name} = {{{body}\n}};"


def provider_lines(entries: list, language: str = "en") -> list:
    """The page's own providerLine, run in node for each entry of hub nmxhub."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to run the page's script")
    words = {
        key: CATALOGS[language][key]
        for key in (
            "ui.provided_by",
            "ui.module_ai_gateway",
            "ui.module_title.samba",
            "ui.module_title.remote_desktop",
        )
    }
    script = "\n".join(
        [
            "const WORDS = " + json.dumps(words) + ";",
            "const t = (key, values) => WORDS[key].replace(/\\{(\\w+)\\}/g,",
            "  (_m, name) => String((values || {})[name]));",
            "function hubName(hub)" + function_body("function hubName(hub)") + "\n}",
            "function entryHost(entry) { return (entry.payload || {}).host || ''; }",
            page_constant("ENTRY_MODULES"),
            page_constant("ENTRY_MODULE_KEYS"),
            "function entryModule(entry)"
            + function_body("function entryModule(entry)")
            + "\n}",
            "function providerLine(hub, entry)"
            + function_body("function providerLine(hub, entry)")
            + "\n}",
            "const hub = {hub_name: 'nmxhub'};",
            "console.log(JSON.stringify(" + json.dumps(entries) + ".map(",
            "  (entry) => providerLine(hub, entry))));",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_every_entry_names_its_hub_its_machine_and_its_modules_title():
    lines = provider_lines(
        [
            {"device_name": "nmxhub", "description_code": "ai_gateway"},
            {"device_name": "nmxhub", "description_code": "samba_module"},
            {"device_name": "nmxdev", "description_code": "samba_module"},
            {"device_name": "studio", "description_code": "device_share"},
            {
                "device_name": "nmxdev",
                "description_code": "vscode_module",
                "title": "VS Code (alice)",
            },
            {"device_name": "", "payload": {"host": "10.0.0.5"}, "title": "dns"},
            {
                "device_name": "nmxhub",
                "description_code": "container",
                "description_params": {"image": "docker.io/traefik/whoami:latest"},
            },
        ]
    )

    assert lines == [
        "from nmxhub:nmxhub:AI gateway",
        "from nmxhub:nmxhub:File share",
        "from nmxhub:nmxdev:File share",
        "from nmxhub:studio:Remote desktop",
        "from nmxhub:nmxdev:VS Code",
        "from nmxhub:10.0.0.5:dns",
        "from nmxhub:nmxhub:whoami:latest",
    ]


def test_the_modules_title_is_worded_in_the_pages_language():
    lines = provider_lines(
        [{"device_name": "nas", "description_code": "samba_module"}], "zh-CN"
    )

    assert lines == ["由 nmxhub:nas:文件共享 提供"]


def test_every_forms_button_row_is_one_row_at_the_bottom_right():
    """N54: Save and Cancel, Choose this folder: one style on every page."""
    actions = PAGE_CSS.split(".form_actions {")[1].split("}")[0]
    assert "justify-content: flex-end" in actions
    assert PAGE_JS.count("actions.className = 'form_actions';") == 5
    assert "actions.className = 'row';" not in PAGE_JS
    assert "actions.style.marginTop" not in PAGE_JS


def test_every_form_field_spans_its_row():
    """N54: no select or input is held narrower than its row."""
    settings_picker = PAGE_CSS.split(".settings .picker {")[1].split("}")[0]
    assert "max-width" not in settings_picker
    assert ".modal select { width: 100%; }" in PAGE_CSS
    assert ".form .row input { flex: 1; }" in PAGE_CSS


# --- the Apps page ---


def run_app_row(app: dict, entries: list, os_name: str = "linux", hub=None) -> dict:
    """The page's own appRow and what it draws with, run in node with the
    English catalog, returning the row's words, lines and controls."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to run the page's script")
    functions = "\n".join(
        body_of(name)
        for name in (
            "fill",
            "isUnhealthy",
            "isRefreshing",
            "hubName",
            "entryHost",
            "protocolSuffix",
            "appWork",
            "isAppUnhealthy",
            "appTone",
            "appProviderLine",
            "localHost",
            "localAddress",
            "entryLine",
            "appRow",
            "stopButton",
            "isPageEntry",
            "appReason",
            "isMac",
        )
    )
    constants = "\n".join(
        f"const {name} = " + PAGE_JS.split(f"const {name} = ")[1].split(";\n")[0] + ";"
        for name in ("APP_SOURCES", "LOOPBACK_SERVER")
    )
    script = "\n".join(
        [
            "const CATALOG = " + json.dumps(EN_WORDS) + ";",
            "const t = (key, params) => fill(CATALOG[key] || key, params);",
            "const wordError = (e) => e ? t('code.' + e.code, e.params) : '';",
            "const lastState = {platform: {os: " + json.dumps(os_name) + "}};",
            "const element = () => ({children: [], disabled: false, textContent: '',",
            "  className: '', appendChild(child) { this.children.push(child); }});",
            "const document = {createElement: element,",
            "  createTextNode: (text) => text};",
            "const send = () => {};",
            "const openAppPortDialog = () => {};",
            "function jobButton(label, job, className) {",
            "  const button = element();",
            "  button.textContent = job ? t('ui.job.' + job) : label;",
            "  button.disabled = !!job;",
            "  button.className = className || '';",
            "  return button;",
            "}",
            "const rowElement = (options) => options;",
            "function appEntries(state, app) { return state.services; }",
            constants,
            functions,
            "const state = {services: " + json.dumps(entries) + "};",
            "const row = appRow(state, "
            + json.dumps(hub or HUB_ROW)
            + ", "
            + json.dumps(app)
            + ");",
            "console.log(JSON.stringify({word: row.word, tone: row.tone,",
            "  provider: row.provider, error: row.error, reason: row.reason,",
            "  lines: row.extras.map((line) => line.textContent),",
            "  actions: row.actions.map((action) => [action.textContent,",
            "    action.disabled, action.className])}));",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


GITEA = {
    "hub_id": "h1",
    "id": "gitea_d1",
    "title": "Gitea",
    "source": "module",
    "device_id": "d1",
    "device_name": "lab-gpu",
    "local_name": "gitea.lab-gpu.localhost",
    "job": "",
    "last_error": None,
    "is_in_use": False,
}
GITEA_WEB = {
    "hub_id": "h1",
    "id": "gitea_d1_web",
    "app_id": "gitea_d1",
    "name": "web",
    "type": "web",
    "payload": {
        "url": "http://10.0.0.5:3000/explore?tab=repos",
        "is_token_required": False,
    },
    "is_healthy": True,
    "local_port": 24123,
    "forward": None,
}
GITEA_SSH = {
    "hub_id": "h1",
    "id": "gitea_d1_ssh",
    "app_id": "gitea_d1",
    "name": "ssh",
    "type": "port",
    "payload": {"host": "10.0.0.5", "port": 2222, "protocol": "tcp"},
    "is_healthy": True,
    "local_port": 27001,
    "forward": None,
}


def test_an_app_row_names_its_machine_its_source_and_every_local_address():
    dns = dict(
        GITEA_SSH,
        name="53_udp",
        type="port",
        payload={"host": "10.0.0.5", "port": 53, "protocol": "udp"},
        local_port=25053,
    )
    shell = dict(
        GITEA_SSH,
        name="lab",
        type="ssh",
        payload={"host": "10.0.0.5", "port": 22001, "account": "lab"},
        local_port=26001,
    )

    row = run_app_row(GITEA, [GITEA_WEB, GITEA_SSH, dns, shell])

    assert row["provider"] == "from home:lab-gpu · module"
    assert row["lines"] == [
        "http://gitea.lab-gpu.localhost:24123/explore?tab=repos",
        "gitea.lab-gpu.localhost:27001",
        "gitea.lab-gpu.localhost:25053/udp",
        "ssh gitea.lab-gpu.localhost:26001",
    ]
    assert row["actions"] == [["Use", False, ""], ["Configure", False, "ghost"]]
    assert (row["tone"], row["word"], row["reason"]) == ("ok", "", "")


def test_an_app_in_use_with_no_page_has_no_open():
    row = run_app_row(dict(GITEA, is_in_use=True), [GITEA_SSH])

    assert row["actions"] == [["Stop", False, "danger"], ["Configure", True, "ghost"]]


def test_an_entry_with_no_number_shows_its_kind_and_no_port():
    row = run_app_row(GITEA, [GITEA_WEB, dict(GITEA_SSH, local_port=None)])

    assert row["lines"] == [
        "http://gitea.lab-gpu.localhost:24123/explore?tab=repos",
        "Port",
    ]


def test_on_a_mac_every_local_address_is_the_loopback():
    row = run_app_row(GITEA, [GITEA_WEB], os_name="darwin")

    assert row["lines"] == ["http://127.0.0.1:24123/explore?tab=repos"]


def test_an_app_in_use_offers_stop_in_uses_place_open_and_holds_its_ports():
    row = run_app_row(dict(GITEA, is_in_use=True), [GITEA_WEB, GITEA_SSH])

    assert row["actions"] == [
        ["Stop", False, "danger"],
        ["Configure", True, "ghost"],
        ["Open", False, "ghost"],
    ]
    assert row["reason"] == EN_WORDS["ui.reason.disconnect_first"]


def test_an_app_job_is_its_buttons_indicator():
    row = run_app_row(dict(GITEA, job="opening"), [GITEA_WEB])

    assert row["word"] == "Opening…"
    assert row["tone"] == "pulse"
    assert row["actions"][0] == ["Opening…", True, ""]
    assert row["actions"][1][1] is True
    assert len(row["actions"]) == 2

    opening = run_app_row(dict(GITEA, job="opening", is_in_use=True), [GITEA_WEB])
    assert opening["actions"][0] == ["Stop", False, "danger"]
    assert opening["actions"][2] == ["Opening…", True, "ghost"]

    stopping = run_app_row(
        dict(GITEA, job="disconnecting", is_in_use=True), [GITEA_WEB]
    )
    assert stopping["actions"][0] == ["Disconnecting…", True, "danger"]


def test_an_unhealthy_entry_says_so_on_its_line_and_use_waits_for_one_healthy():
    sick = dict(GITEA_SSH, is_healthy=False)

    row = run_app_row(GITEA, [GITEA_WEB, sick])
    assert row["lines"][1] == "gitea.lab-gpu.localhost:27001 · Not reachable now"
    assert row["actions"][0][1] is False

    row = run_app_row(GITEA, [dict(GITEA_WEB, is_healthy=False), sick])
    assert row["actions"][0][1] is True
    assert row["reason"] == EN_WORDS["ui.reason.unhealthy"]
    assert row["tone"] == "wait"


def test_empty_health_leaves_use_enabled():
    row = run_app_row(GITEA, [dict(GITEA_WEB, is_healthy=None)])

    assert row["actions"][0][1] is False
    assert row["tone"] == "ok"


def test_a_failed_use_is_worded_on_the_apps_error_line():
    failed = dict(GITEA, last_error={"code": "port_taken", "params": {"port": 24123}})

    row = run_app_row(failed, [GITEA_WEB])

    assert row["error"] == (
        "Local port 24123 is in use; give this entry another in Configure."
    )


def test_a_disabled_hub_holds_every_app_still():
    row = run_app_row(GITEA, [GITEA_WEB], hub=dict(HUB_ROW, connection="disabled"))

    assert [action[1] for action in row["actions"]] == [True, True]
    assert row["reason"] == EN_WORDS["ui.reason.disabled"]


def test_the_apps_page_lists_every_hubs_apps_and_their_entries_but_shares():
    page_body = body_of("drawApps")
    assert "if (hubs.length === 0) return waitCard();" in page_body
    assert "card.appendChild(downRow(hub));" in page_body
    assert "if (count === 0) card.appendChild(emptyRow(t('ui.empty_apps')));" in (
        page_body
    )
    entries = body_of("appEntries")
    assert "entry.app_id === app.id && entry.type !== 'file'" in entries
    assert "} else if (openTab === 'apps') {" in body_of("draw")
    assert "if (tab === 'apps') return t('ui.panel_apps');" in body_of("tabTitle")


def test_the_port_dialog_sends_the_changed_fields_and_says_a_taken_port():
    dialog = body_of("openAppPortDialog")
    assert "t('ui.app.port_dialog_title', { app: app.title })" in dialog
    assert "ports[field.name] = value === '' ? null : Number(value);" in dialog
    assert "api('/api/app/set'," in dialog
    assert "t('ui.reason.port_taken', { port: (reply.params || {}).port })" in dialog
    assert "t('ui.reason.port_range')" in dialog
    assert "modal.classList.toggle('dirty', isDirty);" in dialog
    assert dialog.index("save.textContent = t('ui.save');") < dialog.index(
        "cancel.textContent = t('ui.cancel');"
    )
    field = body_of("isPortField")
    assert "number >= PORT_FIRST && number <= PORT_LAST" in field
    assert "const PORT_FIRST = 1024;" in PAGE_JS
    assert "const PORT_LAST = 65535;" in PAGE_JS


# --- the terminals' account picker ---


def test_the_account_picker_follows_the_chips_with_two_accounts_or_more():
    strip = body_of("machineStrip")
    assert strip.index("line.appendChild(chips);") < strip.index(
        "accountPicker(picked)"
    )
    assert strip.index("accountPicker(picked)") < strip.index("newShellButton(picked)")
    chooser = body_of("accountPicker")
    assert "if (accounts.length < 2) return null;" in chooser
    assert "wrap.title = t('ui.terminal.account');" in chooser
    account = body_of("pickedAccount")
    assert "return accounts.indexOf(chosen) >= 0 ? chosen : (accounts[0] || '');" in (
        account
    )
    assert "&& machineAccounts(picked.machine).length > 0;" in body_of("canOpenShell")
    assert "return t('ui.reason.terminal_no_account');" in body_of("newShellReason")
    assert "openShell(picked.hub, picked.machine, pickedAccount(picked))" in body_of(
        "newShellButton"
    )
    assert "account: tab.account," in body_of("startShell")
    assert "tab.account = account || '';" in body_of("openShell")


# --- no word from outside is read as markup ---


def test_no_word_from_outside_is_ever_read_as_markup():
    """Names, titles, hosts, paths and codes reach the page from the hub and
    its machines; one compromised machine must not run script in the window.
    No assignment of markup may build on anything but a constant literal."""
    for sink in ("outerHTML", "insertAdjacentHTML", "document.write", "DOMParser"):
        assert sink not in PAGE_JS, sink
    for match in re.finditer(r"\.innerHTML\s*\+?=\s*([^;]*);", PAGE_JS):
        assert re.fullmatch(r"'[^'+]*'", match.group(1).strip()), match.group(0)
    assert "innerHTML" not in PAGE_JS


# --- the words of ui_text.md's 0.6.0 table ---

# Key, English, Chinese, as ui_text.md writes them for the clients.
UI_TEXT_060 = (
    (
        "code.control_unavailable",
        "The hub is busy and did not answer; try again.",
        "中枢正忙，没有应答，稍后再试。",
    ),
    (
        "code.terminal_account_missing",
        "No account is enabled for this machine's terminal; enable one on its "
        "machine page.",
        "这台机器的终端没有启用的账户，到它的机器页上启用一个。",
    ),
    (
        "code.account_not_enabled",
        "{account} is not enabled for this machine's terminal.",
        "这台机器的终端没有启用 {account}。",
    ),
    (
        "code.key_missing",
        "The SSH server of {account} has no key from the hub; apply the module again.",
        "{account} 的 SSH 服务器没有中枢发的钥匙，重新应用这个模块。",
    ),
    (
        "code.op_unknown",
        "This agent cannot do {op} on files.",
        "这个被控端不能对文件做 {op}。",
    ),
    (
        "code.hub_untrusted",
        "The hub's key does not match; if it was reset, join it again.",
        "中枢的密钥对不上；中枢重置过的话就重新加入。",
    ),
    ("ui.state.untrusted", "Hub key mismatch", "中枢密钥不符"),
    (
        "code.hub_key_missing",
        "This binding is from 0.5 and the hub no longer moves it; join the hub "
        "again with a new link.",
        "这份绑定来自 0.5，中枢已不再迁移；用新链接重新加入中枢。",
    ),
    (
        "code.port_taken",
        "Local port {port} is in use; give this entry another in Configure.",
        "本机端口 {port} 已被占用，在“配置”里给这个入口换一个。",
    ),
    (
        "code.client_not_running",
        "The client is not running; start it with nclient gui.",
        "客户端没有运行，先 nclient gui。",
    ),
    ("ui.panel_apps", "Apps", "应用"),
    ("ui.app_source.module", "module", "模块"),
    ("ui.app_source.declared", "declared", "声明"),
    ("ui.app_source.manual", "manual", "手动"),
    ("ui.app.use", "Use", "使用"),
    ("ui.app.configure", "Configure", "配置"),
    ("ui.app.stop", "Stop", "停止"),
    ("ui.app.port_dialog_title", "Local ports of {app}", "{app} 的本机端口"),
    (
        "ui.reason.terminal_no_account",
        "No account is enabled for this machine's terminal.",
        "这台机器的终端没有启用的账户。",
    ),
    ("ui.terminal.account", "Account", "账户"),
    (
        "ui.settings.ssh_include",
        "SSH programs reach the machines",
        "让 SSH 程序直接连被控端",
    ),
    (
        "ui.settings.ssh_include_hint",
        "Whether ssh, scp, git and VS Code reach each machine as <machine>.nt.",
        "是否让 ssh、scp、git 和 VS Code 用 <机器>.nt 直接连到每台机器。",
    ),
)


@pytest.mark.parametrize("key, english, chinese", UI_TEXT_060)
def test_the_words_of_ui_text_are_in_both_catalogs_as_written(key, english, chinese):
    assert EN_WORDS[key] == english
    assert CATALOGS["zh-CN"][key] == chinese


def test_a_chinese_invalid_code_opens_with_its_noun():
    for key, wording in CATALOGS["zh-CN"].items():
        if key.startswith("code.") and key.endswith("_invalid"):
            assert wording.startswith("非法"), key
