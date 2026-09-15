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
