from _apc64_host.notation.parser import MapNode, Scalar, SeqNode, parse

JAM = """# Jam
name: Jam
pages:
  1 Drums:
    pads r1c1-r1c8: notes from 36   # bass line
    track 1: [cc 20, program 5]
"""


def test_every_node_carries_its_line():
    parsed = parse(JAM, "jam.yaml")
    assert parsed.issues == ()
    pages = parsed.root.get("pages")
    page = pages.value.entries[0]
    assert (page.key, page.line, page.column) == ("1 Drums", 4, 2)
    entry = page.value.entries[0]
    assert (entry.key, entry.line, entry.value) == ("pads r1c1-r1c8", 5, Scalar("notes from 36", 5))
    assert isinstance(page.value.entries[1].value, SeqNode)
    assert isinstance(parsed.root, MapNode) and not parsed.root.flow


def test_a_missing_colon_is_reported_and_parsing_goes_on():
    parsed = parse(JAM.replace("pads r1c1-r1c8: notes", "pads r1c1-r1c8 notes"), "jam.yaml")
    assert [i.message() for i in parsed.issues] == [
        "jam.yaml line 5, pads r1c1-r1c8: expected ':' after the control name; write \"pads r1c1-r1c8: notes from 36\""]
    assert parsed.root is not None


def test_yaml_syntax_errors_name_the_line_and_a_fix():
    parsed = parse("name: Jam\npages:\n  1 Drums:\n    pad r1c1: note 36\n   pad r1c2: note 37\n", "jam.yaml")
    assert parsed.root is None and len(parsed.issues) == 1
    assert parsed.issues[0].source.line == 5 and parsed.issues[0].problem.startswith("YAML syntax")


def test_duplicate_keys_name_both_lines():
    parsed = parse("name: Jam\npages:\n  1:\n    pad r1c1: note 36\n    pad r1c1: note 37\n", "jam.yaml")
    assert [i.message() for i in parsed.issues] == ["jam.yaml line 5: lines 4 and 5 both say pad r1c1; keep one"]


def test_tabs_and_empty_files_are_reported():
    assert parse("name: Jam\npages:\n\t1: {}\n", "jam.yaml").issues[0].fix == "indent with spaces, not tabs"
    assert parse("# nothing\n", "jam.yaml").issues[0].problem == "the layout is empty"
