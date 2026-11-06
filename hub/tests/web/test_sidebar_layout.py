"""The sidebar's machine list, held against ui_behavior.md's "The Agents page".

What these pin: the machine list scrolls in a box of its own under its
heading, which shrinks to the room the hub group and Sign out leave, and the
box keeps the room an entry's active bar is drawn in.
"""

from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"


def flat(name: str) -> str:
    """One frontend file with its whitespace folded to single spaces."""
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def rule(style: str, selector: str) -> str:
    """The body of one CSS rule."""
    return style.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_the_machines_sit_in_a_box_of_their_own_under_the_heading():
    nav = flat("components/sidebar_nav.tsx")

    assert (
        '<div className="sidebar_group sidebar_group--machines"> '
        '<div className="sidebar_group_label"> {t("ui.shell.group_agent")} </div> '
        '<div className="sidebar_machines"> {machines.map((machine) => ( '
        "<MachineEntry key={machine.id} machine={machine} /> ))} </div> </div>"
    ) in nav


def test_the_hub_group_keeps_its_height_and_the_machine_list_scrolls():
    style = flat("components/sidebar_nav.css")

    assert "flex: none;" in rule(style, ".sidebar_group--hub")
    machines = rule(style, ".sidebar_group--machines")
    assert "flex: 1 1 auto;" in machines
    assert "min-height: 128px;" in machines
    box = rule(style, ".sidebar_machines")
    assert "overflow-y: auto;" in box
    assert "min-height: 0;" in box
    assert "margin: 0 calc(-1 * var(--space-3));" in box
    assert "padding: 0 var(--space-3);" in box
