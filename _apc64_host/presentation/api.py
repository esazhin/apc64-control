"""The HTTP API and the page (contract §3.5, s9–s25; docs/api.md).

build_app(services) gives the FastAPI app: every route of docs/api.md, the static page, the WebSocket routes
handed to the hub, module routers and panels, all behind the NetworkGuard. The page and the CLI use these same
routes (inv22, a21): there is no second state path.

Answers: 200 with the route's JSON; 400 {problem, allowed?} for a malformed or out-of-range request (nothing
changes, d126); 409 {problem} for a refusal ('already held', 'APC64 is not held', 'layout changed, reload',
'no layout x'). The API accepts layout text or a layout id, never a file path (§7.1).
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..application.engine import UnknownLayout, ViewNotSent
from ..application.layout_pipeline import UnknownVersion
from ..application.learn import LearnMode, UnknownPort
from ..application.session import ReleaseResult, TakeResult
from ..application.state_view import UnknownControl
from ..application.tweaks import Invalid, Saved, Stale
from ..domain.controls import ControlRole, Encoder, EncoderPress, Strip, StripTouch, entry, parse_control
from ..domain.effects import NOT_SWITCHED, SWITCHABLE_VIEWS, EncoderTurn, Press, Release, StripMove
from ..domain.issues import DomainInvariantError
from ..domain.layout import MAX_BANKS, MAX_PAGES, Layer, LayoutId, TweakField, TweakRequest
from ..domain.network import AllowedNetworks, ClientAddress
from ..domain.unit_status import ConsentSource
from . import view_model as _view_model
from .network_guard import NetworkGuard
from .ws_hub import Channel

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
PAGES = list(range(1, MAX_PAGES + 1))
BANKS = list(range(1, MAX_BANKS + 1))


@dataclass
class Services:
    """Everything the API talks to (constructor-injected by the composition root, doubles in tests)."""
    session: Any
    engine: Any
    pipeline: Any
    library: Any
    tweaks: Any
    learn: Any
    calibration: Any
    state: Any
    activity: Any
    gate: Any
    ports: Any                      # PortCatalog
    hub: Any
    routers: tuple = ()             # HostModule routers (none in contract 1)
    panels: tuple = ()              # (module name, static directory)
    extra: dict = field(default_factory=dict)


class Refusal(Exception):
    """An answer other than 200: raised by the handlers' helpers, turned into JSON by the app."""

    def __init__(self, code: int, problem: str, **extra):
        self.code, self.problem, self.extra = code, problem, extra
        super().__init__(problem)


def _bad(problem: str, **extra) -> Refusal:
    return Refusal(400, problem, **extra)


async def _body(request: Request) -> dict:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise _bad("the request body is not JSON", allowed=["a JSON object"]) from None
    if not isinstance(data, dict):
        raise _bad("the request body must be a JSON object", allowed=["a JSON object"])
    return data


def _number(value, low: int, high: int, word: str) -> int:
    if isinstance(value, bool):
        value = None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    if not isinstance(value, int) or not low <= value <= high:
        raise _bad(f"{word} must be {low}–{high}", allowed=list(range(low, high + 1)))
    return value


def _control(name: str):
    try:
        control = parse_control(name)
    except DomainInvariantError as error:
        raise _bad(f"{error.problem}{error.joiner}{error.fix}") from None
    return control


def build_app(services: Services, *, static_dir=STATIC_DIR, view_model=_view_model, lifespan=None,
              networks: AllowedNetworks | None = None, local_names=None) -> FastAPI:
    vm = view_model
    s = services
    app = FastAPI(title="APC64 Host", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(NetworkGuard, networks=networks, local_names=local_names)
    app.state.services = services

    @app.exception_handler(Refusal)
    async def refusal(request, error: Refusal):
        return JSONResponse(vm.problem(error.problem, **error.extra), status_code=error.code)

    def state_now() -> dict:
        return vm.state_json(s.state.snapshot())

    # --- state and the unit (s15, s22) ---------------------------------------------------------------
    @app.get("/api/state")
    async def get_state():
        return state_now()

    @app.get("/api/unit")
    async def get_unit():
        return vm.unit_json(s.state.snapshot().unit)

    def consent_source(request: Request, data: dict) -> ConsentSource:
        wanted = str(data.get("source") or ("banner" if request.headers.get("origin") else "agent")).lower()
        if wanted == "agent":
            return ConsentSource.AGENT
        if wanted == "notification":
            return ConsentSource.NOTIFICATION
        if wanted != "banner":
            raise _bad(f"unknown source {wanted}", allowed=["banner", "agent"])
        client = request.client.host if request.client else "127.0.0.1"
        try:
            loopback = ClientAddress.parse(client).address.is_loopback
        except DomainInvariantError:
            loopback = False
        return ConsentSource.BANNER if loopback else ConsentSource.LAN_BROWSER

    @app.post("/api/unit/take")
    async def take(request: Request):
        source = consent_source(request, await _body(request))
        answer = await s.session.take(source)
        body = vm.take_json(answer, s.session.status())
        if answer.result is TakeResult.TAKEN:
            return body
        raise Refusal(409, answer.text, **body)

    @app.post("/api/unit/decline")
    async def decline(request: Request):
        await _body(request)
        s.session.decline()
        status = s.session.status()
        return {"status": status.status, "text": status.text}

    @app.post("/api/unit/release")
    async def release(request: Request):
        await _body(request)
        answer = await s.session.release()
        status = s.session.status()
        if answer is ReleaseResult.NOT_HELD:
            raise Refusal(409, answer.text, status=status.status)
        return {"result": str(answer), "text": answer.text, "status": status.status, "status_text": status.text}

    # --- ports and layouts (s18, s25) ----------------------------------------------------------------
    @app.get("/api/ports")
    async def ports():
        snapshot = s.engine.snapshot()
        layout = snapshot.layout
        declared = [(d, layout.devices[d].pattern) for d in sorted(snapshot.missing)
                    if layout is not None and d in layout.devices]
        return vm.ports_json(s.ports.list(), declared)

    @app.get("/api/layouts")
    async def layouts():
        return [vm.layout_summary_json(x) for x in s.library.summaries()]

    def layout_id(name) -> str:
        """A layout id (file name), or a display name that names exactly one layout."""
        if not isinstance(name, str) or not name.strip():
            raise _bad("name a layout", allowed=[str(x.id) for x in s.library.summaries()])
        name = name.strip()
        summaries = s.library.summaries()
        if any(str(x.id) == name for x in summaries):
            return name
        by_name = [x for x in summaries if x.name.casefold() == name.casefold()]
        if len(by_name) == 1:
            return str(by_name[0].id)
        if name.endswith(".yaml") and any(str(x.id) == name[:-5] for x in summaries):
            return name[:-5]
        return name

    @app.post("/api/validate")
    async def validate(request: Request):
        data = await _body(request)
        if "path" in data and "text" not in data:
            raise _bad("send the layout text, not a path: the service never reads paths you name",
                       allowed=["text", "file"])
        text = data.get("text")
        if not isinstance(text, str):
            raise _bad("send the layout text as 'text'", allowed=["text", "file"])
        file = str(data.get("file") or "layout.yaml").replace("\\", "/").rsplit("/", 1)[-1] or "layout.yaml"
        return vm.validation_json(s.pipeline.validate_text(text, file))

    # --- navigation (s16) ------------------------------------------------------------------------------
    def nav_answer(answer):
        if isinstance(answer, UnknownLayout):
            raise Refusal(409, answer.problem, allowed=list(answer.allowed))
        if isinstance(answer, ViewNotSent):
            raise Refusal(409, answer.problem)
        return state_now()

    @app.post("/api/layout")
    async def load(request: Request):
        data = await _body(request)
        return nav_answer(s.engine.load(layout_id(data.get("name", data.get("layout")))))

    @app.post("/api/page")
    async def page(request: Request):
        data = await _body(request)
        return nav_answer(s.engine.select_page(_number(data.get("n", data.get("page")), 1, MAX_PAGES, "page")))

    @app.post("/api/bank")
    async def bank(request: Request):
        data = await _body(request)
        return nav_answer(s.engine.select_bank(_number(data.get("n", data.get("bank")), 1, MAX_BANKS, "bank")))

    @app.post("/api/shift")
    async def shift(request: Request):
        data = await _body(request)
        held = data.get("held")
        if not isinstance(held, bool):
            raise _bad("held must be true or false", allowed=[True, False])
        return nav_answer(s.engine.set_page_shift(held))

    # --- replica input (s16; a19, d49) -------------------------------------------------------------------
    def replica_control(name: str):
        control = _control(name)
        if entry(control).role is ControlRole.DEVICE_LOCAL:   # a view button: the pad-mode request (2026-10-27)
            kind = str(control.kind)
            if kind not in SWITCHABLE_VIEWS:
                raise _bad(NOT_SWITCHED.get(kind, f"{name} is the unit's own button; it never reaches the host"),
                           allowed=[f"view {v}" for v in SWITCHABLE_VIEWS])
        return control

    def view_of(control):
        return SWITCHABLE_VIEWS.get(str(control.kind)) if entry(control).role is ControlRole.DEVICE_LOCAL else None

    @app.post("/api/control/{name}/press")
    async def press(name: str, request: Request):
        data = await _body(request)
        control = replica_control(name)
        if view_of(control) is not None:
            return nav_answer(s.engine.press_view(view_of(control)))
        if isinstance(control, Strip):
            control = StripTouch(control.n)
        if isinstance(control, Encoder):
            control = EncoderPress()
        velocity = _number(data.get("value", 127), 1, 127, "velocity")
        return nav_answer(s.engine.replica_input(Press(control, velocity)))

    @app.post("/api/control/{name}/release")
    async def release_control(name: str, request: Request):
        await _body(request)
        control = replica_control(name)
        if view_of(control) is not None:
            return state_now()   # the press switched the view; letting go does nothing
        if isinstance(control, Strip):
            control = StripTouch(control.n)
        if isinstance(control, Encoder):
            control = EncoderPress()
        return nav_answer(s.engine.replica_input(Release(control)))

    @app.post("/api/control/{name}/move")
    async def move(name: str, request: Request):
        data = await _body(request)
        control = replica_control(name)
        if isinstance(control, (Strip, StripTouch)):
            value = _number(data.get("value"), 0, 16383, "value")
            return nav_answer(s.engine.replica_input(StripMove(Strip(control.n), value)))
        if isinstance(control, (Encoder, EncoderPress)):
            steps = data.get("value")
            if isinstance(steps, bool) or not isinstance(steps, int) or steps == 0 or abs(steps) > 63:
                raise _bad("value must be the encoder steps, -63…-1 or 1…63", allowed=[-1, 1])
            return nav_answer(s.engine.replica_input(EncoderTurn(steps)))
        raise _bad(f"{name} does not move; only strips and the encoder do",
                   allowed=[f"strip {n}" for n in range(1, 9)] + ["encoder"])

    # --- reads: card, overview, surface (s22) ----------------------------------------------------------
    @app.get("/api/controls/{name}")
    async def card(name: str):
        view = s.state.card(name)
        if isinstance(view, UnknownControl):
            raise _bad(view.problem)
        snapshot = s.engine.snapshot()
        layout, nav = snapshot.layout, snapshot.nav
        base_hash = s.tweaks.current_hash(layout.id) if layout is not None else None
        return vm.card_json(view, layout=layout.id if layout else None, page=nav.page, bank=nav.bank,
                            layer=nav.layer, base_hash=base_hash)

    @app.get("/api/overview")
    async def overview():
        return vm.overview_json(s.state.overview())

    @app.get("/api/surface")
    async def surface():
        return vm.surface_json(s.state.surface())

    # --- versions (s17) ----------------------------------------------------------------------------------
    def known_layout(name: str) -> LayoutId:
        try:
            return LayoutId(layout_id(name))
        except DomainInvariantError as error:
            raise _bad(f"{error.problem}; {error.fix}") from None

    @app.get("/api/layouts/{name}/versions")
    async def versions(name: str):
        return vm.versions_json(s.pipeline.versions(known_layout(name)))

    @app.post("/api/layouts/{name}/restore")
    async def restore(name: str, request: Request):
        data = await _body(request)
        layout = known_layout(name)
        version = data.get("id", data.get("version"))
        if not isinstance(version, str) or not version:
            raise _bad("send the version id", allowed=[str(v) for v in s.pipeline.versions(layout)][:20])
        answer = s.pipeline.restore(layout, version)
        if isinstance(answer, UnknownVersion):
            raise Refusal(409, f"no version {answer.version} of {layout}",
                          allowed=[str(v) for v in s.pipeline.versions(layout)][:20])
        return {"restored": str(answer.version), "at": vm.stamp_iso(answer.version.timestamp), "layout": layout}

    # --- tweak, learn, calibrate (s19–s21) -------------------------------------------------------------
    @app.post("/api/tweak")
    async def tweak(request: Request):
        data = await _body(request)
        snapshot = s.engine.snapshot()
        live, nav = snapshot.layout, snapshot.nav
        control = _control(str(data.get("control", "")))
        if isinstance(control, StripTouch):
            control = Strip(control.n)
        if entry(control).role is not ControlRole.BINDABLE:
            raise _bad(f"{control} is not bindable: scene and strip-mode buttons navigate, Shift is the modifier")
        field_name = data.get("field")
        if field_name not in [f.value for f in TweakField]:
            raise _bad(f"unknown field {field_name}", allowed=[f.value for f in TweakField])
        base_hash = data.get("base_hash")
        if not isinstance(base_hash, str) or not base_hash:
            raise _bad("send base_hash: the hash the card was read with", allowed=["base_hash"])
        layout = data.get("layout") or (live.id if live else None)
        if layout is None:
            raise _bad("no layout is live; name one", allowed=[str(x.id) for x in s.library.summaries()])
        layer = data.get("layer") or str(nav.layer)
        if layer not in ("base", "shift"):
            raise _bad(f"unknown layer {layer}", allowed=["base", "shift"])
        strip = isinstance(control, Strip)
        page_n = None if strip else data.get("page", int(nav.page))
        bank_n = data.get("bank", int(nav.bank)) if strip else None
        if page_n is not None:
            page_n = _number(page_n, 1, MAX_PAGES, "page")
        if bank_n is not None:
            bank_n = _number(bank_n, 1, MAX_BANKS, "bank")
        value = data.get("value")
        if value is not None and not isinstance(value, str):
            value = str(value)
        try:
            request_ = TweakRequest(LayoutId(layout_id(layout)), Layer(layer), control, TweakField(field_name), value,
                                    base_hash, page=page_n, bank=bank_n)
        except DomainInvariantError as error:
            raise _bad(f"{error.problem}{error.joiner}{error.fix}") from None
        answer = s.tweaks.apply(request_)
        if isinstance(answer, Saved):
            return {"ok": True, "hash": str(answer.hash)}
        if isinstance(answer, Stale):
            raise Refusal(409, answer.message)
        if isinstance(answer, Invalid):
            issues = [vm.issue_json(i) for i in answer.issues]
            raise Refusal(400, issues[0]["text"] if issues else "the tweak would make the layout invalid",
                          issues=issues)
        raise Refusal(409, "the tweak was not saved")

    @app.post("/api/learn")
    async def learn(request: Request):
        data = await _body(request)
        mode = data.get("mode")
        if mode not in ("touch", "midi", "off"):
            raise _bad(f"unknown learn mode {mode}", allowed=["touch", "midi", "off"])
        if data.get("control"):
            s.learn.select(_control(str(data["control"])))
        if mode == "midi":
            port = data.get("port")
            if not isinstance(port, str) or not port:
                raise _bad("MIDI-learn listens on one input: send its device or port name", allowed=["port"])
            answer = s.learn.set_mode(LearnMode.midi(port))
        else:
            answer = s.learn.set_mode(LearnMode.touch() if mode == "touch" else LearnMode.off())
        if isinstance(answer, UnknownPort):
            raise Refusal(409, f"unknown port {answer.port}", allowed=list(answer.allowed))
        return vm.learn_json(answer.status)

    @app.post("/api/calibrate")
    async def calibrate(request: Request):
        data = await _body(request)
        step = data.get("step")
        if step not in ("start", "cancel"):
            raise _bad(f"unknown step {step}", allowed=["start", "cancel"])
        status = s.calibration.start() if step == "start" else s.calibration.cancel()
        return {"step": str(status.step), "text": status.text, "problem": status.problem,
                "calibration": vm.calibration_json(s.calibration.current())}

    # --- logs (s23, s24) ---------------------------------------------------------------------------------
    @app.get("/api/activity")
    async def activity(limit: str = "200"):
        n = _number(limit, 1, 200, "limit")
        return [vm.activity_json(r) for r in s.activity.records(n)]

    @app.get("/api/device-log")
    async def device_log(limit: str | None = None):
        entries = s.gate.device_log()
        if limit is not None:
            entries = entries[-_number(limit, 1, 100000, "limit"):]
        return vm.device_log_json(entries)

    # --- WebSockets (s12) --------------------------------------------------------------------------------
    @app.websocket("/ws")
    async def ws_state(ws: WebSocket):
        await s.hub.accept(ws, Channel.STATE)

    @app.websocket("/ws/play")
    async def ws_play(ws: WebSocket):
        await s.hub.accept(ws, Channel.PLAY)

    # --- modules (contract 2's seam) and the page ----------------------------------------------------------
    for router in s.routers:
        app.include_router(router)
    for name, directory in s.panels:
        app.mount(f"/modules/{name}", StaticFiles(directory=str(directory), html=True), name=f"module-{name}")

    static = Path(static_dir)

    @app.middleware("http")
    async def revalidate_page_files(request, call_next):
        """The page's files are re-checked on every load (cheap on the LAN), so an update is never half-cached."""
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static / "index.html", media_type="text/html")

    if static.is_dir():
        app.mount("/", StaticFiles(directory=str(static)), name="static")
    return app

