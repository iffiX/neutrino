# The VS Code module

The `vscode` module runs Microsoft's standalone CLI, `code serve-web`, once
per account on Linux, Windows and macOS ([protocol.md](../../protocol.md),
"The modules section, one entry per module"). A VS Code instance listens on
`127.0.0.1` alone, on every system. A client reaches it through a `connect`
stream ([agent.md](../../agent.md), "The connect stream"), and its token is
what admits a browser. How each system starts it is the "VS Code" row of the
platform table ([agent.md](../../agent.md), "The platform layer").
