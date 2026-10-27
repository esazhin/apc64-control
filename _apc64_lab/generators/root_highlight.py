"""'root-highlight': the layout's root stands out, its major triad is warm, every other note dim."""
from _apc64_lab.domain.pads import RED, WHITE, Rgb


class RootHighlight:
    name = "root-highlight"
    _ROOT, _TRIAD, _OTHER = WHITE, Rgb(255, 140, 0), Rgb(0, 40, 90)

    def colour(self, note, root):
        degree = (note - root) % 12
        if degree == 0:
            return self._ROOT, RED
        if degree in (4, 7):
            return self._TRIAD, WHITE
        return self._OTHER, WHITE


SCHEME = RootHighlight()
