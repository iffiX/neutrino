"""The dashboard, held against ui_behavior.md's "The dashboard".

What these pin: each active exit reads its node's name from the frame's
probes and falls back to its tag.
"""

from pathlib import Path

FRONTEND_SRC_DIR = Path(__file__).resolve().parents[2] / "frontend/src"


def flat(name: str) -> str:
    """One frontend file with its whitespace folded to single spaces."""
    return " ".join((FRONTEND_SRC_DIR / name).read_text(encoding="utf-8").split())


def test_a_node_s_probe_carries_its_name_on_the_frame():
    types = flat("api_types.ts")
    probe = types.split("export interface NodeProbe {", 1)[1].split("}", 1)[0]

    assert "name: string;" in probe


def test_an_active_exit_reads_its_node_s_name_and_else_its_tag():
    exits = flat("active_exits.ts")
    page = flat("pages/dashboard_page.tsx")

    assert "name: probe?.name || outbound.tag," in exits
    assert '<div className="dashboard_exit_tag">{exit.name}</div>' in page
