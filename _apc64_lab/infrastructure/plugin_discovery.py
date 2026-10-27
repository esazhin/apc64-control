"""GeneratorSource over the plugin directory _apc64_lab/generators/ (contract s17 supplier, s18; d12–d16; A18–A20).

discover() imports every module of the package once, in file order, and gives (file, GENERATOR or SCHEME), or
(file, DiscoveryError) for a module that raises on import, exposes neither, or exposes both. Test modules and
private ones (test_*, _*) are skipped. A plugin added while the service runs appears after the next restart
(d15): discovery runs only when the registry loads at start.
"""
import importlib
import logging
import pkgutil
from typing import Iterable

from ..application.ports import DiscoveryError

log = logging.getLogger(__name__)
PLUGINS = "_apc64_lab.generators"


class PluginDiscovery:
    def __init__(self, package: str = PLUGINS, path: Iterable[str] | None = None):
        self.package = package
        self.path = list(path) if path is not None else None

    def discover(self) -> list[tuple[str, object]]:
        package = importlib.import_module(self.package)
        search = self.path if self.path is not None else list(package.__path__)
        found = []
        for info in sorted(pkgutil.iter_modules(search), key=lambda i: i.name):
            if info.name.startswith(("test_", "_")) or info.ispkg:
                continue
            file = f"{self.package.replace('.', '/')}/{info.name}.py"
            try:
                module = importlib.import_module(f"{self.package}.{info.name}")
            except Exception as error:   # a plugin may fail any way on import; it is listed as broken
                log.warning("lab: plugin %s failed to import: %s", file, error)
                found.append((file, DiscoveryError(str(error) or type(error).__name__)))
                continue
            exposed = [name for name in ("GENERATOR", "SCHEME") if hasattr(module, name)]
            if len(exposed) != 1:
                message = ("exposes both GENERATOR and SCHEME; one file holds one" if exposed
                           else "exposes neither GENERATOR nor SCHEME")
                found.append((file, DiscoveryError(message)))
                continue
            found.append((file, getattr(module, exposed[0])))
        return found
