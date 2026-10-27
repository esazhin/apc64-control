"""Fixture captures from a real unit, as (port, bytes) per line: '<seconds> <PORT> <hex bytes…>'."""
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def capture(name: str) -> list[tuple[str, bytes]]:
    lines = []
    for line in (FIXTURES / name).read_text().splitlines():
        parts = line.split()
        if len(parts) < 3 or line.lstrip().startswith("#"):
            continue
        lines.append((parts[1], bytes(int(h, 16) for h in parts[2:])))
    return lines
