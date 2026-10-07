"""The retry marks a press on a failed module puts into a device's state.

A mark is a short random token in a module's entry of the state, or in its
``ai_tools`` section. It means nothing to anything that reads the
configuration; it changes the state's hash, so an agent that tried the
state once and failed tries it again. The marks are the hub's own record of
presses, not a decision anybody wrote, so they live under the state root,
one per module and device, each press replacing the one before, and a
device's marks go with the device.
"""

import json
import secrets

from neutrino_hub.modules.devices.constants import (
    DEVICE_RETRY_MARK_BYTES,
    DEVICE_RETRY_MARKS_PATH,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK, write_generated


class DeviceRetryMarks:
    """Reads and writes the retry marks of every device."""

    def __init__(self, *, path=None):
        """
        Args:
            path: The file; the hub's state root's when None.
        """
        self._path = path or DEVICE_RETRY_MARKS_PATH

    def marks(self, device_id: str) -> dict:
        """One device's marks.

        Args:
            device_id: The device.

        Returns:
            Module name, or ``ai_tools``, to its mark; empty when none.
        """
        held = self._read().get(device_id)
        return dict(held) if isinstance(held, dict) else {}

    def mark(self, device_id: str, name: str) -> str:
        """Put a fresh mark on one module, or on ``ai_tools``.

        Args:
            device_id: The device.
            name: The module name, or ``ai_tools``.

        Returns:
            The new mark.

        Raises:
            OSError: When the file cannot be written.
        """
        mark = secrets.token_hex(DEVICE_RETRY_MARK_BYTES)
        with CONFIG_WRITE_LOCK:
            held = self._read()
            device = held.get(device_id)
            device = dict(device) if isinstance(device, dict) else {}
            device[name] = mark
            held[device_id] = device
            self._write(held)
        return mark

    def drop(self, device_id: str, name: str) -> None:
        """Drop one module's mark, or the AI tools'.

        Args:
            device_id: The device.
            name: The module name, or ``ai_tools``.

        Raises:
            OSError: When the file cannot be written.
        """
        with CONFIG_WRITE_LOCK:
            held = self._read()
            device = held.get(device_id)
            if not isinstance(device, dict) or device.pop(name, None) is None:
                return
            if device:
                held[device_id] = device
            else:
                held.pop(device_id)
            self._write(held)

    def forget(self, device_id: str) -> None:
        """Drop one device's marks.

        Args:
            device_id: The device.

        Raises:
            OSError: When the file cannot be written.
        """
        with CONFIG_WRITE_LOCK:
            held = self._read()
            if held.pop(device_id, None) is not None:
                self._write(held)

    def _read(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        return held if isinstance(held, dict) else {}

    def _write(self, held: dict) -> None:
        write_generated(self._path, json.dumps(held, sort_keys=True), mode=0o600)
