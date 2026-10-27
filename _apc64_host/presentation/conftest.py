"""Presentation test helpers: the real application graph over the simulated APC64 and in-memory ports."""
import asyncio
import contextlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _apc64_host.application.activity import ActivityLog
from _apc64_host.application.calibration import CalibrationService
from _apc64_host.application.conftest import MemorySource, MemoryStore
from _apc64_host.application.engine import HostEngine
from _apc64_host.application.layout_pipeline import LayoutPipeline
from _apc64_host.application.learn import LearnService
from _apc64_host.application.library import LayoutLibrary
from _apc64_host.application.outbound_gate import OutboundGate
from _apc64_host.application.play_stream import PlayStream
from _apc64_host.application.session import DeviceSession
from _apc64_host.application.state_view import StateView
from _apc64_host.application.tweaks import TweakService
from _apc64_host.domain.outbound import CONTRACT1_POLICY
from _apc64_host.infrastructure.clock import AsyncioClock
from _apc64_host.infrastructure.memory_ports import MemoryPorts
from _apc64_host.infrastructure.notifier import SilentPrompt
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_host.infrastructure.version_store import FileVersionStore
from _apc64_host.presentation.api import Services, build_app
from _apc64_host.presentation.ws_hub import WebSocketHub

JAM = """\
# Jam: drums on the grid  # a comment kept by tweaks
name: Jam
devices:
  mpc: MPC Live III MIDI 1
pages:
  1 Drums:
    pads r1c1-r2c8: notes from 36 on mpc ch 10 colour red   # bass line
    play: cc 118 on mpc ch 1
  2 Keys:
    pad r1c1: note 50 on mpc ch 10
banks:
  1 Mix:
    strips 1-8: cc 20-27 on mpc ch 1
routing:
  notes: mpc ch 2 aftertouch pass
"""

TONNETZ = """\
name: Tonnetz C
devices:
  mpc: MPC Live III MIDI 1
pages:
  1 Fifths:
    pads r1c1-r8c8: notes from 24 on mpc ch 1
  2 Thirds:
    pads r1c1-r1c8: notes from 48 on mpc ch 1
  3 Chords:
    pad r1c1: note 60 on mpc ch 1
banks:
  1 Mix:
    strips 1-8: cc 20-27 on mpc ch 1
  2 Sends:
    strips 1-8: cc 30-37 on mpc ch 1
"""

HOME = ("192.168.1.23", 50000)
BASE = "http://192.168.1.10:5058"
WS_BASE = "ws://192.168.1.10:5058"


def compose_rig(tmp_path, files=None, sim=None, ports=None):
    """The real services, wired as the composition root wires them, over hermetic adapters."""
    sim = sim or SimulatedApc64()
    ports = ports or MemoryPorts()
    clock = AsyncioClock()
    source = MemorySource({"jam": JAM, "tonnetz": TONNETZ} if files is None else files)
    store = MemoryStore()
    gate = OutboundGate(CONTRACT1_POLICY)
    activity, stream, library = ActivityLog(), PlayStream(clock), LayoutLibrary()
    tweaks = TweakService(source, catalog=ports)
    calibration = CalibrationService(store)
    holder = SimpleNamespace(engine=None)
    learn = LearnService(tweaks, ports, context=lambda: holder.engine.context())
    engine = HostEngine(gate=gate, targets=ports, feedback=ports, activity=activity, stream=stream, library=library,
                        learn=learn, calibration=calibration, clock=clock, store=store, catalog=ports)
    holder.engine = engine
    pipeline = LayoutPipeline(source=source, versions=FileVersionStore(tmp_path / "state"), library=library,
                              engine=engine, clock=clock, catalog=ports)
    prompt = SilentPrompt()
    session = DeviceSession(locator=sim, holders=sim.holder_lookup, port=sim, prompt=prompt, store=store, gate=gate,
                            engine=engine, clock=clock)
    state = StateView(engine=engine, session=session, library=library, calibration=calibration, learn=learn)
    hub = WebSocketHub(state, activity, stream)
    services = Services(session=session, engine=engine, pipeline=pipeline, library=library, tweaks=tweaks,
                        learn=learn, calibration=calibration, state=state, activity=activity, gate=gate,
                        ports=ports, hub=hub)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        clock.bind(asyncio.get_running_loop())
        pipeline.start()
        engine.start()
        session.start()
        yield
        await session.release("stop")
        session.stop()

    app = build_app(services, lifespan=lifespan, local_names=("studio-pc",))
    return SimpleNamespace(app=app, services=services, sim=sim, source=source, store=store,
                           prompt=prompt, **vars(services))


@pytest.fixture
def rig(tmp_path):
    built = compose_rig(tmp_path)
    with TestClient(built.app, base_url=BASE, client=HOME) as client:
        built.client = client
        built.on_loop = lambda fn, *args: client.portal.call(fn, *args)   # adapters call back on the loop
        built.ws = lambda path, **kwargs: client.websocket_connect(WS_BASE + path, **kwargs)
        yield built
