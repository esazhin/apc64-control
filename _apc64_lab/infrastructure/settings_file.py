"""LabSettingsStore over one small JSON file (the harmony inputs the user chose, §2.7 q7: remembered).

Written atomically like the backups. A missing or damaged file reads as no settings (the defaults), never as
an error: a remembered choice is a convenience, not state the lab depends on.
"""
import json
import logging
from pathlib import Path

from .backup_files import write_atomically

log = logging.getLogger(__name__)


class SettingsFile:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _read(self) -> dict:
        try:
            body = json.loads(self.path.read_text())
            return body if isinstance(body, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            log.warning("lab: %s is not readable (%s); using the defaults", self.path, error)
            return {}

    def get(self, key: str, default=None):
        return self._read().get(key, default)

    def put(self, key: str, value) -> None:
        body = self._read()
        body[key] = value
        write_atomically(self.path, (json.dumps(body, indent=1, sort_keys=True) + "\n").encode())
