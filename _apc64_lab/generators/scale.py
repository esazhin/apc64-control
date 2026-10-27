"""'scale': a scale overlay for any generated layout. The scale's root is white (pressed red), its other notes
keep the fifths hue, and every note outside it is dim but lit, so the layout's geometry stays readable.

    scheme: scale
    scale: dorian        # a key of the harmony core's scale library (apc64 lab list shows them); default major
    root: D              # optional, a note name without octave; default the layout's root (its base's)
"""
from _apc64_lab.domain.generators import ParamKind, ParamSpec, ScaleOverlay, fifths_hue
from _apc64_lab.domain.harmony.scales import BY_KEY, SCALE_KEYS, find_scale, spell_scale
from _apc64_lab.domain.pads import RED, WHITE, Rgb

OUT_OF_SCALE = Rgb(24, 28, 40)


def _lookup(text):
    found = find_scale(text)
    return found.key if found else None


class _Overlay:
    """The scheme bound to a scale and an optional root (None: the layout's root)."""
    name = "scale"

    def __init__(self, scale: str, root: int | None):
        self.scale, self.root = BY_KEY[scale], root

    def _root(self, layout_root: int) -> int:
        return layout_root if self.root is None else self.root

    def colour(self, note, root):
        root = self._root(root)
        pc = note % 12
        if pc == root:
            return WHITE, RED
        if pc in self.scale.pitch_classes(root):
            return fifths_hue(pc * 7 % 12), WHITE
        return OUT_OF_SCALE, WHITE

    def overlay(self, root):
        root = self._root(root)
        return ScaleOverlay(self.scale.key, self.scale.name, root, self.scale.pitch_classes(root),
                            tuple(spell_scale(root, self.scale).items()))


class ScaleScheme(_Overlay):
    params = (ParamSpec("scale", ParamKind.CHOICE, "major", doc="the scale lit (the harmony core's library)",
                        choices=SCALE_KEYS, lookup=_lookup),
              ParamSpec("root", ParamKind.PITCH_CLASS, None, 0, 11,
                        "the scale's root, a note name without octave (default: the layout's root)"))

    def __init__(self):
        super().__init__("major", None)

    def configured(self, values):
        return _Overlay(values.get("scale", "major"), values.get("root"))


SCHEME = ScaleScheme()
