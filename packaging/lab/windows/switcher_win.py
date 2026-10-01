# The Linux verification, on Windows, under the machine's own pythonw in the
# person's session, against the pushed source tree.
# cc-switch finds the profile through the shell, not the environment, so the
# real profile is used, with what was there put back afterwards.
import json, os, pathlib, shutil, sys, time, traceback

sys.path.insert(0, r"C:\src\client")
log = open(r"C:\out\switcher_win.txt", "w", encoding="utf-8", buffering=1)
home = pathlib.Path(os.environ["USERPROFILE"])
backup = home / "switcher_backup"


def stash():
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir()
    for name in (".claude", ".codex", ".gemini", ".cc-switch"):
        if (home / name).exists():
            shutil.move(str(home / name), str(backup / name))


def restore():
    for name in (".claude", ".codex", ".gemini", ".cc-switch"):
        if (home / name).exists():
            shutil.rmtree(home / name)
        if (backup / name).exists():
            shutil.move(str(backup / name), str(home / name))


try:
    stash()
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    (home / ".gemini").mkdir()
    (home / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                    "ANTHROPIC_AUTH_TOKEN": "sk-mine",
                },
                "permissions": {"allow": ["Bash"]},
                "hooks": {"PreToolUse": [{"matcher": "Bash"}]},
            }
        ),
        encoding="utf-8",
    )
    (home / ".codex" / "config.toml").write_text(
        'model = "old"\napproval_policy = "on-request"\n\n[mcp_servers.mine]\ncommand = "my-server"\nargs = ["--flag"]\n',
        encoding="utf-8",
    )
    (home / ".gemini" / ".env").write_text(
        "GEMINI_API_KEY=mine\nMY_OWN_VAR=keep\n", encoding="utf-8"
    )
    from neutrino_client.services import switcher

    def show(tag):
        log.write(f"\n===== {tag}\n")
        for rel in (".claude/settings.json", ".codex/config.toml", ".gemini/.env"):
            p = home / rel
            log.write(f"--- {rel}: {'(absent)' if not p.exists() else ''}\n")
            if p.exists():
                log.write(p.read_text(encoding="utf-8").rstrip() + "\n")

    cfg = {
        "claude": {"default": "m1", "opus": "mo", "sonnet": "ms", "haiku": "mh"},
        "codex": {"model": "c1", "model_reasoning_effort": "low"},
        "gemini": {"model": "g1"},
    }
    t0 = time.monotonic()
    log.write(
        "activate: "
        + switcher.activate(
            base_url="http://hub:8080",
            api_key="sk-test",
            tool_configs=cfg,  # scan: allow
        )
        + "\n"
    )
    log.write("first activation took %.2fs\n" % (time.monotonic() - t0))
    show("after first activation")
    log.write(
        "is_active: %s\n"
        % switcher.is_active(base_url="http://hub:8080", api_key="sk-test", model="m1")
    )
    cfg["claude"]["default"] = "m2"
    cfg["codex"]["model_reasoning_effort"] = "high"
    t0 = time.monotonic()
    log.write(
        "activate again: "
        + switcher.activate(
            base_url="http://hub:8080", api_key="sk-test", tool_configs=cfg
        )
        + "\n"
    )
    log.write("second activation took %.2fs\n" % (time.monotonic() - t0))
    t0 = time.monotonic()
    log.write(
        "activate same: "
        + switcher.activate(
            base_url="http://hub:8080", api_key="sk-test", tool_configs=cfg
        )
        + "\n"
    )
    log.write("unchanged activation took %.2fs\n" % (time.monotonic() - t0))
    show("after second activation (m2, high)")
    t0 = time.monotonic()
    log.write("deactivate: " + switcher.deactivate(base_url="http://hub:8080") + "\n")
    log.write("deactivation took %.2fs\n" % (time.monotonic() - t0))
    show("after deactivation")
    log.write(
        "records: %r\n" % {a: switcher._read_record(a) for a in switcher.SWITCHER_APPS}
    )
except Exception:
    log.write(traceback.format_exc())
finally:
    restore()
log.write("[done]\n")
log.close()
