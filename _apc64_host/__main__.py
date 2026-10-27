"""The composition root (contract §7.1, T37): `python -m _apc64_host` serves; `python -m _apc64_host <command>` is
the apc64 CLI.

    python -m _apc64_host                     serve with the real APC64 (ALSA rawmidi), sequencer and notifications
    python -m _apc64_host serve --simulate    serve with the simulated APC64 and in-memory MIDI ports: no ALSA device
                                              is opened and no desktop notification is shown (development)
    python -m _apc64_host state | take | …    the apc64 command (see docs/api.md)

Every adapter and service is built here and handed in by constructor (no module-level singletons). Threaded
adapters call back through `dispatch`, bound to the event loop's call_soon_threadsafe at startup. The engine and
the session share ONE outbound gate, whose policy is CONTRACT1_POLICY plus what registered HostModules add.
Startup: pipeline → engine → session (s7.c2: startup itself sends nothing to the unit).
Shutdown (SIGTERM/SIGINT via uvicorn's lifespan): session.release('stop') once — LEDs and OLED cleared, DAW
mode off, port closed — then the watchers stop; an atexit hook repeats release_now('stop') as a safety net (a7).
uvicorn listens dual-stack on [::]:<port> (a28), behind the network guard.

Contract 2 (T40): MODULES registers the layout lab, and this file is the one host file that names it. A module is
given as a HostModule or as a factory(config, adapters) → a composed part whose `.module` is the HostModule. The
part may also offer name_layouts(summaries), start() (on the loop) and stop() (after the release). compose()
collects the modules before the gate (whose policy needs their scoped writes), hands the collection to the
engine, session, state view, pipeline (module sections) and tweaks, then binds the host ports into the modules.
`compose(config, adapters)` without modules is contract 1's composition, unchanged; main() passes MODULES.
"""
import argparse
import asyncio
import atexit
import contextlib
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Callable

from .application.activity import ActivityLog
from .application.calibration import CalibrationService
from .application.engine import HostEngine
from .application.layout_pipeline import LayoutPipeline
from .application.learn import LearnService
from .application.library import LayoutLibrary
from .application.modules import collect
from .application.outbound_gate import OutboundGate
from .application.play_stream import PlayStream
from .application.ports import HostModule, HostPorts
from .application.session import DeviceSession
from .application.state_view import StateView
from .application.tweaks import TweakService
from .config import REPO, Config, ConfigError
from .domain.issues import DomainInvariantError
from .domain.outbound import CONTRACT1_POLICY, WriteCapability
from .domain.unit_status import ReleaseReason
from .infrastructure.clock import AsyncioClock
from .infrastructure.layout_files import LayoutFiles
from .infrastructure.state_store import FileStateStore
from .infrastructure.version_store import FileVersionStore
from .notation.compiler import compile_text
from .presentation.api import STATIC_DIR, Services, build_app
from .presentation.ws_hub import WebSocketHub

log = logging.getLogger("apc64-host")


# --- contract 2: the layout lab, registered here (the single coupling point, contract 2 §7.1) ----------------
def lab_module(config: Config, adapters: "Adapters"):
    """build_lab with the service's settings and the one WriteCapability (inv2), handed only to the lab."""
    from _apc64_lab.composition import LabPaths, build_lab
    from _apc64_lab.domain.note_target import NoteTarget
    target = None
    if config.lab_target:
        try:
            target = NoteTarget.parse(config.lab_target)
        except DomainInvariantError as error:
            raise ConfigError("APC64_LAB_TARGET", f"{error.problem}; {error.fix}") from None
    if adapters.simulator is not None:       # a simulated unit never mixes its backups with the real unit's
        base = Path(config.state_dir) / "simulated"
        paths = LabPaths(base / "lab-backups", base / "lab-library", base / "lab-settings.json")
    else:
        paths = LabPaths(config.lab_backups_dir or REPO / "backups", config.lab_library_dir or REPO / "library",
                         Path(config.state_dir) / "lab-settings.json")
    return build_lab(paths, WriteCapability("lab guarded writer"), target=target)


def lab_cli_modules() -> tuple:
    """The `apc64 lab` commands for `python -m _apc64_host lab …` (the apc64 script finds them by entry point)."""
    from _apc64_lab.composition import lab_cli
    return (lab_cli(),)


MODULES: tuple = (lab_module,)     # contract 1 registered none; contract 2 registers the layout lab


class LoopDispatch:
    """`dispatch` for threaded adapters: hands each callback to the event loop once it is bound."""

    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def __call__(self, fn, *args) -> None:
        loop = self.loop
        if loop is None:
            fn(*args)
            return
        try:
            loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:     # the loop has closed (shutdown): late callbacks are dropped
            pass


@dataclass
class Adapters:
    """The outside world, by port: the real one, or the simulated one."""
    locator: Any                 # UnitLocator
    holders: Any                 # HolderLookup
    unit_port: Any               # UnitPort
    midi: Any                    # TargetPorts + FeedbackInputs + PortCatalog
    files: Any                   # LayoutSource
    versions: Any                # VersionStore
    store: Any                   # StateStore
    prompt: Any                  # ConsentPrompt
    clock: AsyncioClock
    dispatch: LoopDispatch
    starts: list = field(default_factory=list)    # callables run at startup, in order
    stops: list = field(default_factory=list)     # callables run at shutdown, in order
    simulator: Any = None


def real_adapters(config: Config, dispatch: LoopDispatch | None = None) -> Adapters:
    """ALSA rawmidi for the APC64, the ALSA sequencer for every other port, notify-send for the question."""
    from .infrastructure.alsa_rawmidi import AlsaRawMidi
    from .infrastructure.alsa_seq import AlsaSequencer
    from .infrastructure.notifier import DesktopNotifier
    from .infrastructure.unit_locator import AmidiUnitLocator
    dispatch = dispatch or LoopDispatch()
    seq = AlsaSequencer(config.port_stem, dispatch=dispatch)
    locator = AmidiUnitLocator(config.port_stem, dispatch=dispatch)
    files = LayoutFiles(config.layouts_dir, dispatch=dispatch)
    return Adapters(locator=locator, holders=seq, unit_port=AlsaRawMidi(holders=seq), midi=seq, files=files,
                    versions=FileVersionStore(config.state_dir), store=FileStateStore(config.state_dir),
                    prompt=DesktopNotifier(), clock=AsyncioClock(), dispatch=dispatch,
                    starts=[seq.start, locator.start, files.start], stops=[files.stop, locator.stop, seq.stop])


def simulated_adapters(config: Config, dispatch: LoopDispatch | None = None, simulator=None, ports=None) -> Adapters:
    """The simulated APC64 (fixture formats) and in-memory MIDI ports: nothing touches ALSA or the desktop.
    Layouts are the configured directory; state goes to <state dir>/simulated so a simulated hold never leaves a
    holding marker for the real unit."""
    from .infrastructure.memory_ports import MemoryPorts
    from .infrastructure.notifier import SilentPrompt
    from .infrastructure.simulated_apc64 import SimulatedApc64
    dispatch = dispatch or LoopDispatch()
    sim = simulator or SimulatedApc64()
    files = LayoutFiles(config.layouts_dir, dispatch=dispatch)
    state_dir = Path(config.state_dir) / "simulated"
    return Adapters(locator=sim, holders=sim.holder_lookup, unit_port=sim, midi=ports or MemoryPorts(), files=files,
                    versions=FileVersionStore(state_dir), store=FileStateStore(state_dir), prompt=SilentPrompt(),
                    clock=AsyncioClock(), dispatch=dispatch, starts=[files.start], stops=[files.stop], simulator=sim)


@dataclass
class Composition:
    app: Any
    services: Services
    adapters: Adapters
    session: DeviceSession
    engine: HostEngine
    pipeline: LayoutPipeline
    gate: OutboundGate
    stream: PlayStream
    hub: WebSocketHub
    release_at_exit: Callable[[], Any]
    parts: tuple = ()            # the composed modules (contract 2: the lab), in registration order


def _is_factory(module) -> bool:
    return callable(module) and not isinstance(module, HostModule)


def compose(config: Config, adapters: Adapters, modules=(), *, local_names=None) -> Composition:
    a = adapters
    parts = tuple(module(config, a) if _is_factory(module) else module for module in modules)
    collection = collect([getattr(part, "module", part) for part in parts])
    gate = OutboundGate(collection.policy(CONTRACT1_POLICY))      # ONE gate, shared by engine and session
    activity, stream, library = ActivityLog(), PlayStream(a.clock), LayoutLibrary()
    sections = collection.sections or None
    tweaks = TweakService(a.files, catalog=a.midi, sections=sections)
    calibration = CalibrationService(a.store)
    engine_ref: dict = {}
    learn = LearnService(tweaks, a.midi, context=lambda: engine_ref["engine"].context())
    engine = HostEngine(gate=gate, targets=a.midi, feedback=a.midi, activity=activity, stream=stream, library=library,
                        learn=learn, calibration=calibration, clock=a.clock, store=a.store, catalog=a.midi,
                        dispatch=a.dispatch, modules=collection)
    engine_ref["engine"] = engine
    pipeline = LayoutPipeline(source=a.files, versions=a.versions, library=library, engine=engine, clock=a.clock,
                              catalog=a.midi, compile=partial(compile_text, sections=sections) if sections else compile_text)
    if collection.hooks:
        tweaks.on_saved = pipeline.changed          # a saved section tweak is a new version at once (s39)
    session = DeviceSession(locator=a.locator, holders=a.holders, port=a.unit_port, prompt=a.prompt, store=a.store,
                            gate=gate, engine=engine, clock=a.clock, auto_accept=config.auto_accept,
                            dispatch=a.dispatch, modules=collection.hooks)
    state = StateView(engine=engine, session=session, library=library, calibration=calibration, learn=learn,
                      panels=collection.panels)
    hub = WebSocketHub(state, activity, stream)
    services = Services(session=session, engine=engine, pipeline=pipeline, library=library, tweaks=tweaks,
                        learn=learn, calibration=calibration, state=state, activity=activity, gate=gate,
                        ports=a.midi, hub=hub, routers=collection.routers, panels=collection.panels)
    if collection.hooks:
        collection.hooks.bind(HostPorts(display=engine, notes=engine, loader=engine, tweaks=tweaks,
                                        sysex=session.sysex_tap, gate=gate, stream=stream, topics=hub, clock=a.clock,
                                        dispatch=a.dispatch, inputs=a.midi, views=engine))
    for part in parts:
        naming = getattr(part, "name_layouts", None)
        if callable(naming):
            library.subscribe(lambda naming=naming: naming(library.summaries()))

    @contextlib.asynccontextmanager
    async def lifespan(app):
        loop = asyncio.get_running_loop()
        a.dispatch.bind(loop)
        a.clock.bind(loop)
        for start in a.starts:
            start()
        pipeline.start()
        engine.start()
        session.start()
        for part in parts:
            if callable(getattr(part, "start", None)):
                part.start()
        log.info("APC64 host ready (%s)%s", "simulated APC64" if a.simulator is not None else "real APC64",
                 f" with {', '.join(collection.names)}" if collection.names else "")
        try:
            yield
        finally:
            answer = await session.release(ReleaseReason.STOP)
            session.stop()
            for part in parts:
                try:
                    if callable(getattr(part, "stop", None)):
                        part.stop()
                except Exception:
                    log.exception("stopping module %s failed", getattr(getattr(part, "module", part), "name", part))
            for stop in a.stops:
                try:
                    stop()
                except Exception:
                    log.exception("stopping %s failed", stop)
            log.info("APC64 host stopped (%s)", answer.text)

    app = build_app(services, static_dir=STATIC_DIR, lifespan=lifespan, networks=config.allowed_networks,
                    local_names=local_names)

    def release_at_exit():
        try:
            return session.release_now(ReleaseReason.STOP)
        except Exception:      # never raise from an exit hook
            log.exception("release at exit failed")
            return None

    return Composition(app, services, a, session, engine, pipeline, gate, stream, hub, release_at_exit, parts)


# --- the process ------------------------------------------------------------------------------------------
def _serve_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m _apc64_host", description="Serve the APC64 host.")
    p.add_argument("serve", nargs="?", help="serve (the default)")
    p.add_argument("--simulate", action="store_true",
                   help="use the simulated APC64 and in-memory MIDI ports (no ALSA, no desktop notifications)")
    p.add_argument("--host", help="listen address (default APC64_HTTP_HOST, :: — every IPv6 and IPv4 address)")
    p.add_argument("--port", type=int, help="listen port (default APC64_HTTP_PORT, 5058)")
    return p


def main(argv=None, environ=None, *, load_config=Config.load, serve=None, adapters_factory=None,
         register_exit=atexit.register) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    if argv and not argv[0].startswith("-") and argv[0] != "serve":
        from .presentation.cli import main as cli_main
        return cli_main(argv, environ=environ, modules=lab_cli_modules())
    args = _serve_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    factory = adapters_factory or (simulated_adapters if args.simulate else real_adapters)
    try:
        config = load_config(environ)
        composition = compose(config, factory(config), modules=MODULES)
    except ConfigError as error:
        raise SystemExit(f"apc64-host: invalid configuration: {error.key}: {error.problem}") from None
    register_exit(composition.release_at_exit)
    if serve is None:
        import uvicorn
        serve = uvicorn.run
        # uvicorn re-raises SIGTERM/SIGINT after its graceful shutdown; exit 0 then (s7.c3), not by the signal
        signal.signal(signal.SIGTERM, _exit_cleanly)
        signal.signal(signal.SIGINT, _exit_cleanly)
    serve(composition.app, host=config.http_host if args.host is None else args.host, port=config.http_port if args.port is None else args.port,
          lifespan="on", ws="auto", log_level="info")
    return 0


def _exit_cleanly(signum, frame):
    raise SystemExit(0)


if __name__ == "__main__":
    sys.exit(main())
