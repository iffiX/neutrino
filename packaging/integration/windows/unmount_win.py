# Detach the V: mapping made by mount_win.py, leaving Explorer open so a
# screenshot shows whether the drive is gone rather than a red cross.
import os, sys, time, traceback

sys.path.insert(0, r"C:\Program Files\Neutrino Client")
log = open(r"C:\out\unmount_win.txt", "w", encoding="utf-8")
try:
    from neutrino_client.platforms.windows import WindowsPlatform

    platform = WindowsPlatform()
    log.write("attached before: %s\n" % platform.is_share_attached(location="V:"))
    platform.detach_share(location="V:")
    log.write("attached after: %s\n" % platform.is_share_attached(location="V:"))
    log.write("exists after: %s\n" % os.path.exists(r"V:\\"))
    time.sleep(4)
except Exception:
    log.write(traceback.format_exc())
log.write("[done]\n")
log.close()
