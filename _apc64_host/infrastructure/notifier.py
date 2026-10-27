"""ConsentPrompt as a desktop notification (contract §7, s35/s86/s91, a11):
`notify-send -a 'APC64 Host' -A take=Take -w '<text>'` waits until the notification is answered.

stdout 'take' → TAKE. Exiting without it (closed, expired, no session bus, no notify-send) → DISMISSED.
withdraw() resolves the pending ask DISMISSED at once and terminates the notification, so a click arriving
after it (e.g. after a Yes on the page) is ignored. One ask is pending at a time: a new ask withdraws the
previous one. DISMISSED is not a No: the page banner stays the primary way to answer.
"""
import asyncio
import logging
from typing import Awaitable, Callable

from ..application.ports import ConsentAnswer

APP_NAME = "APC64 Host"
ACTION = "take"
REAP_TIMEOUT = 2.0

log = logging.getLogger(__name__)


async def _spawn(argv):
    return await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL,
                                                stdin=asyncio.subprocess.DEVNULL)


class DesktopNotifier:
    def __init__(self, program: str = "notify-send", spawn: Callable[[list[str]], Awaitable] = _spawn):
        self._program = program
        self._spawn = spawn
        self._pending: tuple[object, asyncio.Event] | None = None

    def argv(self, text: str) -> list[str]:
        return [self._program, "-a", APP_NAME, "-A", f"{ACTION}=Take", "-w", text]

    async def ask(self, text: str) -> ConsentAnswer:
        self.withdraw()
        withdrawn = asyncio.Event()
        try:
            process = await self._spawn(self.argv(text))
        except (OSError, ValueError) as error:
            log.info("notifier: no desktop notification (%s); the page banner asks instead", error)
            return ConsentAnswer.DISMISSED
        self._pending = (process, withdrawn)
        reading = asyncio.ensure_future(process.stdout.readline())
        waiting = asyncio.ensure_future(withdrawn.wait())
        try:
            await asyncio.wait({reading, waiting}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiting.cancel()
            if self._pending is not None and self._pending[0] is process:
                self._pending = None
        if withdrawn.is_set() or not reading.done():
            reading.cancel()
            return ConsentAnswer.DISMISSED
        try:
            line = reading.result()
        except Exception:
            line = b""
        answer = ConsentAnswer.TAKE if line.strip() == ACTION.encode() else ConsentAnswer.DISMISSED
        asyncio.ensure_future(self._reap(process))
        return answer

    def withdraw(self) -> None:
        if self._pending is None:
            return
        process, withdrawn = self._pending
        self._pending = None
        withdrawn.set()
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        except Exception:
            log.exception("notifier: could not withdraw the notification")
        try:
            asyncio.ensure_future(self._reap(process))
        except RuntimeError:   # no running loop: nothing to reap with
            pass

    @staticmethod
    async def _reap(process) -> None:
        try:
            await asyncio.wait_for(process.wait(), REAP_TIMEOUT)
        except (asyncio.TimeoutError, Exception):
            try:
                process.kill()
            except Exception:
                pass


class SilentPrompt:
    """A ConsentPrompt that shows nothing: the page banner (and the CLI) are the only ways to say yes.

    Used by the simulated run (`python -m _apc64_host --simulate`) so a development run never pops a desktop
    notification. ask() waits until withdrawn and then answers DISMISSED, which is not a No (§2.6 a11).
    """

    def __init__(self):
        self.asked: list[str] = []
        self._withdrawn: asyncio.Event | None = None

    async def ask(self, text: str) -> ConsentAnswer:
        self.withdraw()
        self.asked.append(text)
        withdrawn = self._withdrawn = asyncio.Event()
        await withdrawn.wait()
        return ConsentAnswer.DISMISSED

    def withdraw(self) -> None:
        if self._withdrawn is not None:
            self._withdrawn.set()
            self._withdrawn = None
