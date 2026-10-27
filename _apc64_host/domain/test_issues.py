from _apc64_host.domain.issues import DomainInvariantError, LayoutIssue, Severity, SourceRef, in_line_order


def test_an_issue_renders_file_line_control_problem_and_fix():
    issue = LayoutIssue(Severity.ERROR, SourceRef("jam.yaml", 12), "pads r1c1-r1c8",
                        "expected ':' after the control name", 'write "pads r1c1-r1c8: notes 36"')
    assert issue.message() == ('jam.yaml line 12, pads r1c1-r1c8: expected \':\' after the control name; '
                               'write "pads r1c1-r1c8: notes 36"')
    assert issue.is_error


def test_an_issue_without_a_control_names_only_the_line_and_the_joiner_is_display_only():
    issue = LayoutIssue(Severity.WARNING, SourceRef("jam.yaml", 3), None, "no such pad", "pads are r1c1–r8c8",
                        joiner=", ")
    assert str(issue) == "jam.yaml line 3: no such pad, pads are r1c1–r8c8"
    assert issue == LayoutIssue(Severity.WARNING, SourceRef("jam.yaml", 3), None, "no such pad",
                                "pads are r1c1–r8c8")
    assert not issue.is_error


def test_issues_sort_into_line_order():
    late = LayoutIssue(Severity.ERROR, SourceRef("jam.yaml", 14), None, "b")
    early = LayoutIssue(Severity.ERROR, SourceRef("jam.yaml", 8), None, "a")
    assert in_line_order([late, early]) == [early, late]


def test_the_invariant_error_names_field_problem_and_fix():
    error = DomainInvariantError("channel", "channel must be 1–16", "write 1 to 16")
    assert (error.field, error.problem, error.fix) == ("channel", "channel must be 1–16", "write 1 to 16")
    assert str(error) == "channel: channel must be 1–16; write 1 to 16"


def test_a_control_already_named_by_the_problem_is_not_repeated():
    issue = LayoutIssue(Severity.ERROR, SourceRef("apc.yaml", 3), "device apc", "device apc targets an APC64 port",
                        "the host never sends to the APC64's own ports, choose another port")
    assert issue.message() == ("apc.yaml line 3: device apc targets an APC64 port; "
                               "the host never sends to the APC64's own ports, choose another port")
