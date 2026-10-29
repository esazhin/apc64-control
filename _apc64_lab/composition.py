"""The lab's composition root (contract §7.1, T39; s32 supplier, s33): the only lab file that constructs adapters.

build_lab builds the whole lab by constructor injection, in the order the simulator scenarios use (the `Lab`
graph of infrastructure/test_session_on_simulator.py), with the real file stores:

    HostLink → UnitMemoryAdapter → BackupFiles, LibraryFiles, SettingsFile → GuardedWriter (the one capability)
    → GeneratorRegistry over PluginDiscovery, loaded once (its refusals logged, A20) → DefinitionIndex
    → PatternFiles → PatternLibrary → LabSectionCompiler → HubPublisher → HarmonyTracker → PerformerService
    (ThreadTimer) → SessionService → ProjectMemory, GlobalSettingsService → the /api/lab router, the `apc64 lab`
    commands and the panel → LabModule (check_scoped_writes)

The host's ports (gate, SysEx tap, engine, tweaks, play stream, hub, clock, MIDI inputs) are built after the lab,
because the gate's policy needs the lab's scoped writes first; they reach the lab through LabModule.bind, which
fills the HostLink and binds the publisher to the hub. The one WriteCapability is made by the service's
composition root (_apc64_host/__main__.py) and handed only to GuardedWriter.

The host composition also calls name_layouts with its layout library's names (so push and preview by display name
work for a layout never loaded), start() on the event loop (the harmony tracker reads the play stream there) and
stop() after the unit's release (the slot-0 writer thread ends). The performer (§2.10) reads its patterns from
patterns/ (APC64_LAB_PATTERNS_DIR), plays on a ThreadTimer started with the lab and flashes on the OLED through
the session; its control pads (chord types, pattern slots) are painted into slot 0 by the session's render and
rewritten (repaint) when a selection changes; the voicing it plays is shown by the harmony tracker.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from _apc64_host.domain.issues import in_line_order
from _apc64_host.notation.compiler import compile_text

from .application.global_settings import GlobalSettingsService
from .application.guarded_writer import GuardedWriter
from .application.harmony_tracker import HarmonyTracker
from .application.module import LabModule, check_scoped_writes
from .application.pattern_library import PatternLibrary, users_of
from .application.performer_service import PerformerService
from .application.ports import READ_TIMEOUT, HostLink
from .application.project_memory import ProjectMemory
from .application.registry import DefinitionIndex, GeneratorRegistry
from .application.section_compiler import LabSectionCompiler
from .application.session_service import SessionService
from .domain.lab_section import SECTION
from .domain.note_target import NoteTarget
from .infrastructure.backup_files import BackupFiles
from .infrastructure.library_files import LibraryFiles
from .infrastructure.pattern_files import PatternFiles
from .infrastructure.performer_timer import ThreadTimer
from .infrastructure.plugin_discovery import PluginDiscovery
from .infrastructure.settings_file import SettingsFile
from .infrastructure.unit_memory import UnitMemoryAdapter
from .presentation.api import LabServices, issue_json, lab_router
from .presentation.cli import LabCli
from .presentation.publisher import HubPublisher

log = logging.getLogger("apc64-lab")
STATIC_DIR = Path(__file__).resolve().parent / "presentation" / "static"
SETTINGS_FILE = "lab-settings.json"
PATTERNS_DIR = Path(__file__).resolve().parents[1] / "patterns"   # the repository's (APC64_LAB_PATTERNS_DIR)


@dataclass(frozen=True)
class LabPaths:
    """Where the lab keeps its files: backups (git-ignored, dated), the library (§3.2; the user's own projects,
    git-ignored in this repository), the remembered settings (the harmony inputs), the performer's patterns
    (tracked; §2.10) and every pattern text the editor replaced or deleted (default: pattern-versions beside the
    settings, outside the repository)."""
    backups: Path
    library: Path
    settings: Path
    patterns: Path = PATTERNS_DIR
    pattern_versions: Path | None = None

    @classmethod
    def under(cls, backups, library, state_dir, patterns=PATTERNS_DIR) -> "LabPaths":
        return cls(Path(backups), Path(library), Path(state_dir) / SETTINGS_FILE, Path(patterns))


@dataclass
class Lab:
    """The composed lab: its HostModule plus every service and adapter (for the host's wiring and the tests)."""
    module: LabModule
    link: HostLink
    memory: UnitMemoryAdapter
    backups: BackupFiles
    library: LibraryFiles
    settings: SettingsFile
    writer: GuardedWriter
    registry: GeneratorRegistry
    index: DefinitionIndex
    compiler: LabSectionCompiler
    publisher: HubPublisher
    tracker: HarmonyTracker
    session: SessionService
    projects: ProjectMemory
    globals: GlobalSettingsService
    services: LabServices
    router: Any
    cli: LabCli
    patterns: PatternLibrary | None = None
    performer: PerformerService | None = None
    target: NoteTarget | None = None
    _task: Any = field(default=None, repr=False)

    def name_layouts(self, summaries) -> None:
        """The host library's ids and display names (LayoutSummary rows, or (id, name) pairs); a generated
        layout whose file is gone is forgotten. The panel's list follows at once (the lab state is published)."""
        present, rejected = set(), set()
        for row in summaries:
            layout_id, name = (row.id, row.name) if hasattr(row, "id") else row
            if getattr(row, "deleted", False):
                continue
            present.add(str(layout_id))
            if getattr(row, "valid", True) is False:
                rejected.add(str(layout_id))
            self.index.named(layout_id, name)
        self.index.rejected(rejected)
        for layout_id in [e.layout_id for e in self.index.all()] + [i for i, _, _ in self.index.invalid() if i not in present]:
            if layout_id not in present:
                self.index.forget(layout_id)
        self.session.publish()

    def start(self) -> None:
        """On the event loop, at service start: the harmony tracker follows the play stream (s19.c1)."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self.tracker.run(), name="lab harmony tracker")
        if self.performer is not None:
            self.performer.start()

    def stop(self) -> None:
        """After the unit's release: the tracker stops and the slot-0 writer thread ends."""
        self.tracker.stop()
        if self.performer is not None:
            self.performer.stop()
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.session.close()


def _validator(compiler: LabSectionCompiler, link: HostLink) -> Callable[[str, str], Any]:
    """POST /api/lab/validate: the whole layout compiled with the lab section, ports checked against the host's
    catalog when it is bound (the same check as POST /api/validate)."""
    def validate(text: str, file: str):
        catalog = link.inputs
        ports = None
        if catalog is not None and hasattr(catalog, "list"):
            try:
                ports = [p.name for p in catalog.list()]
            except Exception:   # a catalog that cannot list: structure only
                ports = None
        return compile_text(text, file, ports, sections={SECTION: compiler})
    return validate


def build_lab(paths: LabPaths, capability, *, target: NoteTarget | None = None, source=None,
              threaded: bool = True, read_timeout: float = READ_TIMEOUT,
              wall: Callable[[], datetime] = datetime.now, timer=None) -> Lab:
    """The lab composed (s32.c2): a LabModule ready for collect(), or a start-up error naming the broken piece."""
    link = HostLink()
    memory = UnitMemoryAdapter(link, timeout=read_timeout)
    backups, library, settings = BackupFiles(paths.backups), LibraryFiles(paths.library), SettingsFile(paths.settings)
    writer = GuardedWriter(memory, backups, capability, link, wall)
    registry = GeneratorRegistry(source if source is not None else PluginDiscovery()).load()
    for refusal in registry.refusals:                                                      # A20
        log.warning("lab: start-up: %s", refusal)
    for listed in registry.listed():
        if listed.broken:
            log.warning("lab: %s %s is broken (%s): %s", listed.kind, listed.name, listed.file, listed.error)
    index = DefinitionIndex()
    versions = paths.pattern_versions or Path(paths.settings).parent / "pattern-versions"
    patterns = PatternLibrary(PatternFiles(paths.patterns, versions))
    patterns.users = lambda pattern_id: users_of(pattern_id, index.all(), patterns.names())
    compiler = LabSectionCompiler(registry.generators, registry.schemes, target, index.record, index.failed,
                                  patterns=patterns.names)
    publisher = HubPublisher()
    tracker = HarmonyTracker(publisher, settings, link)
    sessions: list[SessionService] = []
    performer = PerformerService(patterns, link, publisher, timer if timer is not None else
                                 (ThreadTimer() if threaded else None), registry.generators,
                                 flash=lambda text: sessions[0].flash(text) if sessions else None,
                                 repaint=lambda: sessions[0].repaint() if sessions else None,
                                 window=lambda layout_id: sessions[0].transposition_of(layout_id) if sessions else None,
                                 show=tracker.show_voicing)
    session = SessionService(writer, backups, registry, link, publisher, control=memory,
                             held_notes=tracker.held_notes, index=index, target=target, wall=wall, threaded=threaded,
                             on_key=tracker.set_key, on_end_notes=performer.end_held, controls=performer.control_pads,
                             on_scale=performer.set_key)
    sessions.append(session)
    projects = ProjectMemory(writer, backups, library, registry, index, session, wall)
    global_settings = GlobalSettingsService(writer)
    # validation of a text sent to the API compiles without the index hooks: a draft never changes the list
    services = LabServices(session, projects, global_settings, tracker,
                           _validator(LabSectionCompiler(registry.generators, registry.schemes, target,
                                                         patterns=patterns.names), link),
                           performer=performer, patterns=patterns)
    router = lab_router(services)
    cli = LabCli(offline_validation, offline_pattern)

    def bound(host) -> None:
        publisher.bind(host.topics)
        session.publish()
        publisher.publish(tracker.state())
        tracker.publish_inputs()
        performer.publish()

    module = LabModule(link, writer, session, compiler, tracker, router=router, panel=str(STATIC_DIR),
                       cli_commands=(cli,), on_bind=(bound,), performer=performer)
    check_scoped_writes(module)
    log.info("lab: generators %s; colour schemes %s; default note target %s",
             ", ".join(registry.generators()) or "none", ", ".join(registry.schemes()) or "none",
             target.text() if target else "none (notes are only shown unless a layout routes them)")
    return Lab(module, link, memory, backups, library, settings, writer, registry, index, compiler, publisher,
               tracker, session, projects, global_settings, services, router, cli, patterns, performer, target)


def lab_cli() -> LabCli:
    """The `apc64 lab` commands for the host's CLI (no service is composed: the CLI talks to the API)."""
    return LabCli(offline_validation, offline_pattern)


def offline_pattern(text: str, file: str) -> dict:
    """The `apc64 lab validate-pattern` fallback when the service is not running: the pattern compiled here."""
    from .presentation.api import pattern_validation
    return {**pattern_validation(PatternLibrary(PatternFiles(PATTERNS_DIR)).compile_text(text, file)), "offline": True}


def offline_validation(text: str, file: str) -> dict:
    """The `apc64 lab validate` fallback when the service is not running: the layout compiled here with the
    built-in and plugin generators, structure only (no port catalog)."""
    registry = GeneratorRegistry(PluginDiscovery()).load()
    compiler = LabSectionCompiler(registry.generators, registry.schemes,
                                  patterns=PatternLibrary(PatternFiles(PATTERNS_DIR)).names)
    result = compile_text(text, file, None, sections={SECTION: compiler})
    errors = [i for i in in_line_order(result.issues) if i.is_error]
    return {"valid": result.valid and not errors, "summary": result.summary(),
            "issues": [issue_json(i) for i in errors], "warnings": [issue_json(i) for i in result.warnings],
            "offline": True}
