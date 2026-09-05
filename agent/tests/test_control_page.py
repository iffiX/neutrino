"""The page's contract, checked on the one string it ships.

The page is one HTML file with its behavior inline, so what can be checked
here is the contract's visible surface: the three section titles, the words
table replacing the dead phrasing, and the redraw guards — payload
comparison, the selection, the focused field, the open dialog.
"""

from neutrino_agent.control.page import CONTROL_PAGE_HTML


def test_the_three_sections_are_titled():
    for title in (
        'section_status: "Status"',
        'section_modules: "Modules"',
        'section_services: "Services"',
    ):
        assert title in CONTROL_PAGE_HTML


def test_one_panel_per_service_type():
    for panel in (
        'panel_web: "Web"',
        'panel_ports: "Ports"',
        'panel_ai: "AI"',
        'panel_files: "Files"',
    ):
        assert panel in CONTROL_PAGE_HTML


def test_the_redraw_guards_are_all_present():
    # Redraw only on a changed payload…
    assert "if (serialized === lastSerialized) return;" in CONTROL_PAGE_HTML
    # …never over a selection, a focused field, or an open dialog.
    assert "getSelection" in CONTROL_PAGE_HTML
    assert "activeElement" in CONTROL_PAGE_HTML
    assert "openDialogs > 0" in CONTROL_PAGE_HTML


def test_controls_are_disabled_not_hidden():
    assert "disabled = !isPrivileged" in CONTROL_PAGE_HTML
    assert "privileged_only" in CONTROL_PAGE_HTML


def test_the_dead_wording_is_gone():
    assert "removal did not take" not in CONTROL_PAGE_HTML
    assert "the removal finished, but the software is still there" in (
        CONTROL_PAGE_HTML
    )


def test_the_ai_panel_stages_chips_config_and_apply():
    for marker in (
        "aiStaged",
        "tool_configs",
        "'/api/services/'",
        "CLAUDE_SLOTS",
        "REASONING_EFFORTS",
    ):
        assert marker in CONTROL_PAGE_HTML
