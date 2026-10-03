"""What `nhub apply` renders: the hub's own components and nothing hosted."""

from neutrino_hub.cli import apply
from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.ops import EASYTIER_CONFIG_NAME
from neutrino_hub.modules.overlay.config import set_enabled
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.utils.json_file import write_config
from tests.conftest import unlock_vault


def test_the_components_are_the_hubs_own():
    """A device hosts the file share, the git server, the containers and the
    storage from its desired state; the hub renders none of them."""
    assert apply.COMPONENTS == (
        "router",
        "xray",
        "dnsmasq",
        "cliproxyapi",
        "overlay",
    )


def test_apply_removes_a_device_directory_no_stored_device_names(tmp_path, monkeypatch):
    """The sweep keeps the directory of every stored id, and the packages
    directory beside them."""
    from neutrino_hub.modules.devices import desired_state as desired_state_module
    from neutrino_hub.modules.devices.registry import DeviceRegistry

    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    kept = DeviceRegistry().create("kept").id
    for name in (kept, "aa-bb-cc-dd-ee-ff", "packages"):
        (tmp_path / "devices" / name).mkdir(parents=True)

    removed = apply._forget_orphan_device_dirs()

    assert removed == ["aa-bb-cc-dd-ee-ff"]
    assert (tmp_path / "devices" / kept).is_dir()
    assert (tmp_path / "devices" / "packages").is_dir()
    assert not (tmp_path / "devices" / "aa-bb-cc-dd-ee-ff").exists()


# --- dnsmasq: one install, and one restart only when it moved ---


def test_an_apply_installs_dnsmasq_through_the_one_shared_function(monkeypatch):
    """The panel and the command line write and restart dnsmasq the same way,
    so neither can overwrite the other's file and restart over it."""
    installed = []
    monkeypatch.setattr(
        apply, "install_dnsmasq", lambda config: installed.append(config) or True
    )

    apply._apply({"dnsmasq": "interface=enp1s0\n"})

    assert installed == ["interface=enp1s0\n"]


def test_a_run_that_restarts_nothing_still_leaves_the_file_the_unit_names(
    monkeypatch,
):
    """`--skip-apply` writes the generated files. The dnsmasq unit points at
    this one, so it has to be there even when nothing is restarted."""
    written = []
    monkeypatch.setattr(
        apply, "write_generated", lambda path, text: written.append((str(path), text))
    )

    apply._write({"dnsmasq": "interface=enp1s0\n"}, is_apply_skipped=True)

    assert written == [(str(apply.ROUTER_DNSMASQ_PATH), "interface=enp1s0\n")]


def test_an_apply_does_not_write_the_file_before_installing_it(monkeypatch):
    """A file written first would match whatever `install_dnsmasq` compares
    against, and dnsmasq would never be restarted on a real change."""
    written = []
    monkeypatch.setattr(
        apply, "write_generated", lambda path, text: written.append(str(path))
    )

    apply._write({"dnsmasq": "interface=enp1s0\n"}, is_apply_skipped=False)

    assert written == []


# --- overlays: the enabled ones run, EasyTier rendered only when enabled ---


def _stored_easytier(tmp_path, monkeypatch, providers: list) -> None:
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    network = RouterNetworkConfig.from_dict({"overlays": []})
    for provider in providers:
        set_enabled(network, provider, is_enabled=True)
    write_config("router/network.json", network.to_dict())
    write_config("xray/routing.json", {})
    stored = EasyTierConfig(mode="console")
    stored.set_config_server("etk_example")  # scan: allow
    write_config(EASYTIER_CONFIG_NAME, stored.to_dict())


def test_an_apply_renders_easytier_when_it_is_enabled(tmp_path, monkeypatch):
    _stored_easytier(tmp_path, monkeypatch, ["netbird", "easytier"])

    assert apply._render(("overlay",))["easytier"].is_console_mode


def test_an_apply_leaves_easytier_down_when_it_is_off(tmp_path, monkeypatch):
    """A package upgrade runs this; a stored network must not start an
    overlay nobody turned on."""
    _stored_easytier(tmp_path, monkeypatch, ["netbird"])

    assert "easytier" not in apply._render(("overlay",))


class _RecordingSwitcher:
    calls: list = []

    def start(self, network, *, report=None):
        _RecordingSwitcher.calls.append("start")
        return []

    def stop(self, network, *, report=None):
        _RecordingSwitcher.calls.append("stop")
        return []


def test_an_apply_starts_the_overlays_first_and_stops_them_last(monkeypatch):
    """The command line runs the panel's converge steps in the panel's order,
    the two pushes left out."""
    _RecordingSwitcher.calls = []
    monkeypatch.setattr(apply, "OverlaySwitcher", _RecordingSwitcher)
    monkeypatch.setattr(
        apply,
        "install_dnsmasq",
        lambda config: _RecordingSwitcher.calls.append("dnsmasq") or True,
    )

    class Controller:
        def reconcile(self):
            _RecordingSwitcher.calls.append("router")
            return []

    monkeypatch.setattr(apply, "RouterStateController", Controller)

    apply._apply(
        {
            "overlay": RouterNetworkConfig.from_dict({}),
            "router": "",
            "dnsmasq": "interface=enp1s0\n",
        }
    )

    assert _RecordingSwitcher.calls == ["start", "router", "dnsmasq", "stop"]


def test_elsewhere_an_apply_renders_no_ruleset(elsewhere, tmp_path, monkeypatch):
    """No xray account and no nftables there; the routing pass still runs."""
    _stored_easytier(tmp_path, monkeypatch, [])

    def refuse():
        raise AssertionError("looked up the xray account")

    monkeypatch.setattr(apply, "lookup_xray_uid", refuse)

    assert apply._render(("router",)) == {"router": ""}
