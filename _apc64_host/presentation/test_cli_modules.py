"""T41 (contract 2): the apc64 command mounts module subcommands (WIRES s29; inv9).

A module's subcommand is parsed and run over the command's transport; contract 1's commands are unchanged with a
module mounted and without one; the installed entry point and `python -m _apc64_host` both reach the lab; and one
composition case: `apc64 lab list` reaches the lab API route of the composed service through the client."""
import io

from fastapi.testclient import TestClient

from _apc64_host import __main__ as root
from _apc64_host.presentation import cli
from _apc64_host.presentation.test_cli import FakeTransport
from _apc64_host.test___main__ import BASE, config_for


class Demo:
    name = "demo"

    def __init__(self):
        self.ran = []

    def register(self, sub, common):
        command = sub.add_parser("demo", help="a module's commands", parents=[common])
        command.add_argument("word")

    def run(self, args, transport, out, err, as_json):
        status, data = transport.request("GET", f"/api/demo/{args.word}")
        self.ran.append((args.word, as_json))
        print(data["message"], file=out)
        return 0 if status == 200 else 1


class Answers:
    def __init__(self, answers):
        self.answers, self.requests = answers, []

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        return self.answers[(method, path)]


def run(argv, transport, modules):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, transport=transport, out=out, err=err, environ={}, modules=modules)
    return code, out.getvalue(), err.getvalue()


def test_a_module_subcommand_runs_over_the_commands_transport():
    demo = Demo()
    transport = Answers({("GET", "/api/demo/ping"): (200, {"message": "pong"})})
    assert run(["demo", "ping", "--json"], transport, (demo,)) == (0, "pong\n", "")
    assert demo.ran == [("ping", True)] and transport.requests == [("GET", "/api/demo/ping", None)]


def test_contract_1_commands_are_unchanged_with_and_without_a_module():
    for modules in ((), (Demo(),)):
        transport = FakeTransport({("GET", "/api/layouts"): (200, [
            {"id": "jam", "file": "jam.yaml", "name": "Jam", "valid": True, "pages": 2, "banks": 1, "errors": 0}])})
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["layouts"], transport=transport, out=out, err=err, environ={}, modules=modules)
        assert code == 0 and transport.requests[0][:2] == ("GET", "/api/layouts")
        assert out.getvalue() == "jam.yaml  Jam  2 pages, 1 bank\n"


def test_the_installed_entry_point_is_the_lab():
    names = [m.name for m in cli.installed_modules()]
    assert names == ["lab"], "reinstall: .venv/bin/pip install -e . --no-deps"


def test_python_m_apc64_host_reaches_the_lab_command(capsys):
    code = root.main(["lab", "list"], {"APC64_URL": "http://127.0.0.1:9"})
    assert code == 2 and "service not running on port 9" in capsys.readouterr().err


class ClientTransport:
    def __init__(self, client):
        self.client = client

    def request(self, method, path, body=None):
        answer = self.client.request(method, path, json=body) if body is not None else self.client.request(method, path)
        return answer.status_code, answer.json()


def test_apc64_lab_list_reaches_the_lab_route_of_the_composed_service(tmp_path):   # s29 wired
    (tmp_path / "layouts").mkdir()
    config = config_for(tmp_path)
    comp = root.compose(config, root.simulated_adapters(config), root.MODULES)
    (lab,) = comp.parts
    states = []
    original = lab.session.state
    lab.session.state = lambda: states.append(1) or original()
    with TestClient(comp.app, base_url=BASE, client=("127.0.0.1", 4000)) as client:
        code, out, err = run(["lab", "list"], ClientTransport(client), root.lab_cli_modules())
    assert code == 0 and states, err
    assert out.splitlines()[:3] == ["generators:", "  tonnetz  base 0–127 (default 48), channel 1–16 (default 1)",
                                    "  isomorphic  base 0–127 (default 36), column -12–12 (default 1), row -12–12 "
                                    "(default 5), channel 1–16 (default 1)"]
