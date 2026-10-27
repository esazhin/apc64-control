import asyncio
import os
import stat

from _apc64_host.application.ports import ConsentAnswer, ConsentPrompt
from _apc64_host.infrastructure.notifier import DesktopNotifier

ASK = "Take control of APC64?"
ARGV = ["notify-send", "-a", "APC64 Host", "-A", "take=Take", "-w", ASK]


class FakeProcess:
    """notify-send -w: prints the clicked action's key, or exits silently when the notification is closed."""

    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.returncode = None
        self.terminated = False
        self._exited = asyncio.Event()

    def click_take(self):
        if not self.stdout.at_eof():
            self.stdout.feed_data(b"take\n")
        self.exit(0)

    def exit(self, code=0):
        if not self.stdout.at_eof():
            self.stdout.feed_eof()
        self.returncode = code
        self._exited.set()

    def terminate(self):
        self.terminated = True
        self.exit(-15)

    async def wait(self):
        await self._exited.wait()
        return self.returncode


class Spawner:
    def __init__(self, error=None):
        self.argv, self.processes, self.error = [], [], error

    async def __call__(self, argv):
        self.argv.append(list(argv))
        if self.error:
            raise self.error
        process = FakeProcess()
        self.processes.append(process)
        return process


async def started(spawner, count=1):
    while len(spawner.processes) < count:
        await asyncio.sleep(0)
    return spawner.processes[count - 1]


def test_a_click_on_take_resolves_the_ask_take_once():
    # T17, s35.c2, s86.c1–c2, s91.c2
    async def scenario():
        spawner = Spawner()
        notifier = DesktopNotifier(spawn=spawner)
        assert isinstance(notifier, ConsentPrompt)
        asking = asyncio.ensure_future(notifier.ask(ASK))
        (await started(spawner)).click_take()
        return await asking, spawner.argv

    answer, argv = asyncio.run(scenario())
    assert answer is ConsentAnswer.TAKE
    assert argv == [ARGV]


def test_closing_the_notification_resolves_dismissed():
    # s86.c2, s91.c3
    async def scenario():
        spawner = Spawner()
        notifier = DesktopNotifier(spawn=spawner)
        asking = asyncio.ensure_future(notifier.ask(ASK))
        (await started(spawner)).exit(0)
        return await asking

    assert asyncio.run(scenario()) is ConsentAnswer.DISMISSED


def test_withdraw_resolves_dismissed_terminates_and_a_late_click_is_ignored():
    # T17, s35.c1, s86.c1 (terminate to withdraw), s91.c3
    async def scenario():
        spawner = Spawner()
        notifier = DesktopNotifier(spawn=spawner)
        asking = asyncio.ensure_future(notifier.ask(ASK))
        process = await started(spawner)
        process.terminate = lambda: setattr(process, "terminated", True)   # a slow exit: still running
        notifier.withdraw()
        answer = await asking
        process.click_take()                                               # the user clicks after the banner yes
        await asyncio.sleep(0)
        return answer, process.terminated

    answer, terminated = asyncio.run(scenario())
    assert answer is ConsentAnswer.DISMISSED and terminated


def test_a_new_ask_withdraws_the_pending_one():
    async def scenario():
        spawner = Spawner()
        notifier = DesktopNotifier(spawn=spawner)
        first = asyncio.ensure_future(notifier.ask(ASK))
        await started(spawner)
        second = asyncio.ensure_future(notifier.ask(ASK))
        (await started(spawner, 2)).click_take()
        return await first, await second, spawner.processes[0].terminated

    assert asyncio.run(scenario()) == (ConsentAnswer.DISMISSED, ConsentAnswer.TAKE, True)


def test_without_notify_send_or_a_session_bus_the_ask_is_dismissed_and_the_banner_remains():
    # a11: the page banner is the primary path; the notification is additive
    async def scenario():
        return await DesktopNotifier(spawn=Spawner(error=FileNotFoundError("notify-send"))).ask(ASK)

    assert asyncio.run(scenario()) is ConsentAnswer.DISMISSED
    DesktopNotifier(spawn=Spawner()).withdraw()   # nothing pending: harmless


def test_the_default_spawn_runs_the_program_and_reads_its_answer(tmp_path):
    # the real asyncio subprocess path, with a stand-in program instead of notify-send
    script = tmp_path / "fake-notify-send"
    script.write_text('#!/bin/sh\necho "$@" > "$(dirname "$0")/argv"\necho take\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    answer = asyncio.run(DesktopNotifier(program=str(script)).ask(ASK))
    assert answer is ConsentAnswer.TAKE
    assert (tmp_path / "argv").read_text().strip() == " ".join(ARGV[1:])

    silent = tmp_path / "silent"
    silent.write_text("#!/bin/sh\nexit 0\n")
    silent.chmod(silent.stat().st_mode | stat.S_IEXEC)
    assert asyncio.run(DesktopNotifier(program=str(silent)).ask(ASK)) is ConsentAnswer.DISMISSED
    assert os.path.exists(script)
