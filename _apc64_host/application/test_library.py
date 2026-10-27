from _apc64_host.application.library import DuplicateName, LayoutLibrary, Registered
from _apc64_host.domain.conftest import drum_pads, layout, page
from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import LayoutId


def jam(id="jam", name="Jam"):
    return layout(id, name, pages=[page(1, "Drums", base=drum_pads())])


def issue(file, line, problem="unknown device mcp"):
    return LayoutIssue(Severity.ERROR, SourceRef(file, line), None, problem, "declared devices: mpc")


def test_a_second_layout_with_the_same_name_is_refused_naming_the_first():   # A42
    library = LayoutLibrary()
    assert library.register(LayoutId("jam"), jam()) == Registered()
    answer = library.register(LayoutId("jam2"), jam("jam2", "jam"))
    assert answer == DuplicateName(LayoutId("jam"), "jam")
    assert library.compiled(LayoutId("jam")).id == "jam" and library.compiled(LayoutId("jam2")) is None
    assert library.catalog().ids == (LayoutId("jam"),)


def test_the_catalog_and_summaries_list_layouts_alphabetically_by_name():   # s18.c2, d106
    library = LayoutLibrary()
    for id, name in [("tonnetz", "Tonnetz C"), ("jam", "Jam"), ("amb", "Ambient")]:
        library.register(LayoutId(id), jam(id, name))
    library.set_issues(LayoutId("broken"), [issue("broken.yaml", 3)])
    assert [n for _, n in library.catalog().entries] == ["Ambient", "Jam", "Tonnetz C"]
    summaries = library.summaries()
    assert [(s.id, s.name, s.valid, s.pages, s.banks) for s in summaries] == [
        ("amb", "Ambient", True, 1, 0), ("jam", "Jam", True, 1, 0), ("tonnetz", "Tonnetz C", True, 1, 0),
        ("broken", "broken", False, 0, 0)]


def test_invalid_content_keeps_the_last_good_layout_and_shows_its_errors_until_fixed():   # d116, A52 library side
    library, seen = LayoutLibrary(), []
    library.subscribe(lambda: seen.append("changed"))
    library.register(LayoutId("jam"), jam())
    library.set_issues(LayoutId("jam"), [issue("jam.yaml", 5)])
    assert library.compiled(LayoutId("jam")) is not None
    assert [i.message() for i in library.issues(LayoutId("jam"))] == [
        "jam.yaml line 5: unknown device mcp; declared devices: mpc"]
    summary = library.summaries()[0]
    assert summary.valid is False and summary.errors == 1
    library.register(LayoutId("jam"), jam())
    assert library.issues(LayoutId("jam")) == () and library.summaries()[0].valid
    assert len(seen) == 3


def test_a_deleted_file_stays_compiled_from_memory_and_is_marked():   # A56 library side
    library = LayoutLibrary()
    library.register(LayoutId("jam"), jam())
    library.mark_deleted(LayoutId("jam"))
    assert library.compiled(LayoutId("jam")) is not None and library.deleted(LayoutId("jam"))
    assert library.summaries()[0].deleted and library.catalog().ids == ()
    library.register(LayoutId("jam"), jam())
    assert not library.deleted(LayoutId("jam"))


def test_all_issues_come_in_file_and_line_order_with_warnings_kept_apart():
    library = LayoutLibrary()
    library.set_issues(LayoutId("b"), [issue("b.yaml", 9), issue("b.yaml", 2)])
    library.set_issues(LayoutId("a"), [issue("a.yaml", 4)])
    warning = LayoutIssue(Severity.WARNING, SourceRef("jam.yaml", 7), None, "page name longer than 14 characters")
    library.register(LayoutId("jam"), jam(), warnings=[warning])
    assert [(i.source.file, i.source.line) for i in library.all_issues()] == [
        ("a.yaml", 4), ("b.yaml", 2), ("b.yaml", 9)]
    assert library.warnings(LayoutId("jam")) == (warning,)
