"""LabWindow: where the window sits on the lattice (contract d33–d40, inv11); StepWindow: a generator's own window
steps and range (the guitar amendment, 2026-10-27).

Each interval keeps its own step count. The window is transposed by 12·octave + 7·fifth + 4·third semitones,
and the OLED shows the current interval's count ('5th +2'). A step that would push any active pad outside
0–127 is refused as an Edge: the window stays and row 2 adds 'edge' (d29). A multi-step message is taken or
refused as a whole (a build decision: the window never lands on a position nobody asked for).

Amendment (2026-10-27): a generator may declare its own window (a WindowSpec, the optional `window(params)` hook).
The window is then one position, the transposition in semitones, within the generator's range; Tempo cycles the
generator's step kinds and each encoder detent moves one step of the current kind: a fixed number of semitones,
or (a paged step) to the next or previous of the spec's page positions. A step beyond the range, past the last
page, or that would push a pad outside 0–127 is refused as an Edge, as above. A layout whose generator declares no
window keeps the LabWindow: Octave / Fifth / Third and only the 0–127 edge.

Row 2 as shown (2026-10-27, from the live test): a WindowSpec with a `unit` ('Frets') always shows what is on the
pads on row 2, 'Frets 8-15', whatever the step kind; the step kind and a refused step are brief messages instead
(flash_step: 'Step: Page', flash_edge: its `end_text`, 'Neck end'), which the session shows for about a second.
The page's window line keeps the step kind (label()). Without a unit, row 2 is as before ('Fret 3-10', 'Pg 17-24
edge'); a LabWindow has no flashes.
"""
from dataclasses import dataclass, field

from _apc64_host.domain.oled import OLED_WIDTH, OledText

from .music import Interval
from .pads import NoteSpan

EDGE = " edge"


def _counts(octave: int = 0, fifth: int = 0, third: int = 0) -> tuple[tuple[Interval, int], ...]:
    return ((Interval.OCTAVE, octave), (Interval.FIFTH, fifth), (Interval.THIRD, third))


@dataclass(frozen=True)
class LabWindow:
    interval: Interval = Interval.OCTAVE                      # d38: each activation starts at octave …
    counts: tuple[tuple[Interval, int], ...] = field(default_factory=_counts)   # … with every count at 0

    def count(self, interval: Interval | None = None) -> int:
        return dict(self.counts)[interval or self.interval]

    def transposition(self) -> int:
        return sum(interval.semitones * n for interval, n in self.counts)

    def label(self) -> str:
        return f"{self.interval.label} {self.count():+d}"

    def cycled(self) -> "LabWindow":
        """Tempo: the next interval; steps already counted keep their interval (d34)."""
        return LabWindow(self.interval.next(), self.counts)

    def stepped(self, steps: int) -> "LabWindow":
        """`steps` more of the current interval, unchecked."""
        counts = tuple((i, n + steps if i is self.interval else n) for i, n in self.counts)
        return LabWindow(self.interval, counts)

    def shifted(self, steps: int, span: NoteSpan | None) -> "LabWindow | Edge":
        """`steps` (±n) of the current interval, or Edge when `span` (the active notes at transposition 0)
        would leave 0–127."""
        moved = self.stepped(steps)
        if span is not None and not span.fits(moved.transposition()):
            return Edge(self, steps)
        return moved

    def oled(self, name: str, edge: bool = False) -> OledText:
        """Row 1 the layout name, row 2 interval and count (d40, d41: both cut to 14 characters)."""
        return OledText(name, self.label() + (EDGE if edge else ""))

    def flash_step(self, name: str) -> OledText | None:
        return None

    def flash_edge(self, name: str) -> OledText | None:
        return None

    def to_json(self) -> dict:
        """The window as the API shows it (the active layout's interval, offset, counts and window)."""
        return {"interval": self.interval.label, "offset": self.count(),
                "counts": {interval.name.lower(): n for interval, n in self.counts},
                "transposition": self.transposition(),
                "window": {"steps": [i.label for i in Interval], "step": self.interval.label,
                           "label": self.label()}}


# --- a generator's own window (amendment 2026-10-27) -----------------------------------------------------
@dataclass(frozen=True)
class WindowStep:
    """One kind of window step: `label` on the OLED and the page ('Fret'), `short` when row 2 with its edge marker
    would not fit in 14 characters ('Fr'), and either `semitones` per detent or `paged` (a detent moves to the next
    or previous page position of the WindowSpec)."""
    label: str
    short: str = ""
    semitones: int = 1
    paged: bool = False


@dataclass(frozen=True)
class WindowSpec:
    """A generator's window: its step kinds (Tempo cycles them, the first is where each activation starts), the
    transposition range `lowest`…`highest` (semitones), the page positions a paged step stops at, and `shown`:
    when > 0, row 2 shows the range of positions on the pads ('Fret 3-10': position 3, 8 shown), else the signed
    position ('Semi +3')."""
    steps: tuple[WindowStep, ...]
    lowest: int
    highest: int
    pages: tuple[int, ...] = ()
    shown: int = 0
    unit: str = ""          # row 2 names what is shown: '<unit> a-b' ('Frets 8-15'); the kind and the edge flash
    end_text: str = "end"   # the flash for a refused step when `unit` is set ('Neck end')

    def __post_init__(self):
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "pages", tuple(sorted(set(self.pages))))
        if not self.steps or self.lowest > self.highest:
            raise ValueError("a window has at least one step and lowest <= highest")

    @property
    def start(self) -> int:
        """Where each activation starts: transposition 0 when it is in range, else the nearer end."""
        return min(max(0, self.lowest), self.highest)

    def contains(self, position: int) -> bool:
        return self.lowest <= position <= self.highest

    def to_json(self) -> dict:
        return {"steps": [s.label for s in self.steps], "lowest": self.lowest, "highest": self.highest,
                "pages": list(self.pages), "shown": self.shown, "unit": self.unit or None}


@dataclass(frozen=True)
class StepWindow:
    """The window of a generator that declares its own (WindowSpec): one position (the transposition) and the
    current step kind. The same interface as LabWindow, so the session and the API treat both alike."""
    spec: WindowSpec
    step: int = 0           # index into spec.steps
    position: int = 0

    @classmethod
    def starting(cls, spec: WindowSpec) -> "StepWindow":
        return cls(spec, 0, spec.start)

    @property
    def kind(self) -> WindowStep:
        return self.spec.steps[self.step]

    @property
    def interval(self) -> WindowStep:   # LabWindow's name for the current step kind
        return self.kind

    def count(self) -> int:
        return self.position

    def transposition(self) -> int:
        return self.position

    def label(self, short: bool = False) -> str:
        name = (self.kind.short or self.kind.label) if short else self.kind.label
        if self.spec.shown > 0:
            return f"{name} {self.position}-{self.position + self.spec.shown - 1}"
        return f"{name} {self.position:+d}"

    def cycled(self) -> "StepWindow":
        """Tempo: the next step kind (Fret → Page → Fret); the position stays."""
        return StepWindow(self.spec, (self.step + 1) % len(self.spec.steps), self.position)

    def moved(self, steps: int) -> int | None:
        """The position `steps` detents of the current kind away, or None when that leaves the range (or runs past
        the first or last page)."""
        position = self.position
        if self.kind.paged:
            for _ in range(abs(steps)):
                ahead = [p for p in self.spec.pages if (p > position if steps > 0 else p < position)]
                if not ahead:
                    return None
                position = min(ahead) if steps > 0 else max(ahead)
        else:
            position += steps * self.kind.semitones
        return position if self.spec.contains(position) else None

    def shifted(self, steps: int, span: NoteSpan | None) -> "StepWindow | Edge":
        """`steps` (±n) detents of the current kind, taken or refused as a whole: Edge beyond the range or when
        `span` would leave 0–127."""
        position = self.moved(steps)
        if position is None or (span is not None and not span.fits(position)):
            return Edge(self, steps)
        return StepWindow(self.spec, self.step, position)

    def within(self, spec: WindowSpec | None) -> "StepWindow | None":
        """This window under a changed spec (a tweak reloaded the layout): the same kind and position when the new
        range still holds it, else None (the caller starts afresh)."""
        if spec is None or not spec.contains(self.position):
            return None
        return StepWindow(spec, self.step if self.step < len(spec.steps) else 0, self.position)

    def shown_range(self) -> str:
        return f"{self.position}-{self.position + self.spec.shown - 1}"

    def oled(self, name: str, edge: bool = False) -> OledText:
        """Row 1 the layout name. Row 2 with a unit: what the pads show ('Frets 8-15'), edge or not (the edge is a
        flash). Without: the step kind and the position ('Fret 3-10'); with the edge marker, the short kind when the
        full one would not fit ('Pg 17-24 edge')."""
        if self.spec.unit and self.spec.shown > 0:
            return OledText(name, f"{self.spec.unit} {self.shown_range()}")
        row = self.label()
        if edge:
            row = row + EDGE if len(row + EDGE) <= OLED_WIDTH else self.label(short=True) + EDGE
        return OledText(name, row)

    def flash_step(self, name: str) -> OledText | None:
        """The brief message after Tempo when row 2 shows the range: 'Step: Page'."""
        return OledText(name, f"Step: {self.kind.label}") if self.spec.unit else None

    def flash_edge(self, name: str) -> OledText | None:
        """The brief message for a refused step when row 2 shows the range: 'Neck end'."""
        return OledText(name, self.spec.end_text) if self.spec.unit else None

    def to_json(self) -> dict:
        return {"interval": self.kind.label, "offset": self.position, "counts": {},
                "transposition": self.transposition(),
                "window": {**self.spec.to_json(), "step": self.kind.label, "position": self.position,
                           "label": self.label()}}


def window_for(spec: WindowSpec | None) -> "LabWindow | StepWindow":
    """A fresh window: the generator's own when it declares one, else Octave / Fifth / Third at 0 (d38)."""
    return StepWindow.starting(spec) if spec is not None else LabWindow()


@dataclass(frozen=True)
class Edge:
    """A refused step: the window it stays at and the steps that were asked for."""
    window: "LabWindow | StepWindow"
    steps: int

    def oled(self, name: str) -> OledText:
        return self.window.oled(name, edge=True)

    def flash(self, name: str) -> OledText | None:
        return self.window.flash_edge(name)
