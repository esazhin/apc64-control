"""OLED text: two ASCII rows, cut to 14 characters (the safe length while rows and length are [TBD])."""
from dataclasses import dataclass

OLED_WIDTH = 14
TRANSIENT_SECONDS = 2.0   # a layout, page or bank name shows for about 2 s


_ASCII_STAND_INS = str.maketrans({"→": ">", "–": "-", "—": "-"})   # the host's own label punctuation


def oled_cut(text: str) -> str:
    """What the OLED shows for a text: non-ASCII as '?', cut to 14, trailing spaces trimmed (d109, d110).

    The arrows and dashes of generated labels ('CC30 → mpc') are shown as their ASCII look-alikes.
    """
    ascii_only = "".join(ch if " " <= ch <= "~" else "?" for ch in str(text).translate(_ASCII_STAND_INS))
    return ascii_only[:OLED_WIDTH].rstrip()


def name_warning(what: str, name: str) -> str | None:
    """The validation warning for a name the OLED cannot show in full, or None (contract d109, A43)."""
    if oled_cut(name) == name:
        return None
    if len(name) > OLED_WIDTH:
        return f'{what} name longer than {OLED_WIDTH} characters, OLED shows "{oled_cut(name)}"'
    return f'{what} name has characters the OLED cannot show, OLED shows "{oled_cut(name)}"'


@dataclass(frozen=True)
class OledText:
    row0: str = ""
    row1: str = ""

    def __post_init__(self):
        object.__setattr__(self, "row0", oled_cut(self.row0))
        object.__setattr__(self, "row1", oled_cut(self.row1))

    @property
    def rows(self) -> tuple[str, str]:
        return (self.row0, self.row1)

    @classmethod
    def blank(cls) -> "OledText":
        return cls("", "")

    @classmethod
    def no_layout(cls) -> "OledText":
        return cls("No layout", "")

    @classmethod
    def idle(cls, layout_name: str, page_no: int | None, page_name: str | None,
             bank_no: int | None, bank_name: str | None) -> "OledText":
        """At rest: row 0 the layout name, row 1 'P<n> <page> | B<n> <bank>' (contract d108)."""
        parts = []
        if page_no is not None:
            parts.append(f"P{page_no} {page_name}".rstrip() if page_name else f"P{page_no}")
        if bank_no is not None:
            parts.append(f"B{bank_no} {bank_name}".rstrip() if bank_name else f"B{bank_no}")
        return cls(layout_name, " | ".join(parts))

    @classmethod
    def transient(cls, name: str, context: str = "") -> "OledText":
        """A name shown for ~2 s after a change: the name on row 0, what changed on row 1."""
        return cls(name, context)
