# The ZFS storage module

The `zfs` module is ZFS storage: the pools and datasets of a Linux machine,
and of no other system ([agent.md](../../agent.md), "Which modules each
system runs"). Its entry in the state, its verbs and its routes are in
[protocol.md](../../protocol.md), "The modules section, one entry per
module".

The install puts the ZFS tools on the machine and, where the distribution
ships no ZFS kernel module, builds one for the running kernel. The check is
the recipe's `verify`, `modprobe zfs && zpool --version`, so a machine
whose kernel changed after the install, with no ZFS module built for the
new kernel, reads `absent` while `zpool` is installed. That row carries
`zfs_kernel_module_missing {kernel}`, `kernel` being the running kernel's
release as `uname -r` prints it ([agent.md](../../agent.md), "Status is
typed"). **Install** runs the install's steps again, which build the module
for the running kernel.
