"""Service settings: APC64_* environment variables over an optional, git-ignored config.local over the defaults."""
from dataclasses import dataclass
from pathlib import Path

from .domain.issues import DomainInvariantError
from .domain.network import AllowedNetworks, DEFAULT_NETWORKS

REPO = Path(__file__).resolve().parents[1]
# KEY=VALUE lines (shell- and systemd-EnvironmentFile-compatible); see config.local.example
LOCAL_CONFIG = REPO / "config.local"

DEFAULTS = {
    "APC64_HTTP_PORT": "5058",
    "APC64_HTTP_HOST": "::",
    "APC64_LAYOUTS_DIR": "layouts",
    "APC64_STATE_DIR": "~/.local/state/apc64-host",
    "APC64_ALLOWED_NETWORKS": ",".join(DEFAULT_NETWORKS),
    "APC64_AUTO_ACCEPT": "0",
    "APC64_PORT_STEM": "APC64",
    # contract 2, the layout lab (read by the composition root, which registers the lab)
    "APC64_LAB_TARGET": "",
    "APC64_LAB_BACKUPS_DIR": "backups",
    "APC64_LAB_LIBRARY_DIR": "library",
    "APC64_LAB_PATTERNS_DIR": "patterns",
}
_TRUE, _FALSE = {"1", "true", "yes", "on"}, {"0", "false", "no", "off", ""}


class ConfigError(ValueError):
    """A setting that cannot be used; names its key so the service can say which line to fix."""

    def __init__(self, key: str, problem: str):
        self.key, self.problem = key, problem
        super().__init__(f"{key}: {problem}")


def read_local_config(path) -> dict:
    """The KEY=VALUE pairs of a config.local file; {} when there is none. '#' comments and blank lines are skipped."""
    if path is None or not Path(path).is_file():
        return {}
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def _port(key: str, text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ConfigError(key, f"must be a port number 1-65535, got {text!r}")
    return int(text)


def _flag(key: str, text: str) -> bool:
    if text.lower() in _TRUE:
        return True
    if text.lower() in _FALSE:
        return False
    raise ConfigError(key, f"must be 1 or 0 (yes/no), got {text!r}")


def _directory(key: str, text: str, base: Path) -> Path:
    if not text:
        raise ConfigError(key, "must name a directory")
    path = Path(text).expanduser()
    return path if path.is_absolute() else base / path


@dataclass(frozen=True)
class Config:
    http_port: int
    layouts_dir: Path
    state_dir: Path
    allowed_networks: AllowedNetworks
    auto_accept: bool
    port_stem: str
    # contract 2 (the layout lab): the default note target for generated layouts ('' = none: notes only shown,
    # unless a layout routes them), and where its backups and library live; None = the repository's backups/
    # and library/. The composition root validates the target (a bad one is a start-up error naming the key).
    lab_target: str = ""
    lab_backups_dir: Path | None = None
    lab_library_dir: Path | None = None
    lab_patterns_dir: Path | None = None   # the performer's patterns (contract 2 §2.10); None = the repository's
    # the listen address: '::' = every IPv6 and IPv4 address (dual-stack, a28); `serve --host` overrides it
    http_host: str = "::"

    @classmethod
    def load(cls, environ, path=LOCAL_CONFIG) -> "Config":
        """Defaults, then config.local, then the environment; relative directories are under the repository."""
        base = Path(path).resolve().parent if path is not None else REPO
        values = {**DEFAULTS, **read_local_config(path),
                  **{k: v for k, v in environ.items() if k in DEFAULTS}}
        try:
            networks = AllowedNetworks.parse(values["APC64_ALLOWED_NETWORKS"])
        except DomainInvariantError as error:
            raise ConfigError("APC64_ALLOWED_NETWORKS", f"{error.problem}; {error.fix}") from None
        host = values["APC64_HTTP_HOST"].strip()
        if not host:
            raise ConfigError("APC64_HTTP_HOST", "must be a listen address, e.g. :: (every address) or 127.0.0.1")
        stem = values["APC64_PORT_STEM"].strip()
        if not stem:
            raise ConfigError("APC64_PORT_STEM", "must be the start of the APC64's port names, e.g. APC64")
        return cls(
            http_port=_port("APC64_HTTP_PORT", values["APC64_HTTP_PORT"].strip()),
            layouts_dir=_directory("APC64_LAYOUTS_DIR", values["APC64_LAYOUTS_DIR"].strip(), base),
            state_dir=_directory("APC64_STATE_DIR", values["APC64_STATE_DIR"].strip(), base),
            allowed_networks=networks,
            auto_accept=_flag("APC64_AUTO_ACCEPT", values["APC64_AUTO_ACCEPT"].strip()),
            port_stem=stem,
            lab_target=" ".join(values["APC64_LAB_TARGET"].split()),
            lab_backups_dir=_directory("APC64_LAB_BACKUPS_DIR", values["APC64_LAB_BACKUPS_DIR"].strip(), base),
            lab_library_dir=_directory("APC64_LAB_LIBRARY_DIR", values["APC64_LAB_LIBRARY_DIR"].strip(), base),
            lab_patterns_dir=_directory("APC64_LAB_PATTERNS_DIR", values["APC64_LAB_PATTERNS_DIR"].strip(), base),
            http_host=host,
        )
