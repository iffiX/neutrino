"""A machine's default account in the panel, held against the standard.

What these pin: the setup page's account screen after the proxy screen and
before Ready, starting at the context's ``default_account``, its password on
Windows, its Next testing the account before the next screen and keeping a
refusal's words under the fields, left out with no account, and the review's
Default account row; the Default chip and no Remove on the default's row of
Available accounts, and the Save of the first account on a machine with no
default asking first; the default's row first in Enabled accounts, checked
and locked with the chip, and always in the list the apply writes; a machine
with no default greying every tab's buttons, every apply bar and + Add
module, each bar showing ``ui.modules.default_needed``; an online machine
with no default reading incomplete in amber in the sidebar, the Agents table
and the machine page's header, offline winning; the API types mirroring the
hub's ``default_account`` fields; and every word in both languages as
ui_text.md writes it, the deleted ones gone.
"""

import json
import re
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
COMPONENTS_DIR = FRONTEND_SRC_DIR / "components"
PAGES_DIR = FRONTEND_SRC_DIR / "pages"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
UI_TEXT = HUB_DIR.parent / "skills/core-code-author/design/ui_text.md"
LANGUAGES = ("en", "zh-CN")
ROW_PATTERN = re.compile(
    r"^\| `((?:ui|code|state)\.[a-z0-9_.]+)`[^|]* \| (.+?) \| (.+?) \|$"
)
# The new and the changed words, by the catalog file that holds them.
WORDED_KEYS = {
    "setup.json": (
        "ui.setup.screen_account",
        "ui.setup.account_lead",
        "ui.setup.account",
        "ui.setup.account_password",
        "ui.setup.review_account",
    ),
    "devices.json": ("state.incomplete",),
    "modules.json": (
        "ui.accounts.default",
        "ui.accounts.make_default",
        "ui.accounts.default_title",
        "ui.accounts.default_body",
        "ui.modules.default_needed",
        "ui.containers.run_apply_hint",
    ),
    "codes.json": (
        "code.account_no_login",
        "code.account_is_default",
        "code.default_account_missing",
        "code.machine_account_missing",
    ),
}
# The words ui_text.md deletes with the default account.
GONE_KEYS = (
    "ui.modules.no_accounts",
    "ui.containers.run_account",
    "ui.containers.run_account_hint",
    "ui.containers.run_account_warning",
    "ui.containers.run_needed",
    "ui.containers.account_title",
    "ui.containers.account_empty",
)
# Every apply bar the machine page reaches, by the file that draws it.
MODULE_BAR_FILES = (
    "instances_panel.tsx",
    "gitea_panels.tsx",
    "remote_desktop_panels.tsx",
    "ollama_settings.tsx",
    "ayakaleaf_panels.tsx",
    "containers_panels.tsx",
    "containers_run_settings.tsx",
)


def flat(text: str) -> str:
    return " ".join(text.split())


def source(path: Path) -> str:
    return flat(path.read_text(encoding="utf-8"))


def standard_rows() -> dict:
    """Every key row of ui_text.md, as {key: (English, Chinese)}."""
    rows = {}
    for line in UI_TEXT.read_text(encoding="utf-8").splitlines():
        match = ROW_PATTERN.match(line)
        if match is not None:
            rows.setdefault(match.group(1), (match.group(2), match.group(3)))
    return rows


def catalog(language: str, name: str) -> dict:
    return json.loads((LOCALES_DIR / language / name).read_text(encoding="utf-8"))


def every_word(language: str) -> dict:
    found: dict = {}
    for path in sorted((LOCALES_DIR / language).glob("*.json")):
        found.update(json.loads(path.read_text(encoding="utf-8")))
    return found


def function_body(text: str, name: str) -> str:
    """One function of a flattened source, up to the next doc comment."""
    start = text.index(f"function {name}(")
    end = text.find("/** ", start)
    return text[start:] if end == -1 else text[start:end]


@pytest.mark.parametrize(
    "name,key", [(name, key) for name, keys in WORDED_KEYS.items() for key in keys]
)
def test_each_word_says_what_ui_text_writes_in_both_languages(name, key):
    english, chinese = standard_rows()[key]

    assert catalog("en", name)[key] == english
    assert catalog("zh-CN", name)[key] == chinese


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_deleted_words_are_gone(language):
    held = every_word(language)

    for key in GONE_KEYS:
        assert key not in held


def test_the_api_types_mirror_the_hub_s_default_account():
    types = source(FRONTEND_SRC_DIR / "api_types.ts")
    setup = source(FRONTEND_SRC_DIR / "setup_api.ts")

    for view in ("DeviceView", "AccountListView", "EnabledAccountsView"):
        body = types[types.index(f"export interface {view} ") :]
        body = body[: body.index("}")]
        assert "default_account: string;" in body
    assert "AccountPasswordTest" not in types
    context = setup[setup.index("export interface SetupContext {") :]
    context = context[: context.index("}")]
    assert "accounts: string[];" in context
    assert "default_account: string;" in context
    assert "default_account?: SetupAccountAnswer;" in setup


def test_the_account_screen_comes_after_the_proxy_screen_and_before_ready():
    page = source(PAGES_DIR / "setup_page.tsx")

    assert (
        '"ui.setup.screen_proxy", "ui.setup.screen_account", '
        '"ui.setup.screen_ready", ] as const;'
    ) in page
    assert "const SCREEN_ACCOUNT = 5;" in page
    assert "...(hasAccounts ? [] : [SCREEN_ACCOUNT])," in function_body(
        page, "hiddenScreens"
    )
    assert "const hasAccounts = context.accounts.length > 0;" in page


def test_the_account_screen_starts_at_the_context_s_default_account():
    page = source(PAGES_DIR / "setup_page.tsx")
    screen = page[page.index("{index === SCREEN_ACCOUNT && (") :]
    screen = screen[: screen.index("{index === SCREEN_REVIEW && (")]

    assert (
        'useState( context.default_account || (context.accounts[0] ?? ""), );'
    ) in page
    assert '<p className="setup_lead">{t("ui.setup.account_lead")}</p>' in screen
    assert "options={context.accounts.map((offered) => ({" in screen
    assert 'label={t("ui.setup.account")}' in screen
    assert '{isWindows && ( <label className="field">' in screen
    assert 't("ui.setup.account_password")' in screen
    assert (
        '{accountError !== null && ( <span className="field_error">{accountError}</span> )}'
    ) in screen


def test_next_tests_the_account_and_a_refusal_keeps_the_screen():
    page = source(PAGES_DIR / "setup_page.tsx")
    setup = source(FRONTEND_SRC_DIR / "setup_api.ts")
    test = page[page.index("const testAccount = async () => {") :]
    test = test[: test.index("};")]

    assert (
        "onClick={index === SCREEN_ACCOUNT ? () => void testAccount() : next}" in page
    )
    assert (
        "(index === SCREEN_ACCOUNT && (isAccountTesting || (isWindows && "
        'accountPassword === "")))'
    ) in page
    assert "await testSetupAccount(token, accountAnswer()); next();" in test
    assert "setAccountError(describeError(cause));" in page
    assert 'await call<unknown>("account/test", token, answer);' in setup
    assert ("isWindows ? { account, password: accountPassword } : { account }") in page


def test_the_answers_and_the_review_name_the_default_account():
    page = source(PAGES_DIR / "setup_page.tsx")

    assert ("if (hasAccounts) { document.default_account = accountAnswer(); }") in page
    assert (
        '<Row name={t("ui.setup.review_account")} value={hasAccounts ? account : NOTHING} />'
    ) in page
    assert 'const NOTHING = "—";' in page


def test_the_default_s_row_has_the_chip_and_no_remove():
    panel = source(COMPONENTS_DIR / "accounts_panel.tsx")

    assert (
        "{account.account === view.default_account && ( "
        '<span className="badge">{t("ui.accounts.default")}</span> )}'
    ) in panel
    remove = panel[: panel.index('{t("ui.accounts.remove")}')]
    remove = remove[remove.rindex("{account.account") :]
    assert remove.startswith("{account.account !== view.default_account && (")
    assert "Make default" not in panel
    assert "make_default" not in panel


def test_the_first_account_s_save_asks_first():
    form = source(COMPONENTS_DIR / "account_form.tsx")
    ask = form[form.index("const askSave = () => {") :]
    ask = ask[: ask.index("}); };")]

    assert 'if (!isNew || view.default_account !== "") { void save(); return; }' in ask
    assert 'title: t("ui.accounts.default_title", { account: name }),' in ask
    assert 'body: t("ui.accounts.default_body", { account: name }),' in ask
    assert 'confirmLabel: t("ui.accounts.make_default"),' in ask
    assert "onConfirm: () => void save()," in ask
    assert "disabled={!isReady} onClick={askSave}" in form
    assert "{confirm.modal}" in form


def test_the_default_s_row_comes_first_checked_and_locked_with_the_chip():
    panel = source(COMPONENTS_DIR / "instances_panel.tsx")
    check = function_body(panel, "AccountCheck")
    first = function_body(panel, "defaultFirst")
    draft = function_body(panel, "draftOf")

    assert "{defaultFirst(saved).map((row) =>" in panel
    assert panel.count("isDefault={row.account === saved.default_account}") == 2
    assert "disabled={isDisabled || isDefault}" in check
    assert (
        '{isDefault && <span className="badge">{t("ui.accounts.default")}</span>}'
    ) in check
    assert first.index("row.account === view.default_account") < first.index(
        "row.account !== view.default_account"
    )
    assert (
        "accounts: isDefaultListed ? [view.default_account, ...enabled] : enabled,"
    ) in draft
    assert "ui.modules.no_accounts" not in panel


def test_a_machine_with_no_default_greys_the_tabs_like_an_offline_one():
    page = source(COMPONENTS_DIR / "machine_modules.tsx")

    assert 'const isDefaultMissing = defaultAccount === "";' in page
    assert "const isLive = isAgentOnline && !isDefaultMissing;" in page
    assert (
        'const blockedHint = !isAgentOnline ? t("ui.modules.agent_offline") '
        ': isDefaultMissing ? t("ui.modules.default_needed") : null;'
    ) in page
    assert (
        "const canAct = activeRow !== undefined && isLive && !isBusy && !isInTransit;"
        in page
    )
    assert "isEnabled={isLive && !isBusy && !isRowCancelling}" in page
    assert "disabled={!isLive || isBusy}" in page
    assert "canPress={isLive && !isInTransit}" in page
    assert '<fieldset className="modules_config" disabled={!isLive}>' in page
    assert "blockedHint, defaultAccount, platformOs," in page
    assert (
        '<button type="button" className="button modules_list_add" '
        "disabled={isDefaultMissing}"
    ) in page


@pytest.mark.parametrize("name", MODULE_BAR_FILES)
def test_every_apply_bar_shows_the_page_s_reason(name):
    panel = source(COMPONENTS_DIR / name)

    assert "blockedHint: string | null;" in panel
    assert "ui.modules.agent_offline" not in panel
    bars = panel.split("<ApplyBar")[1:]
    assert bars
    for bar in bars:
        assert "blockedHint={blockedHint}" in bar[: bar.index("/>")]


def test_the_machine_page_hands_the_default_to_the_tabs():
    page = source(PAGES_DIR / "machine_page.tsx")

    assert "defaultAccount={device.default_account}" in page
    assert (
        "{ type: HUB_EVENT_CONFIG, key: `devices/${deviceId}/accounts.json` },"
    ) in page


def test_incomplete_is_an_online_machine_with_no_default():
    level = source(FRONTEND_SRC_DIR / "device_level.ts")

    assert (
        'return device.is_agent_online && device.default_account === "";'
    ) in function_body(level, "isDeviceIncomplete")


def test_the_sidebar_shows_the_amber_dot_and_incomplete_where_offline_goes():
    nav = source(COMPONENTS_DIR / "sidebar_nav.tsx")
    entry = function_body(nav, "MachineEntry")

    assert "const isIncomplete = isDeviceIncomplete(machine);" in entry
    assert (
        '{isIncomplete ? ( <StatusDot tone="warn" /> ) : ( '
        '<StatusDot tone={isOnline ? "ok" : "idle"} isPulsing={isOnline} /> )}'
    ) in entry
    assert (
        '{!isOnline && ( <span className="sidebar_machine_offline">'
        '{t("state.offline")}</span> )}'
    ) in entry
    assert (
        '{isIncomplete && ( <span className="sidebar_machine_offline">'
        '{t("state.incomplete")}</span> )}'
    ) in entry
    assert "{ type: HUB_EVENT_CONFIG }," in nav


@pytest.mark.parametrize(
    "path,check",
    [
        (PAGES_DIR / "devices_page.tsx", "{isDeviceIncomplete(device) ? ("),
        (PAGES_DIR / "machine_page.tsx", "{isIncomplete ? ("),
    ],
)
def test_the_agents_table_and_the_machine_header_read_incomplete(path, check):
    page = source(path)

    assert (
        f'{check} <StatusDot tone="warn" label={{t("state.incomplete")}} /> ) : ('
        in page
    )
