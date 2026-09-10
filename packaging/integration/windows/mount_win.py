# A real mapping through WNetAddConnection2 in the person's session, then
# Explorer is opened so a screenshot can show the drive.
import os, subprocess, sys, tempfile, time, traceback

sys.path.insert(0, r"C:\Program Files\Neutrino Client")
log = open(r"C:\out\mount_win.txt", "w", encoding="utf-8")
try:
    from neutrino_client.platforms.windows import WindowsPlatform

    platform = WindowsPlatform()
    subprocess.run(["net", "use", "V:", "/delete", "/y"], capture_output=True)
    creds = os.path.join(tempfile.mkdtemp(), "share.credentials")
    open(creds, "w").write("username=neutrino\npassword=neutrino\n")
    log.write("free letters: %s\n" % platform.mount_location_choices()[:4])
    platform.attach_share(
        share_url="//localhost/probe", location="V:", credentials_path=creds
    )
    log.write("attached: %s\n" % platform.is_share_attached(location="V:"))
    log.write("readable: %s\n" % os.path.exists(r"V:\readme.txt"))
    subprocess.Popen(["explorer.exe", "shell:MyComputerFolder"])
    time.sleep(8)
    log.write("explorer opened\n")
except Exception:
    log.write(traceback.format_exc())
log.write("[done]\n")
log.close()
