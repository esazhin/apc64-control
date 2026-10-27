"""VersionStore: a copy of every layout version that went live, under <state>/versions/<layout>/
<timestamp>-<hash>.yaml, outside the repository (contract §7, s59/s84, d117–d121, A55).

Every version is kept (d119). Timestamps are sortable UTC stamps (20261023T104200.123Z) and strictly
increase per layout, so list() is newest first even for saves within one millisecond. Files are written
temp + rename, so a crash never leaves half a version.
"""
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from ..domain.layout import ContentHash, LayoutId, VersionId

SUFFIX = ".yaml"


def stamp(moment: datetime) -> str:
    moment = moment.astimezone(UTC)
    return f"{moment:%Y%m%dT%H%M%S}.{moment.microsecond // 1000:03d}Z"


def parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=UTC)


class FileVersionStore:
    def __init__(self, state_dir, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._root = Path(state_dir).expanduser() / "versions"
        self._now = now

    def save(self, layout: LayoutId, text: str, content_hash: ContentHash) -> VersionId:
        directory = self._root / LayoutId(layout)
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = stamp(self._now())
        existing = self.list(layout)
        if existing and existing[0].timestamp >= timestamp:
            timestamp = stamp(parse_stamp(existing[0].timestamp) + timedelta(milliseconds=1))
        version = VersionId(timestamp, ContentHash(content_hash))
        target = directory / f"{version.timestamp}-{version.hash}{SUFFIX}"
        temporary = target.with_name(target.name + ".tmp")
        with open(temporary, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return version

    def list(self, layout: LayoutId) -> list[VersionId]:
        directory = self._root / LayoutId(layout)
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        versions = []
        for name in names:
            if not name.endswith(SUFFIX):
                continue
            timestamp, _, digest = name[:-len(SUFFIX)].partition("-")
            if timestamp and digest:
                versions.append(VersionId(timestamp, ContentHash(digest)))
        return sorted(versions, reverse=True)

    def read(self, layout: LayoutId, version: VersionId) -> str | None:
        """The version's text; its hash may be shortened as in str(VersionId). None when unknown."""
        matches = [v for v in self.list(layout)
                   if v.timestamp == version.timestamp and v.hash.startswith(version.hash)]
        if len(matches) != 1:
            return None
        path = self._root / LayoutId(layout) / f"{matches[0].timestamp}-{matches[0].hash}{SUFFIX}"
        try:
            return path.read_bytes().decode("utf-8", "replace")
        except OSError:
            return None
