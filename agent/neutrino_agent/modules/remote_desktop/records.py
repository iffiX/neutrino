"""The Remote desktop module's records under the state root, read and
written whole.

Not pure: reads and writes files.
"""

import contextlib
import json
import os
import time

try:
    import fcntl
except ImportError:  # Windows carries no fcntl.
    fcntl = None
try:
    import msvcrt
except ImportError:  # Only Windows carries msvcrt.
    msvcrt = None

# How often a held lock is tried again.
LOCK_POLL_S = 0.2


def read_json(path: str) -> dict:
    """One record.

    Args:
        path: The file.

    Returns:
        Its object; empty when the file is missing or holds no object.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@contextlib.contextmanager
def held(path: str):
    """Hold a lock file across processes for one change of RustDesk's
    registration, waiting while another process holds it.

    ``nagent leave`` runs in its own process while the service answers the
    hub's ``binding_unknown`` with the same give back; one waits for the
    other. The system frees the lock when its process ends.

    Args:
        path: The lock's file; its directory is made, root's own.

    Yields:
        Nothing; the lock is held inside the block.

    Raises:
        OSError: When the file cannot be opened.
    """
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(LOCK_POLL_S)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif msvcrt is not None:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(descriptor)


def write_json(path: str, data: dict) -> None:
    """Write one record where only root reads it.

    Args:
        path: The file.
        data: The object.

    Raises:
        OSError: When the file cannot be written.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    temporary = f"{path}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
    os.replace(temporary, path)
