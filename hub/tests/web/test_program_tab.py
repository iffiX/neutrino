"""The tab of a command line program, Codex or Claude Code, held against the standard.

What these pin: the `find` step's words in both languages, the programs'
section of ui_text.md being test_program_wording.py's; each tool a module of
the account layer whose apply bar
shows `ui.program.apply_hint` and waits for the module's state alone; the
owner notice over the state line; no Start and no Stop on a program, whose
state line reads `state.ready` with a dot that does not pulse; Install live on
a program with no want and on a failed one wanting `running`; the version line
only while the module's own copy is on the machine; each enabled account's
row naming its copy by the source chip's words, then its version and its AI
tools state in the words of its row under Available accounts, read with the
account's switch and with no switch of its own, and the copy's path whole on
a line of its own.
"""

import json
import re
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parents[2]
FRONTEND_SRC_DIR = HUB_DIR / "frontend/src"
COMPONENTS_DIR = FRONTEND_SRC_DIR / "components"
LOCALES_DIR = FRONTEND_SRC_DIR / "locales"
DESIGN_DIR = HUB_DIR.parent / "skills/core-code-author/design"
LANGUAGES = ("en", "zh-CN")
PROGRAMS = ("claude_code", "codex")
ROW_PATTERN = re.compile(
    r"^\| `((?:ui|code|state)\.[a-z0-9_.]+)` \| (.+?) \| (.+?) \|$"
)


def flat(text: str) -> str:
    return " ".join(text.split())


def source(path: Path) -> str:
    return flat(path.read_text(encoding="utf-8"))


def page() -> str:
    return source(COMPONENTS_DIR / "machine_modules.tsx")


def panel() -> str:
    return source(COMPONENTS_DIR / "instances_panel.tsx")


def design(name: str) -> str:
    return (DESIGN_DIR / name).read_text(encoding="utf-8")


def words(language: str) -> dict:
    """Every sentence of one language, from all its catalog files."""
    found: dict = {}
    for path in sorted((LOCALES_DIR / language).glob("*.json")):
        found.update(json.loads(path.read_text(encoding="utf-8")))
    return found


def section_rows(heading: str) -> dict:
    """The rows of one ui_text.md section's key table, as {key: (en, zh)}."""
    text = design("ui_text.md")
    body = text[text.index(f"\n## {heading}\n") :]
    body = body[: body.index("\n## ", 1)]
    rows = {}
    for line in body.splitlines():
        match = ROW_PATTERN.match(line)
        if match is not None:
            rows[match.group(1)] = (match.group(2), match.group(3))
    return rows


def descriptors() -> dict:
    """Each descriptor's text in the panel's table, by module name."""
    table = (FRONTEND_SRC_DIR / "module_descriptors.ts").read_text(encoding="utf-8")
    table = table[table.index("MODULE_DESCRIPTORS") :]
    return dict(re.findall(r"^  (\w+): \{\n(.*?)^  \},$", table, re.M | re.S))


def function_body(text: str, name: str) -> str:
    """One function of a flattened source, up to the next doc comment."""
    start = text.index(f"function {name}(")
    end = text.find("/** ", start)
    return text[start:] if end == -1 else text[start:end]


@pytest.mark.parametrize("index,language", list(enumerate(LANGUAGES)))
def test_the_find_step_says_what_ui_text_writes(index, language):
    rows = section_rows("A module task's words")

    assert words(language)["ui.modules.step.find"] == (
        rows["ui.modules.step.find"][index]
    )


def test_each_tool_is_a_program_of_the_account_layer():
    table = descriptors()
    marked = [name for name, text in table.items() if "isProgram" in text]

    assert sorted(marked) == sorted(PROGRAMS)
    for name in PROGRAMS:
        text = flat(table[name])
        assert f'apply: "ui.{name}.apply",' in text
        assert 'applyHint: "ui.program.apply_hint",' in text
        assert "field: null," in text
        assert "isProgram: true," in text
        assert "isWithoutProgram" not in text
        assert "ownerNotice" not in text


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_program_s_apply_bar_has_its_label(language):
    said = words(language)

    for name in PROGRAMS:
        assert said[f"ui.{name}.apply"].endswith(said[f"ui.module_title.{name}"])


def test_ui_behavior_draws_the_tab_as_these_check():
    text = flat(design("ui_behavior.md"))

    assert (
        "draws the line `ui.codex.owner_notice` or `ui.claude_code.owner_notice` "
        "over its state line, and **Install**, **Uninstall** and **Configure** "
        "alone at the bottom"
    ) in text
    assert (
        "Its state line reads `state.ready` in place of `running`, as Terminal's "
        "rows do, with or without an enabled account"
    ) in text
    assert (
        "A program the machine reports `installed` while the hub holds no "
        "`want` has **Install** live, which writes `running`, and so does a "
        "program that reads `failed` while its `want` is `running`."
    ) in text
    assert (
        "`ui.modules.source_user` for the person's own copy and "
        "`ui.modules.source_upstream` for the module's; its version; the "
        "account's AI tools state in the words of its row under **Available "
        "accounts**, shown and never set here; then the copy's path whole, in "
        "mono, on a line of its own; an account's code shows its words under "
        "the row in the error colour"
    ) in text
    assert (
        "`state.ai_tools_switched_back` for an account the machine has not " "reported"
    ) in text
    assert "read with the account's switch, `is_ai_tools_enabled`" in text
    assert (
        "| The version line | shown while the module's own copy is on the machine;"
    ) in text
    assert (
        "with its apply bar, `ui.codex.apply` or `ui.claude_code.apply` its "
        "button and `ui.program.apply_hint` its hint; the apply waits for the "
        "module's state alone"
    ) in text


def test_the_owner_notice_is_drawn_over_the_state_line():
    body = page()
    start = body.index("const PROGRAM_NOTICES: Record<string, string> = {")
    table = body[start : body.index("};", start)]
    notice = (
        '{programNotice !== undefined && ( <p className="field_hint">'
        "{t(programNotice)}</p> )}"
    )

    assert dict(re.findall(r'(\w+): "(ui\.\w+\.owner_notice)"', table)) == {
        name: f"ui.{name}.owner_notice" for name in PROGRAMS
    }
    assert (
        "const programNotice = activeRow === undefined "
        "? undefined : PROGRAM_NOTICES[activeRow.name];"
    ) in body
    assert notice in body
    assert body.index(notice) < body.index('<div className="modules_detail_head">')


def test_a_program_is_read_from_the_row_s_kind():
    body = page()

    assert 'const KIND_PROGRAM = "program";' in body
    assert "const isProgram = activeRow?.kind === KIND_PROGRAM;" in body


def test_a_program_has_no_start_and_no_stop():
    body = page()
    actions = body[body.index('<div className="modules_actions">') :]
    actions = actions[: actions.index("{actionError !== null")]
    held = actions[actions.index("{!isProgram && ( <>") :]
    held = held[: held.index("</> )}")]

    assert actions.count('<ActionButton action="start"') == 1
    assert actions.count('<ActionButton action="stop"') == 1
    assert '<ActionButton action="start"' in held
    assert '<ActionButton action="stop"' in held
    assert '<ActionButton action="install"' not in held
    assert '<ActionButton action="uninstall"' not in held
    assert "configure()" not in held


def test_a_running_program_reads_ready_with_a_dot_that_does_not_pulse():
    word = function_body(page(), "stateWord")
    head = page()[page().index('<div className="modules_detail_head">') :]
    head = head[: head.index("</div>")]

    assert word.index(
        'if (row.state === "running" && row.kind === KIND_PROGRAM) '
        '{ return t("state.ready"); }'
    ) < word.index("state.running_no_accounts")
    assert "isPulsing={isProgram ? false : undefined}" in head


def test_install_is_live_on_a_program_with_no_want_or_a_failed_one():
    body = page()
    install = body[body.index('<ActionButton action="install"') :]
    install = install[: install.index("/>")]

    assert (
        '(activeRow.state === "absent" || activeRow.state === "install_failed" '
        '|| isRetried(activeRow, "installed") || (isProgram && '
        "(isUnclaimed(activeRow) || isRetried(activeRow, WANT_RUNNING))))"
    ) in install


def test_the_version_line_shows_while_the_module_s_copy_is_on_the_machine():
    body = page()
    block = body[: body.index("<ModuleVersionBlock")]
    block = block[block.rindex("{(isPresent") :]

    assert "!isCarriedRow && (!isProgram || hasModuleCopy(activeRow)) && (" in block
    assert (
        "function hasModuleCopy(row: DeviceModuleView): boolean { "
        "return row.details.has_module_copy === true; }"
    ) in body


def test_a_program_s_bar_shows_its_own_hint_and_waits_for_the_want_it_has():
    body = page()
    instances = panel()

    assert (
        "isWaitingForStart={ !target.isCarried && !target.isProgram && "
        "target.want !== WANT_RUNNING }"
    ) in body
    assert "isProgram: isProgram," in body
    assert (
        "useSettledApply( reportOf(saved, descriptor), "
        "isWaitingForStart || descriptor.isProgram === true ? want : WANT_RUNNING, )"
    ) in instances


def test_a_program_s_apply_waits_for_its_state_alone():
    report = function_body(panel(), "reportOf")

    assert "instances: descriptor.isProgram === true ? [] : view.accounts" in report


def test_a_program_s_rows_are_its_own():
    instances = panel()

    assert (
        "descriptor.isProgram === true ? ( <ProgramAccountRow key={row.account} "
        "row={row}"
    ) in instances


def test_an_enabled_account_s_row_names_its_copy_by_the_source_chip_s_words():
    instances = panel()
    start = instances.index("const COPY_KEYS: Record<string, string> = {")
    table = instances[start : instances.index("};", start)]
    row = function_body(instances, "ProgramAccountRow")

    assert dict(re.findall(r'(\w+): "(ui\.modules\.source_\w+)"', table)) == {
        "user": "ui.modules.source_user",
        "module": "ui.modules.source_upstream",
    }
    assert (
        "{row.is_enabled && copyKey !== undefined && ( <> "
        '<span className="badge">{t(copyKey)}</span> '
        '<span className="instances_row_version mono">{row.version}</span> </> )}'
    ) in row
    assert (
        "{row.is_enabled && copyKey !== undefined && ( "
        '<span className="instances_row_path mono">{row.path}</span> )}'
    ) in row
    assert row.index("{t(copyKey)}") < row.index("aiToolsWords(")
    assert row.index("aiToolsWords(") < row.index("{row.path}")
    assert (
        '{row.code !== "" && ( <span className="field_error instances_row_error"> '
        "{describeCode(row)} </span> )}"
    ) in row
    assert "state.running" not in row
    assert "is_running" not in row


def test_the_ai_tools_state_reads_as_its_row_under_available_accounts():
    instances = panel()
    accounts = source(COMPONENTS_DIR / "accounts_panel.tsx")
    row = function_body(instances, "ProgramAccountRow")

    assert 'from "../ai_tools_words"' in instances
    assert 'from "../ai_tools_words"' in accounts
    assert (
        "label={aiToolsWords( account.account, account.ai_tools, "
        "account.is_ai_tools_enabled, )}"
    ) in accounts
    assert (
        '<span className="instances_row_tools"> '
        '<StatusDot tone={AI_TOOLS_TONES[tools.state] ?? "idle"} '
        "label={aiToolsWords( row.account, tools, "
        "row.is_ai_tools_enabled === true, )} /> </span>"
    ) in row
    assert (
        "const AI_TOOLS_UNREPORTED: AccountAiToolsView = { "
        'state: "switched_back", code: "", params: {}, };'
    ) in instances
    assert "<input" not in row


@pytest.mark.parametrize("module", PROGRAMS)
def test_each_program_has_a_line_glyph_of_its_own(module):
    """module_template.md, "Icons": a 24 by 24 line drawing in currentColor,
    read by the panel by module name, in place of the generic glyph."""
    glyphs = HUB_DIR.parent / "images/icons/modules"
    glyph = (glyphs / f"{module}.svg").read_text(encoding="utf-8")

    assert 'viewBox="0 0 24 24"' in glyph
    assert 'fill="none"' in glyph and 'stroke="currentColor"' in glyph
    assert glyph != (glyphs / "generic.svg").read_text(encoding="utf-8")
