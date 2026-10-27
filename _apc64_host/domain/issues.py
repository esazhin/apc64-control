"""Where a layout is wrong, what is wrong and how to fix it (contract d112): issues and the domain's invariant error."""
from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True, order=True)
class SourceRef:
    file: str
    line: int   # 1-based, as an editor shows it

    def __str__(self) -> str:
        return f"{self.file} line {self.line}"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class LayoutIssue:
    """One finding. Rendered uniformly as '<file> line <n>[, <control>]: <problem><joiner><fix>'; the control is
    left out of the text when the problem already names it ('device apc targets an APC64 port')."""
    severity: Severity
    source: SourceRef
    control: str | None
    problem: str
    fix: str | None = None
    joiner: str = field(default="; ", compare=False)

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR

    def message(self) -> str:
        named = self.control and self.control not in self.problem
        where = str(self.source) + (f", {self.control}" if named else "")
        return f"{where}: {self.problem}" + (f"{self.joiner}{self.fix}" if self.fix else "")

    def __str__(self) -> str:
        return self.message()


def in_line_order(issues) -> list[LayoutIssue]:
    """All issues of one file in line order (d113); stable for issues on the same line."""
    return sorted(issues, key=lambda issue: (issue.source.file, issue.source.line))


class DomainInvariantError(ValueError):
    """A value or aggregate rule was broken; names the field, the problem and the fix."""

    def __init__(self, field: str, problem: str, fix: str, joiner: str = "; "):
        self.field, self.problem, self.fix, self.joiner = field, problem, fix, joiner
        super().__init__(f"{field}: {problem}{joiner}{fix}")
