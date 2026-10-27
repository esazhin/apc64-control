import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from _apc64_host.application.ports import VersionStore
from _apc64_host.config import REPO, Config
from _apc64_host.domain.layout import ContentHash, LayoutId, VersionId
from _apc64_host.infrastructure.version_store import FileVersionStore

JAM = LayoutId("jam")


def ticking(start=datetime(2026, 10, 23, 10, 42, tzinfo=UTC), step=timedelta(minutes=1)):
    moments = [start]

    def now():
        current = moments[-1]
        moments.append(current + step)
        return current

    return now


def save(store, text, layout=JAM):
    return store.save(layout, text, ContentHash.of(text))


def test_versions_are_kept_per_layout_newest_first_and_read_back_exactly(tmp_path):
    # T16, s59.c2, s84, inv20, d117, d119
    store = FileVersionStore(tmp_path / "state", now=ticking())
    assert isinstance(store, VersionStore)
    texts = ["name: Jam\n", "name: Jam\n# two\n", "name: Jam\r\n# three, CRLF kept\r\n"]
    ids = [save(store, text) for text in texts]
    assert ids[0] == VersionId("20261023T104200.000Z", ContentHash.of(texts[0]))
    assert store.list(JAM) == list(reversed(ids))
    assert [store.read(JAM, version) for version in ids] == texts
    files = sorted(p.relative_to(tmp_path) for p in (tmp_path / "state").rglob("*.yaml"))
    assert [str(f) for f in files] == [f"state/versions/jam/{v.timestamp}-{v.hash}.yaml" for v in ids]
    assert store.list(LayoutId("tonnetz")) == []


def test_read_by_short_id_and_unknown_versions(tmp_path):
    store = FileVersionStore(tmp_path, now=ticking())
    version = save(store, "name: Jam\n")
    short = VersionId(version.timestamp, ContentHash(version.hash[:12]))      # str(VersionId) in the API
    assert store.read(JAM, short) == "name: Jam\n"
    assert store.read(JAM, VersionId("20250101T000000.000Z", version.hash)) is None
    assert store.read(LayoutId("other"), version) is None


def test_saves_in_the_same_millisecond_still_order_newest_first(tmp_path):
    same = datetime(2026, 10, 23, 10, 42, tzinfo=UTC)
    store = FileVersionStore(tmp_path, now=lambda: same)
    first, second = save(store, "a\n"), save(store, "b\n")
    assert second.timestamp > first.timestamp
    assert store.list(JAM) == [second, first]


def test_the_default_state_dir_is_outside_the_repository():
    # A55: version copies never live in the repo (contract a27)
    state = Config.load({}, path=None).state_dir
    assert not state.resolve().is_relative_to(REPO)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_status_shows_only_the_layout_and_never_a_version_copy(tmp_path):
    # A55: several versions of 'Jam' exist; only layouts/jam.yaml can show as changed
    repo, state = tmp_path / "repo", tmp_path / "state"
    (repo / "layouts").mkdir(parents=True)
    (repo / "layouts" / "jam.yaml").write_text("name: Jam\n")

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "jam")
    store = FileVersionStore(state, now=ticking())
    for n in range(3):
        text = f"name: Jam\n# edit {n}\n"
        (repo / "layouts" / "jam.yaml").write_text(text)
        save(store, text)
    assert git("status", "--porcelain").splitlines() == [" M layouts/jam.yaml"]
    assert len(store.list(JAM)) == 3
