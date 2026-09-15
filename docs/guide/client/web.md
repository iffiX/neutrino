---
title: Web
---

# Web

Links a hub publishes appear in the **Web** panel of that hub's group, each with an **Open** button for your browser.

An entry in the panel is a link the hub of its group published. It is Gitea, from the Gitea module on a managed machine, or a web address declared by hand on the hub's **Services** page. The line under the entry says which, and each hub publishes into its own group. **Open** opens the link in the computer's default browser. From a terminal, `nclient service web open <ref>` does the same. `<ref>` is the entry's number under its hub in `nclient service list`, or its id, and `--hub` takes the hub's name unless only one is joined. An entry the hub cannot reach right now is greyed and reads **not reachable now**.
