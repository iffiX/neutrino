"""The container declarations and the checks that keep systemd able to run
them, or a flag out of a command line."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.podman.config import PodmanConfig


def config_with(**overrides) -> PodmanConfig:
    data = {"containers": [{"name": "redis", "image": "docker.io/library/redis:7"}]}
    data.update(overrides)
    return PodmanConfig.from_dict(data)


def refused_code(config: PodmanConfig) -> str:
    with pytest.raises(ModuleApplyError) as refused:
        config.validate()
    return refused.value.code


def test_a_sound_configuration_passes():
    config_with().validate()


def test_the_parse_survives_a_round_trip():
    config = config_with()

    assert PodmanConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()
    assert config.declared_names == ["redis"]


@pytest.mark.parametrize("name", ["", "Redis", "a b", "-x", "x\ny", "x" * 65])
def test_a_name_that_is_not_a_unit_name_is_refused(name):
    assert refused_code(config_with(containers=[{"name": name, "image": "img"}])) == (
        "container_name_invalid"
    )


def test_two_containers_cannot_share_a_name():
    config = config_with(
        containers=[{"name": "redis", "image": "a"}, {"name": "redis", "image": "b"}]
    )
    assert refused_code(config) == "container_name_duplicate"


@pytest.mark.parametrize("image", ["", "bad image", "a\nb"])
def test_an_image_with_whitespace_is_refused(image):
    assert refused_code(config_with(containers=[{"name": "x", "image": image}])) == (
        "image_invalid"
    )


@pytest.mark.parametrize("port", ["80", "80:80:80", "eighty:80", "80:80/icmp"])
def test_a_port_that_is_not_a_mapping_is_refused(port):
    config = config_with(containers=[{"name": "x", "image": "img", "ports": [port]}])
    assert refused_code(config) == "port_mapping_invalid"


@pytest.mark.parametrize("port", ["8080:80", "53:53/udp", "443:8443/tcp"])
def test_a_sound_port_mapping_passes(port):
    config_with(containers=[{"name": "x", "image": "img", "ports": [port]}]).validate()


@pytest.mark.parametrize(
    "volume", ["novolume", "relative/path:/data", "/host:relative", "a:b\n:/x"]
)
def test_a_volume_that_is_not_source_destination_is_refused(volume):
    config = config_with(
        containers=[{"name": "x", "image": "img", "volumes": [volume]}]
    )
    assert refused_code(config) == "volume_invalid"


@pytest.mark.parametrize("volume", ["/srv/share:/data", "cache:/var/cache"])
def test_a_sound_volume_passes(volume):
    config_with(
        containers=[{"name": "x", "image": "img", "volumes": [volume]}]
    ).validate()


@pytest.mark.parametrize("entry", ["NOEQUALS", "1BAD=x", "K=v\nInjected=y"])
def test_an_environment_line_that_is_not_key_value_is_refused(entry):
    config = config_with(
        containers=[{"name": "x", "image": "img", "environment": [entry]}]
    )
    assert refused_code(config) == "environment_invalid"


def test_a_command_cannot_span_lines():
    config = config_with(containers=[{"name": "x", "image": "img", "command": "a\nb"}])
    assert refused_code(config) == "command_invalid"


@pytest.mark.parametrize("mirror", ["https://mirror.example.com", "bad mirror", "a\nb"])
def test_a_mirror_that_is_a_url_or_garbled_is_refused(mirror):
    assert refused_code(config_with(mirrors=[mirror])) == "mirror_invalid"


@pytest.mark.parametrize(
    "mirror", ["mirror.ccs.tencentyun.com", "registry.local:5000", "host/path"]
)
def test_a_sound_mirror_passes(mirror):
    config_with(mirrors=[mirror]).validate()


def with_services(ports: list, services: list) -> PodmanConfig:
    return config_with(
        containers=[{"name": "x", "image": "img", "ports": ports, "services": services}]
    )


def test_services_survive_a_round_trip_and_an_absent_list_is_empty():
    config = with_services(
        ["8080:80", "53:53"],
        [
            {"port": 8080, "kind": "web", "scheme": "https"},
            {"port": 53, "kind": "port", "protocols": ["tcp", "udp"]},
        ],
    )

    assert PodmanConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()
    assert config.to_dict()["containers"][0]["services"] == [
        {"port": 8080, "kind": "web", "scheme": "https", "protocols": ["tcp"]},
        {"port": 53, "kind": "port", "scheme": "http", "protocols": ["tcp", "udp"]},
    ]
    assert config_with().containers[0].services == []


@pytest.mark.parametrize(
    "service",
    [
        {"port": 8080, "kind": "auto"},
        {"port": 8080, "kind": "web", "scheme": "http"},
        {"port": 8080, "kind": "port", "protocols": ["udp"]},
    ],
)
def test_a_sound_service_passes(service):
    with_services(["8080:80"], [service]).validate()


def test_a_port_service_with_no_protocol_is_refused_with_its_port():
    config = with_services(["53:53"], [{"port": 53, "kind": "port", "protocols": []}])

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert refused.value.code == "service_protocol_none"
    assert refused.value.params == {"port": 53}


@pytest.mark.parametrize(
    "services",
    [
        [{"port": 9090, "kind": "web"}],
        [{"port": 8080, "kind": "ftp"}],
        [{"port": 8080, "kind": "web", "scheme": "gopher"}],
        [{"port": 8080, "kind": "port", "protocols": ["sctp"]}],
        [{"port": 8080, "kind": "web"}, {"port": 8080, "kind": "port"}],
        [{"port": "eighty", "kind": "web"}],
    ],
)
def test_a_service_off_the_published_ports_or_garbled_is_refused(services):
    assert refused_code(with_services(["8080:80"], services)) == "service_invalid"


@pytest.mark.parametrize(
    ("services", "port"),
    [
        ([{"port": 9090, "kind": "web"}], 9090),
        ([{"port": 8080, "kind": "web", "scheme": "gopher"}], 8080),
        ([{"port": 8080, "kind": "web"}, {"port": 8080, "kind": "port"}], 8080),
    ],
)
def test_a_refused_service_names_its_container_and_port(services, port):
    config = with_services(["8080:80"], services)

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert refused.value.code == "service_invalid"
    assert refused.value.params == {"name": "x", "port": port}


def test_a_garbled_port_mapping_is_refused_before_its_service():
    config = with_services(["8080"], [{"port": 8080, "kind": "web"}])

    assert refused_code(config) == "port_mapping_invalid"


# --- Windows and macOS: the Podman machine ---

MACHINE = {"account": "lab", "cpus": 2, "memory_gib": 4, "disk_gib": 120}


def machine_config(volumes=(), machine=None, containers=None) -> PodmanConfig:
    if containers is None:
        containers = [{"name": "web", "image": "nginx", "volumes": list(volumes)}]
    return PodmanConfig.from_dict(
        {
            "containers": containers,
            "machine": dict(MACHINE) if machine is None else machine,
        }
    )


def refusal_on(config: PodmanConfig, os_name: str, **facts) -> ModuleApplyError:
    with pytest.raises(ModuleApplyError) as refused:
        config.validate(os_name=os_name, **facts)
    return refused.value


def test_the_run_settings_survive_a_round_trip_and_a_linux_state_names_none():
    config = machine_config(machine=dict(MACHINE, password="pw"))

    assert config.machine.account == "lab"
    assert config.machine.password == "pw"
    assert PodmanConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()
    assert config_with().machine is None
    assert "machine" not in config_with().to_dict()


@pytest.mark.parametrize(
    "volume",
    ["C:\\data:/data", "d:\\a b\\c:/srv:ro", "C:/data:/data", "webdata:/data"],
)
def test_windows_takes_a_folder_on_a_drive_or_a_named_volume(volume):
    machine_config([volume]).validate(os_name="windows")


@pytest.mark.parametrize(
    "volume",
    [
        "/Users/me/site:/usr/share/nginx/html",
        "/private/tmp/x:/x",
        "/var/folders/ab/T/x:/x",
        "/Users:/home",
        "webdata:/data",
    ],
)
def test_macos_takes_a_folder_podman_shares_or_a_named_volume(volume):
    machine_config([volume]).validate(os_name="darwin")


@pytest.mark.parametrize(
    "os_name, volume",
    [
        ("windows", "\\\\server\\share:/data"),
        ("windows", "/srv/data:/data"),
        ("darwin", "/opt/data:/data"),
        ("darwin", "/Usersx/me:/data"),
        ("darwin", "relative/dir:/data"),
    ],
)
def test_a_folder_the_machine_cannot_reach_is_not_shared(os_name, volume):
    refusal = refusal_on(machine_config([volume]), os_name)

    assert refusal.code == "volume_not_shared"
    assert refusal.params == {"name": "web", "volume": volume}


@pytest.mark.parametrize("volume", ["C:\\data", "C:\\data:data", "C:\\a\nb:/x"])
def test_a_windows_volume_without_a_destination_is_invalid(volume):
    assert refusal_on(machine_config([volume]), "windows").code == "volume_invalid"


def test_a_drive_letter_means_nothing_on_a_mac():
    config = machine_config(["C:\\data:/data"])

    assert refusal_on(config, "darwin").code == "volume_invalid"


def test_linux_keeps_its_own_volume_rules_and_ignores_the_run_settings():
    config = machine_config(["C:\\data:/data"], machine={"cpus": 999})

    assert refusal_on(config, "linux").code == "volume_invalid"
    machine_config(["/srv:/srv"], machine={"cpus": 999}).validate(
        host_cpus=4, host_memory_gib=8, disk_gib_now=500
    )


@pytest.mark.parametrize("cpus", [-1, 9])
def test_cpus_past_the_computer_are_refused_with_the_maximum(cpus):
    config = machine_config(machine=dict(MACHINE, cpus=cpus))

    refusal = refusal_on(config, "windows", host_cpus=8)

    assert refusal.code == "machine_cpus_invalid"
    assert refusal.params == {"cpus": cpus, "max": 8}


def test_unreadable_cpus_are_refused():
    config = machine_config(machine=dict(MACHINE, cpus="many"))

    assert refusal_on(config, "darwin").code == "machine_cpus_invalid"


@pytest.mark.parametrize("memory_gib", [-2, 17])
def test_memory_past_the_computer_is_refused_with_the_maximum(memory_gib):
    config = machine_config(machine=dict(MACHINE, memory_gib=memory_gib))

    refusal = refusal_on(config, "darwin", host_cpus=8, host_memory_gib=16)

    assert refusal.code == "machine_memory_invalid"
    assert refusal.params == {"memory_gib": memory_gib, "max": 16}


def test_a_disk_smaller_than_the_machines_is_a_shrink():
    config = machine_config(machine=dict(MACHINE, disk_gib=100))

    refusal = refusal_on(config, "windows", disk_gib_now=120)

    assert refusal.code == "machine_disk_shrink"
    assert refusal.params == {"disk_gib": 100, "current_gib": 120}


def test_a_zero_takes_the_default_and_passes_every_size_check():
    config = machine_config(
        machine={"account": "lab", "cpus": 0, "memory_gib": 0, "disk_gib": 0}
    )

    config.validate(os_name="darwin", host_cpus=4, host_memory_gib=8, disk_gib_now=130)
    machine_config(
        machine={"account": "lab", "cpus": 0, "memory_gib": 0, "disk_gib": 130}
    ).validate(os_name="windows", host_cpus=4, host_memory_gib=8, disk_gib_now=130)


@pytest.mark.parametrize("disk_gib", [0, -5])
def test_a_windows_disk_limit_below_1_is_invalid(disk_gib):
    config = machine_config(machine=dict(MACHINE, disk_gib=disk_gib))

    refusal = refusal_on(config, "windows")

    assert refusal.code == "machine_disk_invalid"
    assert refusal.params == {"disk_gib": disk_gib}


def test_a_windows_state_without_run_settings_checks_no_disk():
    PodmanConfig.from_dict({"containers": []}).validate(os_name="windows")


def test_sizes_within_the_computer_pass_and_an_unknown_size_checks_nothing():
    machine_config().validate(
        os_name="windows", host_cpus=2, host_memory_gib=4, disk_gib_now=120
    )
    machine_config(machine=dict(MACHINE, cpus=64, memory_gib=512)).validate(
        os_name="darwin"
    )


def test_containers_with_no_account_are_refused():
    assert (
        refusal_on(machine_config(machine={"cpus": 1, "disk_gib": 100}), "windows").code
        == "machine_account_missing"
    )
    assert (
        refusal_on(
            PodmanConfig.from_dict({"containers": [FULL_CONTAINER]}), "darwin"
        ).code
        == "machine_account_missing"
    )


def test_no_containers_and_no_account_pass():
    PodmanConfig.from_dict({"containers": []}).validate(os_name="windows")


@pytest.mark.parametrize(
    "ports, services",
    [
        (["5353:53/udp"], []),
        (["5353:53"], [{"port": 5353, "kind": "port", "protocols": ["tcp", "udp"]}]),
        (["5353:53"], [{"port": 5353, "kind": "port", "protocols": ["udp"]}]),
    ],
)
def test_windows_refuses_a_port_published_on_udp_and_the_macs_take_it(ports, services):
    container = {"name": "dns", "image": "img", "ports": ports, "services": services}
    config = machine_config(containers=[container])

    refusal = refusal_on(config, "windows")

    assert refusal.code == "udp_not_forwarded"
    assert refusal.params == {"name": "dns", "port": 5353}
    config.validate(os_name="darwin")
    config.validate(os_name="linux")


def test_windows_takes_a_port_on_tcp_and_a_web_service():
    container = {
        "name": "web",
        "image": "img",
        "ports": ["18080:80", "8443:443/tcp"],
        "services": [{"port": 18080, "kind": "web", "scheme": "http"}],
    }

    machine_config(containers=[container]).validate(os_name="windows")


FULL_CONTAINER = {"name": "redis", "image": "docker.io/library/redis:7"}


# --- hub containers ---

HUB_DIGEST = "sha256:" + "c" * 64


def hub_container(**overrides) -> dict:
    container = {
        "module": "demo",
        "name": "neutrino_demo",
        "image": {"digest": HUB_DIGEST, "sources": ["ghcr.io/acme/demo"]},
        "ports": [],
        "volumes": ["neutrino_demo_data:/data"],
        "environment": ["INDEX={pypi}"],
        "command": "",
        "is_autostart": True,
        "services": [],
        "source_sets": ["pypi"],
        "after": [],
        "page_port": 8080,
    }
    container.update(overrides)
    return container


def hub_with(*containers) -> PodmanConfig:
    return PodmanConfig.from_dict(
        {"containers": [], "hub_containers": list(containers)}
    )


def test_a_hub_container_parses_and_survives_a_round_trip():
    config = hub_with(
        hub_container(),
        hub_container(name="neutrino_demo_db", after=["neutrino_demo"], page_port=0),
    )

    config.validate()

    assert PodmanConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()
    assert config.to_dict()["hub_containers"][0]["image"] == {
        "digest": HUB_DIGEST,
        "sources": ["ghcr.io/acme/demo"],
    }
    assert config.hub_names() == {"demo": ["neutrino_demo", "neutrino_demo_db"]}
    assert config.hub_containers[0].network == "neutrino_demo"


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"name": "demo"}, "container_name_invalid"),
        ({"name": "neutrino_other"}, "container_name_invalid"),
        ({"module": "Demo"}, "container_name_invalid"),
        (
            {"image": {"digest": "sha256:short", "sources": ["ghcr.io/a/b"]}},
            "image_invalid",
        ),
        ({"image": {"digest": HUB_DIGEST, "sources": []}}, "image_invalid"),
        (
            {"image": {"digest": HUB_DIGEST, "sources": ["ghcr.io/a/b:1"]}},
            "image_invalid",
        ),
        ({"volumes": ["/srv:/data"]}, "volume_invalid"),
        ({"volumes": ["other_data:/data"]}, "volume_invalid"),
        ({"environment": ["not an entry"]}, "environment_invalid"),
        ({"after": ["neutrino_demo_ghost"]}, "container_unknown"),
        ({"after": ["neutrino_demo"]}, "container_unknown"),
        ({"page_port": 70000}, "port_mapping_invalid"),
        ({"source_sets": ["PyPI"]}, "environment_invalid"),
    ],
)
def test_a_hub_container_the_agent_cannot_render_is_refused(overrides, code):
    assert refused_code(hub_with(hub_container(**overrides))) == code


def test_a_hub_container_cannot_share_a_declared_container_s_name():
    config = PodmanConfig.from_dict(
        {
            "containers": [{"name": "neutrino_demo", "image": "nginx"}],
            "hub_containers": [hub_container()],
        }
    )

    assert refused_code(config) == "container_name_duplicate"


def test_a_machine_with_hub_containers_needs_an_account():
    config = PodmanConfig.from_dict(
        {"hub_containers": [hub_container()], "machine": {"account": "", "disk_gib": 9}}
    )

    with pytest.raises(ModuleApplyError) as refused:
        config.validate(os_name="windows")

    assert refused.value.code == "machine_account_missing"


def test_with_hub_containers_leaves_the_configuration_as_it_was():
    config = hub_with(hub_container())

    narrowed = config.with_hub_containers([])

    assert narrowed.hub_containers == []
    assert len(config.hub_containers) == 1
