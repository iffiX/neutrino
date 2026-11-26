"""The shared folders' entries on macOS: each account named by its UUID, the inherited entries of the two accounts on a write folder, the default account's alone on a read folder, and every file under them set on its own descriptor."""

import os

import pytest

from neutrino_agent.modules.comfyui import darwin_access


def test_a_macs_entries_name_each_account_by_its_uuid():
    text = darwin_access.acl_text(
        [("UUID-1", "anna", 501, darwin_access.INHERITED, darwin_access.FOLDER_WRITE)]
    )
    assert text == (
        "!#acl 1\n"
        "user:UUID-1:anna:501:allow,file_inherit,directory_inherit:"
        "list,add_file,search,delete,add_subdirectory,delete_child,"
        "readattr,writeattr,readextattr,writeextattr,readsecurity\n"
    )
    assert darwin_access.file_rights(0o755, False).endswith(",execute")


class Acl:
    def __init__(self):
        self.lists = []

    def uuid_of(self, uid):
        return f"UUID-{uid}"

    def set_fd(self, descriptor, text):
        self.lists.append((os.readlink(f"/proc/self/fd/{descriptor}"), text))


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="no /proc")
def test_a_macs_shared_folders_take_the_entries_of_the_two_accounts(tmp_path):
    data = tmp_path / "comfyui_data"
    base = data / "data"
    for name in ("models", "input", "output", "user", "custom_nodes"):
        os.makedirs(base / name)
    (base / "models" / "m.safetensors").write_bytes(b"m")
    acl = Acl()
    darwin_access.DarwinFolderAccess(
        data_dir=str(data),
        base_dir=str(base),
        service=("neutrino_comfyui", 300),
        acl=acl,
    ).write(("anna", 501))
    lists = dict(acl.lists)
    assert "user:UUID-501:anna:501:allow:search" in lists[str(data)]
    assert "allow:list,search" in lists[str(base)]
    models = lists[str(base / "models")]
    assert "UUID-300:neutrino_comfyui:300:allow,file_inherit" in models
    assert "UUID-501:anna:501:allow,file_inherit" in models
    assert "neutrino_comfyui" not in lists[str(base / "user")]
    assert "allow:read,write" in lists[str(base / "models" / "m.safetensors")]
