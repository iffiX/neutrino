"""What `nhub apply` renders: the hub's own components and nothing hosted."""

from neutrino_hub.cli import apply


def test_the_components_are_the_hubs_own():
    """A device hosts the file share, the git server, the containers and the
    storage from its desired state; the hub renders none of them."""
    assert apply.COMPONENTS == (
        "router",
        "xray",
        "dnsmasq",
        "cliproxyapi",
        "easytier",
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
