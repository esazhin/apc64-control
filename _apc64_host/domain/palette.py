"""The one colour table: name ↔ palette index ↔ approximate RGB.

The APC64 indexes Ableton's 128-colour clip palette (PROTOCOL-SPEC §6). The RGB the unit really shows for
each index is [TBD], so the RGB here is the common Ableton/Launchpad table and is only an APPROXIMATION
(contract S: never present it as the unit's exact colours).
"""
from dataclasses import dataclass, field

from .issues import DomainInvariantError

APPROXIMATE = True
APPROXIMATION_NOTE = "approximate colours (Ableton palette); the APC64's exact RGB is not known"

_RGB_HEX = (
    "000000 1E1E1E 7F7F7F FFFFFF FF4C4C FF0000 590000 190000 FFBD6C FF5400 591D00 271B00 FFFF4C FFFF00 "
    "595900 191900 88FF4C 54FF00 1D5900 142B00 4CFF4C 00FF00 005900 001900 4CFF5E 00FF19 00590D 001902 "
    "4CFF88 00FF55 00591D 001F12 4CFFB7 00FF99 005935 001912 4CC3FF 00A9FF 004152 001019 4C88FF 0055FF "
    "001D59 000819 4C4CFF 0000FF 000059 000019 874CFF 5400FF 190064 0F0030 FF4CFF FF00FF 590059 190019 "
    "FF4C87 FF0054 59001D 220013 FF1500 993500 795100 436400 033900 005735 00547F 0000FF 00454F 2500CC "
    "7F7F7F 202020 FF0000 BDFF2D AFED06 64FF09 108B00 00FF87 00A9FF 002AFF 3F00FF 7A00FF B21A7D 402100 "
    "FF4A00 88E106 72FF15 00FF00 3BFF26 59FF71 38FFCC 5B8AFF 3151C6 877FE9 D31DFF FF005D FF7F00 B9B000 "
    "90FF00 835D07 392B00 144C10 0D5038 15152A 16205A 693C1C A8000A DE513D D86A1C FFE126 9EE12F 67B50F "
    "1E1E30 DCFF6B 80FFBD 9A99FF 8E66FF 404040 757575 E0FFFF A00000 350000 1AD000 074200 B9B000 3F3100 "
    "B35F00 4B1502"
).split()
assert len(_RGB_HEX) == 128

# Fixed names (contract a26); the first name of an index is the one written back by tweaks
NAMES = {
    "off": 0, "dimwhite": 1, "grey": 2, "white": 3, "red": 5, "orange": 9, "yellow": 13, "lime": 17,
    "green": 21, "mint": 29, "teal": 33, "cyan": 37, "blue": 45, "purple": 49, "magenta": 53, "pink": 57,
}
ALIASES = {"black": 0, "dim": 1, "gray": 2, "violet": 49}
_LOOKUP = {**NAMES, **ALIASES}


def _key(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch not in " -_")


@dataclass(frozen=True)
class Colour:
    """A palette index; the name it was written with is kept for display only."""
    index: int
    name: str | None = field(default=None, compare=False)

    def __post_init__(self):
        if isinstance(self.index, bool) or not isinstance(self.index, int) or not 0 <= self.index <= 127:
            raise DomainInvariantError("colour", "colour index must be 0–127",
                                       f"write a colour name ({', '.join(NAMES)}) or an index 0–127")

    @property
    def rgb(self) -> tuple[int, int, int]:
        return approx_rgb(self.index)

    @property
    def is_off(self) -> bool:
        return self.index == 0

    def __str__(self) -> str:
        return self.name or name_of(self.index) or str(self.index)


OFF = Colour(0, "off")
WHITE = Colour(3, "white")


@dataclass(frozen=True)
class PaletteEntry:
    name: str | None
    index: int
    rgb: tuple[int, int, int]


def approx_rgb(index: int) -> tuple[int, int, int]:
    value = int(_RGB_HEX[index], 16)
    return (value >> 16, (value >> 8) & 0xFF, value & 0xFF)


def name_of(index: int) -> str | None:
    return next((name for name, i in NAMES.items() if i == index), None)


def parse_colour(text) -> Colour:
    """A colour name (case, spaces and dashes ignored: 'Dim White' = 'dimwhite') or an index 0–127."""
    if isinstance(text, int) and not isinstance(text, bool):
        return Colour(text)
    raw = str(text).strip()
    if raw.isdigit():
        return Colour(int(raw))
    key = _key(raw)
    if key not in _LOOKUP:
        raise DomainInvariantError("colour", f"unknown colour '{raw}'",
                                   f"use one of {', '.join(NAMES)} or an index 0–127")
    return Colour(_LOOKUP[key], key if key in NAMES else name_of(_LOOKUP[key]))


def palette() -> tuple[PaletteEntry, ...]:
    """All 128 entries, for the page's colour picker and approximate rendering."""
    return tuple(PaletteEntry(name_of(i), i, approx_rgb(i)) for i in range(128))
