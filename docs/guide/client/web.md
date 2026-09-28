---
title: Web
---

# Web

Links every joined hub offers appear in the **Web** panel, each with an **Open** button for your browser.

The panel lists each hub's links, hub by hub. An entry is Gitea, from the Gitea module on a managed machine, or a web address declared by hand on the hub's **Services** page. The line under the address names the hub, the machine and the module, such as **from Neutrino:Argon:Gitea**, and a hand-declared address shows its own name as the module. A panel with no entry reads **no web service is offered**. **Open** opens the link in the computer's default browser. From a terminal, `nclient service web open <ref>` does the same. `<ref>` is the entry's number under its hub in `nclient service list`, or its id, and `--hub` takes the hub's name unless only one is joined. An entry the hub cannot reach right now is greyed and reads **not reachable now**.
