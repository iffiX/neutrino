---
title: Web
---

# Web

Web services the hub publishes appear in the client's **Web** panel, each with an **Open** button for your browser.

An entry in the panel is a link the hub published. It is Gitea, from the Gitea module on a managed machine, or a web address declared by hand on the hub's **Services** page. The line under the entry says which. **Open** opens the link in the computer's default browser. From a terminal, `nclient service web open <ref>` does the same, where `<ref>` is the entry's number in `nclient service list` or its id. An entry the hub cannot reach right now is greyed and reads **not reachable now**.
