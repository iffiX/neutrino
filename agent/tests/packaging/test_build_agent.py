"""The Linux packages' container build, with the container stood in for."""

import pytest

import build_agent


def test_the_container_takes_the_go_programs_before_the_package_build():
    script = build_agent.AGENT_CONTAINER_BUILD.format(
        install="true", script="build_deb.py", architecture="amd64"
    )

    copy = "cp -r /src/dist/go /build/dist/"
    assert "mkdir -p" in script and "/build/dist" in script
    assert copy in script
    assert script.index(copy) < script.index("python3 agent/packaging/build_deb.py")


def test_a_missing_go_program_stops_the_build_before_any_container(
    monkeypatch, go_programs
):
    (go_programs / "linux-arm64" / "neutrino_transport").unlink()
    monkeypatch.setattr(
        build_agent.sys,
        "argv",
        ["build_agent.py", "--architecture", "arm64", "--families", "debian"],
    )
    monkeypatch.setattr(
        build_agent.edition_build, "require_edition_tree", lambda edition: None
    )
    monkeypatch.setattr(
        build_agent.container_build, "container_engine", lambda: "podman"
    )
    monkeypatch.setattr(
        build_agent.container_build,
        "build_in_container",
        lambda *args, **kwargs: pytest.fail("a container ran"),
    )

    with pytest.raises(SystemExit, match="linux-arm64/neutrino_transport"):
        build_agent.main()
