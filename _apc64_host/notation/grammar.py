"""The one grammar of the layout format (contract §7.1): keys, control-name forms, binding phrases and value
forms. The compiler parses with it, splice writes with it and schema.py documents it, so they cannot drift.

A binding is a short phrase (or a mapping with the same words as keys):

    note 36                         cc 20 value 64            program 5          none (unbind)
    notes from 36                   cc 20-27                  pitchbend          (strips)
    note C1 on mpc ch 10            cc14 20  (MSB 20, LSB 52)  cc 20 + program 5  (several messages, in order)

followed by options:

    toggle | toggle 100/0 | momentary          colour red | colour 45          velocity 100
    label "Kick drum"                           feedback | feedback cc 20 from bitwig ch 1 [off dimwhite]
    touch note 60 (strips)                      bar | bipolar (strips)         [colours 0:off 127:green]
"""
import re
from dataclasses import dataclass, field

from ..domain.layout import MessageKind

TOP_KEYS = ("name", "device", "devices", "pages", "banks", "routing")
DEVICE_KEYS = ("port", "ch", "channel")
PAGE_KEYS = ("name", "shift")
ROUTING_KEYS = ("notes", "custom")
BINDING_KEYS = ("send", "label", "colour", "color", "mode", "toggle", "velocity", "feedback", "off", "touch",
                "bar", "style")
ROUTING_FIELDS = ("device", "to", "on", "ch", "channel", "aftertouch", "transpose", "remap")
AFTERTOUCH_WORDS = {"pass": "pass", "pressure": "pressure", "channel-pressure": "pressure", "drop": "drop"}

MESSAGE_WORDS = {
    "note": MessageKind.NOTE, "notes": MessageKind.NOTE,
    "cc": MessageKind.CC, "ccs": MessageKind.CC,
    "cc14": MessageKind.CC14,
    "program": MessageKind.PROGRAM, "prog": MessageKind.PROGRAM, "pc": MessageKind.PROGRAM,
    "pitchbend": MessageKind.PITCHBEND, "bend": MessageKind.PITCHBEND, "pb": MessageKind.PITCHBEND,
}
CANONICAL_WORD = {MessageKind.NOTE: "note", MessageKind.CC: "cc", MessageKind.CC14: "cc14",
                  MessageKind.PROGRAM: "program", MessageKind.PITCHBEND: "pitchbend"}
OPTION_WORDS = ("toggle", "momentary", "colour", "color", "velocity", "vel", "label", "feedback", "off", "touch",
                "bar", "bipolar", "colours", "colors")
TARGET_WORDS = ("on", "ch", "channel", "value", "from")

# Control-name forms, as regular expressions over normalised (lower-case, single-spaced) names
NAMED_BUTTONS = ("tempo", "clear", "duplicate", "quantize", "fixed", "undo", "play", "rec", "stop", "down", "up",
                 "left", "right", "recarm", "mute", "solo", "clipstop", "encoder press", "encoder")
CONTROL_FORMS = {
    "pad": r"pads? r[1-8]c[1-8](-r[1-8]c[1-8])?",
    "numbered": r"(tracks?|trackctls?|strips?) [1-8](-[1-8])?",
    "named": "(" + "|".join(re.escape(n) for n in NAMED_BUTTONS) + ")",
}
CONTROL_KEY = re.compile(r"^(" + "|".join(CONTROL_FORMS.values()) + r")$")
# The start of a line that names a control but has no ':' after it (contract A38)
_LOOSE_CONTROL = re.compile(
    r"^(?P<control>(pads?\s+r\d+c\d+(\s*-\s*r\d+c\d+)?|(tracks?|trackctls?|strips?|scenes?|stripmodes?)\s+\d+"
    r"(\s*-\s*\d+)?|" + "|".join(re.escape(n) for n in NAMED_BUTTONS) + r"))\s+(?P<rest>[^:#\s].*)$",
    re.IGNORECASE)
PAGE_KEY = re.compile(r"^(page\s+)?(?P<n>-?\d+)(\s+(?P<name>.+))?$", re.IGNORECASE)
BANK_KEY = re.compile(r"^(bank\s+)?(?P<n>-?\d+)(\s+(?P<name>.+))?$", re.IGNORECASE)


class PhraseError(ValueError):
    """A phrase that does not parse: problem and fix, like every layout issue."""

    def __init__(self, problem: str, fix: str):
        self.problem, self.fix = problem, fix
        super().__init__(f"{problem}; {fix}")


@dataclass
class MessageSpec:
    """One message as written: a number, a range ('20-27') or 'from N', before devices are resolved."""
    kind: MessageKind
    first: str | None = None      # the number or note name as written
    last: str | None = None       # end of an explicit range
    ascending: bool = False       # 'from N': N, N+1, … across a range of controls
    value: int | None = None      # 'cc 20 value 64'
    lsb: int | None = None        # 'cc14 20/52'
    device: str | None = None
    channel: int | None = None

    @property
    def is_range(self) -> bool:
        return self.ascending or self.last is not None


@dataclass
class FeedbackSpec:
    kind: MessageKind | None = None   # None: echo the binding's own first message
    number: str | None = None
    device: str | None = None
    channel: int | None = None
    colours: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class BindingSpec:
    messages: list[MessageSpec] = field(default_factory=list)
    toggle: bool | None = None       # None: not said (momentary when compiled)
    toggle_values: tuple[int, int] | None = None
    colour: str | None = None
    label: str | None = None
    velocity: int | None = None
    feedback: FeedbackSpec | None = None
    off_colour: str | None = None
    touch: MessageSpec | None = None
    style: str | None = None
    none: bool = False               # 'none': explicitly unbound (overrides a range on one control)


# --- tokens ----------------------------------------------------------------------------------------------
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'|\S+')
_SPACED_DASH = re.compile(r"(?<=[0-9A-Za-z#])\s+-\s+(?=[0-9A-Ga-g])")


def tokens(text: str) -> list[str]:
    """Words of a phrase; quoted text stays one token; spaced ranges close up ('36 - 51' → '36-51').
    '+' between messages must stand alone ('cc 20 + program 5'); '+12' stays a signed number."""
    text = _SPACED_DASH.sub("-", str(text).replace("–", "-").replace("—", "-"))
    return _TOKEN.findall(text)


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1].replace('\\"', '"')
    return token


def _int(token: str | None, what: str, fix: str) -> int:
    if token is None or not re.fullmatch(r"[+-]?\d+", token):
        raise PhraseError(f"expected {what}" + (f", found '{token}'" if token else ""), fix)
    return int(token)


class _Reader:
    def __init__(self, words: list[str]):
        self.words, self.i = words, 0

    def peek(self, ahead: int = 0) -> str | None:
        j = self.i + ahead
        return self.words[j].lower() if j < len(self.words) else None

    def raw(self) -> str | None:
        return self.words[self.i] if self.i < len(self.words) else None

    def take(self) -> str | None:
        word = self.raw()
        self.i += 1
        return word

    def done(self) -> bool:
        return self.i >= len(self.words)


def _message(reader: _Reader, allow_range: bool = True) -> MessageSpec:
    word = reader.peek()
    kind = MESSAGE_WORDS.get(word)
    if kind is None:
        raise PhraseError(f"'{reader.raw()}' is not a message",
                          "start with note, notes, cc, cc14, program or pitchbend")
    reader.take()
    spec = MessageSpec(kind)
    if kind is MessageKind.PITCHBEND:
        return _target(reader, spec)
    if reader.peek() == "from":
        reader.take()
        spec.first, spec.ascending = reader.take(), True
        if spec.first is None:
            raise PhraseError(f"'{word} from' needs a starting number", f"write e.g. '{word} from 36'")
    else:
        first = reader.take()
        if first is None:
            raise PhraseError(f"'{word}' needs a number", f"write e.g. '{CANONICAL_WORD[kind]} 36'")
        if kind is MessageKind.CC14 and "/" in first:
            msb, _, lsb = first.partition("/")
            spec.first, spec.lsb = msb, _int(lsb, "an LSB controller number", "write e.g. 'cc14 20/52'")
        else:
            spec.first, spec.last = _split_range(first)
    if spec.is_range and not allow_range:
        raise PhraseError(f"'{word}' here takes one number", "write a single number")
    return _target(reader, spec)


_VALUE = re.compile(r"\d+|[A-Ga-g][#b]?-?\d+")


def _split_range(token: str) -> tuple[str, str | None]:
    """'36-51' → ('36', '51'); 'C-1-D0' → ('C-1', 'D0'); a single value → (value, None)."""
    for match in re.finditer("-", token):
        left, right = token[:match.start()], token[match.end():]
        if _VALUE.fullmatch(left) and _VALUE.fullmatch(right):
            return left, right
    return token, None


def _target(reader: _Reader, spec: MessageSpec) -> MessageSpec:
    """'on <device>', 'ch <n>' and 'value <v>' after a message, in any order."""
    while True:
        word = reader.peek()
        if word == "on" and reader.peek(1) is not None and reader.peek(1) not in OPTION_WORDS:
            reader.take()
            spec.device = reader.take().lower()
        elif word in ("ch", "channel"):
            reader.take()
            spec.channel = _int(reader.take(), "a channel 1–16", "write e.g. 'ch 10'")
        elif word == "value" and spec.kind in (MessageKind.CC, MessageKind.PITCHBEND):
            reader.take()
            spec.value = _int(reader.take(), "a value", "write e.g. 'value 64'")
        else:
            return spec


def parse_phrase(text: str) -> BindingSpec:
    """A binding phrase → BindingSpec; raises PhraseError naming the problem and the fix."""
    reader = _Reader(tokens(text))
    if reader.done():
        raise PhraseError("the binding is empty", "write e.g. 'note 36' or 'cc 20'")
    if reader.peek() == "none":
        if len(reader.words) > 1:
            raise PhraseError("'none' stands alone", "write just 'none' to leave the control unbound")
        return BindingSpec(none=True)
    spec = BindingSpec([_message(reader)])
    while not reader.done():
        word = reader.peek()
        if word == "+":
            reader.take()
            spec.messages.append(_message(reader))
        elif word in OPTION_WORDS:
            _option(reader, spec)
        elif word in MESSAGE_WORDS:
            raise PhraseError(f"a second message '{reader.raw()}' needs '+' before it",
                              f"write '… + {reader.raw()} …' to send both")
        else:
            raise PhraseError(f"unexpected '{reader.raw()}'",
                              "after the message come options: toggle, colour <c>, velocity <v>, label \"…\", "
                              "feedback, touch …, bar, bipolar")
    return spec


def parse_options(text: str, spec: BindingSpec) -> BindingSpec:
    """Options alone ('toggle colour red label "Kick"'), applied onto spec: the mapping form's keys."""
    reader = _Reader(tokens(text))
    while not reader.done():
        if reader.peek() not in OPTION_WORDS:
            raise PhraseError(f"unexpected '{reader.raw()}'", "use toggle, colour, velocity, label, feedback, off, "
                                                              "touch, bar or bipolar")
        _option(reader, spec)
    return spec


def _option(reader: _Reader, spec: BindingSpec):
    word = reader.take().lower()
    if word == "toggle":
        spec.toggle = True
        if reader.raw() and re.fullmatch(r"\d+/\d+", reader.raw()):
            on, off = reader.take().split("/")
            spec.toggle_values = (int(on), int(off))
    elif word == "momentary":
        spec.toggle = False
    elif word in ("colour", "color"):
        spec.colour = _required(reader, word, "a colour name or index", "colour red")
    elif word in ("velocity", "vel"):
        spec.velocity = _int(reader.take(), "a velocity 1–127", "write e.g. 'velocity 100'")
    elif word == "label":
        text = _required(reader, word, "the label text", 'label "Kick"')
        if text[0] in "\"'" and (len(text) < 2 or text[-1] != text[0]):
            raise PhraseError("the label's quotes are not closed",
                              "close them; if the label holds ' #' or ': ', put the whole binding in single "
                              "quotes, e.g. pad r1c1: 'note 36 label \"Kick #1\"'")
        spec.label = _unquote(text)
    elif word == "off":
        spec.off_colour = _required(reader, word, "the off colour", "off dimwhite")
    elif word in ("bar", "bipolar"):
        spec.style = word
    elif word == "touch":
        spec.touch = _message(reader)
    elif word == "feedback":
        spec.feedback = _feedback(reader)
    elif word in ("colours", "colors"):
        spec.feedback = spec.feedback or FeedbackSpec()
        spec.feedback.colours += _colours(reader)


def _required(reader: _Reader, word: str, what: str, example: str) -> str:
    token = reader.take()
    if token is None:
        raise PhraseError(f"'{word}' needs {what}", f"write e.g. '{example}'")
    return token


def _feedback(reader: _Reader) -> FeedbackSpec:
    spec = FeedbackSpec()
    if reader.peek() in ("note", "cc"):
        spec.kind = MESSAGE_WORDS[reader.take().lower()]
        spec.number = _required(reader, "feedback", "a number", "feedback cc 20")
    while reader.peek() in ("from", "ch", "channel", "colours", "colors"):
        word = reader.take().lower()
        if word == "from":
            spec.device = _required(reader, "from", "a device name", "feedback cc 20 from bitwig").lower()
        elif word in ("ch", "channel"):
            spec.channel = _int(reader.take(), "a channel 1–16", "write e.g. 'ch 1'")
        else:
            spec.colours += _colours(reader)
    return spec


def _colours(reader: _Reader) -> list[tuple[int, str]]:
    pairs = []
    while reader.raw() and re.fullmatch(r"\d+:\S+", reader.raw()):
        value, _, colour = reader.take().partition(":")
        pairs.append((int(value), colour))
    if not pairs:
        raise PhraseError("'colours' needs value:colour pairs", "write e.g. 'colours 0:off 64:yellow 127:green'")
    return pairs


# --- routing phrases -------------------------------------------------------------------------------------
@dataclass
class RoutingSpec:
    device: str | None = None
    channel: int | None = None
    aftertouch: str = "pass"
    transpose: int = 0
    remap: list[tuple[str, str]] = field(default_factory=list)


def parse_routing(text: str) -> RoutingSpec:
    """'mpc ch 2 aftertouch pressure transpose 12 remap 36>38 37>40'."""
    reader = _Reader(tokens(text))
    spec = RoutingSpec()
    if reader.peek() in ("to", "on"):
        reader.take()
    first = reader.peek()
    if first is None or first in ("ch", "channel", "aftertouch", "transpose", "remap"):
        raise PhraseError("routing needs a target device first", "write e.g. 'notes: mpc ch 2'")
    spec.device = reader.take().lower()
    while not reader.done():
        word = reader.take().lower()
        if word in ("ch", "channel"):
            spec.channel = _int(reader.take(), "a channel 1–16", "write e.g. 'ch 2'")
        elif word == "aftertouch":
            choice = (reader.take() or "").lower()
            if choice not in AFTERTOUCH_WORDS:
                raise PhraseError(f"aftertouch '{choice}' is not a choice", "write aftertouch pass, pressure or drop")
            spec.aftertouch = AFTERTOUCH_WORDS[choice]
        elif word == "transpose":
            spec.transpose = _int(reader.take(), "semitones", "write e.g. 'transpose 12' or 'transpose -12'")
        elif word == "remap":
            while reader.raw() and ">" in reader.raw():
                a, _, b = reader.take().partition(">")
                spec.remap.append((a, b))
            if not spec.remap:
                raise PhraseError("remap needs pairs", "write e.g. 'remap 36>38 37>40'")
        else:
            raise PhraseError(f"unexpected '{word}' in routing",
                              "write '<device> ch <n> aftertouch pass|pressure|drop transpose <n> remap <a>><b>'")
    return spec


# --- rendering (the inverse of parse_phrase, used by tweaks) --------------------------------------------
def render_message(spec: MessageSpec) -> str:
    word = "notes" if spec.kind is MessageKind.NOTE and spec.is_range else CANONICAL_WORD[spec.kind]
    parts = [word]
    if spec.kind is not MessageKind.PITCHBEND:
        number = f"from {spec.first}" if spec.ascending else (
            f"{spec.first}-{spec.last}" if spec.last is not None else str(spec.first))
        if spec.kind is MessageKind.CC14 and spec.lsb is not None:
            number = f"{spec.first}/{spec.lsb}"
        parts.append(number)
    if spec.value is not None:
        parts.append(f"value {spec.value}")
    if spec.device:
        parts.append(f"on {spec.device}")
    if spec.channel is not None:
        parts.append(f"ch {spec.channel}")
    return " ".join(parts)


def _quote_label(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


def render_phrase(spec: BindingSpec) -> str:
    """BindingSpec → the canonical one-line phrase; parse_phrase(render_phrase(s)) gives s back."""
    if spec.none:
        return "none"
    parts = [" + ".join(render_message(m) for m in spec.messages)]
    if spec.touch is not None:
        parts.append("touch " + render_message(spec.touch))
    if spec.toggle:
        parts.append("toggle" + (f" {spec.toggle_values[0]}/{spec.toggle_values[1]}" if spec.toggle_values else ""))
    if spec.velocity is not None:
        parts.append(f"velocity {spec.velocity}")
    if spec.style:
        parts.append(spec.style)
    if spec.colour is not None:
        parts.append(f"colour {spec.colour}")
    if spec.label is not None:
        parts.append(f"label {_quote_label(spec.label)}")
    if spec.feedback is not None:
        fb = spec.feedback
        text = "feedback"
        if fb.kind is not None:
            text += f" {CANONICAL_WORD[fb.kind]} {fb.number}"
        if fb.device:
            text += f" from {fb.device}"
        if fb.channel is not None:
            text += f" ch {fb.channel}"
        if fb.colours:
            text += " colours " + " ".join(f"{v}:{c}" for v, c in fb.colours)
        parts.append(text)
    if spec.off_colour is not None:
        parts.append(f"off {spec.off_colour}")
    return " ".join(parts)


def yaml_scalar(text: str) -> str:
    """A phrase as a YAML plain scalar where that is safe, otherwise single-quoted."""
    risky = (": " in text or " #" in text or text.endswith(":") or text[:1] in "!&*?|>'\"%@`{[,-#"
             or text != text.strip())
    return "'" + text.replace("'", "''") + "'" if risky else text


def normalise_key(key) -> str:
    return " ".join(str(key).lower().replace("–", "-").split())


def loose_control_line(line: str) -> tuple[str, str] | None:
    """(control, rest) when a line names a control but lacks the ':' after it, e.g. 'pads r1c1-r1c8 notes 36'."""
    content = line.split(" #", 1)[0].strip()
    if not content or content.startswith(("#", "-")):
        return None
    match = _LOOSE_CONTROL.match(content)
    if not match or ":" in match.group("control"):
        return None
    rest = match.group("rest")
    if rest.startswith(":") or content.endswith(":") or ": " in content:
        return None
    return match.group("control"), rest.strip()
