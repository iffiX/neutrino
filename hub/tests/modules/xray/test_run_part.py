"""How nhub run starts the proxy core: its start line for the hub's service."""

from neutrino_hub.modules.xray import run_part


def test_the_proxy_core_starts_with_its_rendered_configuration_and_geodata():
    line = run_part.child_start_lines()["xray"]

    assert line.argv == [
        run_part.XRAY_BINARY,
        "run",
        "-config",
        str(run_part.XRAY_CONFIG_PATH),
    ]
    assert line.env == {run_part.XRAY_ASSET_ENV: str(run_part.XRAY_ASSET_DIR)}


def test_only_xray_becomes_the_proxy_core():
    assert run_part.RUN_ONLY == {"xray": run_part.exec_xray}
    assert run_part.RUN_CHILDREN == {"xray": run_part.XRAY_BINARY}
