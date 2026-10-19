"""Fixed values of the frp module."""

from neutrino_hub.utils.constants import carried_program

# The upstream frpc (fatedier/frp, Apache-2.0) every hub package carries.
# packaging/shared/hub_assets.py reads the asset each system and machine takes
# from this release, and its hash, from the table below.
FRP_VERSION = "0.71.1"
FRP_RELEASE_URL = "https://github.com/fatedier/frp/releases/download/v{version}/{asset}"
FRP_ASSETS = {
    ("linux", "amd64"): (
        "frp_0.71.1_linux_amd64.tar.gz",
        "1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803",  # scan: allow
    ),
    ("linux", "arm64"): (
        "frp_0.71.1_linux_arm64.tar.gz",
        "8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019",  # scan: allow
    ),
    ("darwin", "amd64"): (
        "frp_0.71.1_darwin_amd64.tar.gz",
        "8acb59b6fb998cc8d209d1373d90bf70fa5ec3efeb4dfbc7bda6ce3abd78cb45",  # scan: allow
    ),
    ("darwin", "arm64"): (
        "frp_0.71.1_darwin_arm64.tar.gz",
        "d15d0324b99e14619c9aa46e37f6db588c06a09be4bc6f7948890b6b61077842",  # scan: allow
    ),
    ("windows", "amd64"): (
        "frp_0.71.1_windows_amd64.zip",
        "b90074b2b6a1d792a7a40f085ac6d276bcab2d1bc60201f8a86ca53ce65ce821",  # scan: allow
    ),
}
FRP_BINARY_NAME = "frpc"
FRP_BINARY_PATH = carried_program(FRP_BINARY_NAME)
