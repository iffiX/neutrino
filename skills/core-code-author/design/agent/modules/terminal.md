# The Terminal module

The `terminal` module is one of the modules the agent's package carries
([agent.md](../../agent.md), "The kinds of module"). Its one setting is its
enabled accounts: the available accounts of the machine a `shell` or an
`exec` stream runs as ([agent.md](../../agent.md), "The two layers and the
accounts"). A stream names the account it runs as, and one that names none
runs as the first enabled account.

| Rule | Reason |
| --- | --- |
| A shell runs the account's shell, the `shell_path` of its row, or its login shell when that is empty, and PowerShell on Windows. On Linux and macOS it starts as a login shell, `<program> -l`. | The account form says once which shell the account uses, for the terminal and the SSH server alike. |
| A shell for an account starts in that account's home with that account's environment, through `run_as_account`'s step-down on Linux and macOS, on a pseudo-terminal of its own handed to that account. On Windows the agent logs the account on with its password and starts the shell under that token on a pseudo console ([agent.md](../../agent.md), "Acting for an account"). | The shell is that account's and nothing more, and Windows starts a process as another account only with its password. |
| With no enabled account the module refuses every open with `terminal_account_missing`; an account the module does not enable is refused `account_not_enabled {account}`, one the machine does not have `account_unknown {account}`, and a shell that is missing or not executable `shell_program_unusable {path}`. None falls back to root or to another account. | A shell the hub opens is never root's, and a refusal says which choice was wrong. |
| A shell opened afterwards runs as the module then says; a session already open keeps the account it runs as, and a container's shell is not touched. | Changing the enabled accounts never moves a person out of a shell they are in. |
