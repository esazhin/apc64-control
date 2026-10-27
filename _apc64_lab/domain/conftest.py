"""Lab domain test fixtures: the captured project and global dumps (fixtures/ at the repository root)."""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def snapshot_frames() -> list[bytes]:
    """The 25 project dumps of fixtures/apc64-snapshot-2026-10-22.hex (identity line skipped), slot order."""
    frames = []
    for line in (FIXTURES / "apc64-snapshot-2026-10-22.hex").read_text().splitlines():
        if line.startswith("F0 47 00 53 14"):
            frames.append(bytes.fromhex(line))
    return frames


@pytest.fixture
def factory_frame() -> bytes:
    return fixture_bytes("apc64-factory-project.syx")


@pytest.fixture
def global_frame() -> bytes:
    return fixture_bytes("apc64-global-settings-2026-10-22.syx")
