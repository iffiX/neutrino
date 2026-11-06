"""How nhub run starts the proxy core: its start line for the hub's service."""

import io
import sys

from neutrino_hub.modules.xray import run_part
from neutrino_hub.modules.xray.constants import XRAY_UNIT_TEMPLATE
from neutrino_hub.utils.constants import UTILS_DATA_DIR
from tests.modules.xray.test_log_filter import DETOUR, REFUSED, WARNING


def test_the_proxy_core_starts_with_its_rendered_configuration_and_geodata():
    line = run_part.child_start_lines()["xray"]

    assert line.argv == [
        run_part.XRAY_BINARY,
        "run",
        "-config",
        str(run_part.XRAY_CONFIG_PATH),
    ]
    assert line.env == {run_part.XRAY_ASSET_ENV: str(run_part.XRAY_ASSET_DIR)}


def test_only_xray_runs_the_proxy_core_through_its_log_filter():
    assert run_part.RUN_ONLY == {"xray": run_part.run_xray}
    assert run_part.RUN_CHILDREN == {"xray": run_part.XRAY_BINARY}


def test_the_filter_writes_on_warnings_and_one_failed_dial_and_keeps_the_exit_code():
    """The info of every connection stays out of the journal, a failed dial
    goes in once in ten seconds, and a configuration xray rejects still exits
    23 for the unit's RestartPreventExitStatus."""
    script = "; ".join(
        [
            "import sys",
            f"print({DETOUR!r})",
            f"print({WARNING!r})",
            f"print({REFUSED!r})",
            f"print({REFUSED!r})",
            "sys.exit(23)",
        ]
    )
    written = io.StringIO()

    code = run_part.filter_child([sys.executable, "-c", script], {}, written)

    assert code == 23
    assert written.getvalue() == f"{WARNING}\n{REFUSED}\n"


def test_the_unit_keeps_the_proxy_core_s_listeners_off_mptcp():
    """A Go listener opens an MPTCP socket by default, and a 5.15 kernel refuses
    IP_TRANSPARENT on one, so no TCP reaches the TPROXY listener there."""
    unit = (UTILS_DATA_DIR / "services" / XRAY_UNIT_TEMPLATE).read_text(
        encoding="utf-8"
    )

    assert "Environment=GODEBUG=multipathtcp=0\n" in unit
