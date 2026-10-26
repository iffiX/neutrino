# The File share module

The `samba` module is the file share: Samba on Linux, and the system's own
SMB server on Windows and macOS ([agent.md](../../agent.md), "Which modules
each system runs").

Its one setting is its enabled accounts. For each it serves one share, named
after the account, at the account's share path, to one SMB user with a
password the hub generates ([agent.md](../../agent.md), "The file share's
accounts"); the module keeps no share list and no user list of its own, and
a client mounts a share with the user and the password the `service` frame
hands it. The module has no import: a Samba a person set up by hand reads
`installed`, and on Linux the first apply replaces its `smb.conf` whole with
the enabled accounts' shares, which the tab says before that apply.

The file share on Windows and macOS is the one module that changes what the
person set up. On Linux it owns the whole `smb.conf`; on Windows and macOS it
owns who reaches the system's SMB server. It changes only the shares and
accounts it made, the ones its record under the state root lists and its
marker names, but its fence covers every share on the machine, the person's
own included.

Removing the agent's package takes away what the agent added in order to
run and to fence, and leaves what the machine serves. On every system the
shares and the accounts stay as they are and the system's SMB server goes on
serving them. The agent's own units, scheduled tasks, firewall rules and
fence go with the package, and so do its modules' Windows services, found
by name as the rest are. An agent installed again imports nothing it
finds: the enabled accounts the hub holds for the machine decide, and its
first apply makes the machine match them. On Linux that apply replaces
`smb.conf` whole and sets each SMB user's password from `passwords`. On
Windows and macOS, when the module's record under the state root was kept,
the shares and accounts it lists are the module's again. When the record is
gone, an account its marker names is the module's again, and a share left
under an enabled account's name is not, so the apply refuses it
`share_name_taken {name}` until the person removes that share.

Its journal on Windows reads the SMB server's latest events from
`Microsoft-Windows-SMBServer/Operational`, and on macOS what the unified
log holds of `smbd` over the last 15 minutes ([agent.md](../../agent.md),
"Which modules each system runs").
