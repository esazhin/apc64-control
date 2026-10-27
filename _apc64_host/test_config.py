from pathlib import Path

import pytest

from _apc64_host.config import DEFAULTS, LOCAL_CONFIG, Config, ConfigError, read_local_config

ROOT = Path(__file__).resolve().parent.parent


def test_without_config_local_the_defaults_apply(tmp_path):
    config = Config.load({"PATH": "/usr/bin"}, tmp_path / "config.local")
    assert config.http_port == 5058 and config.auto_accept is False and config.port_stem == "APC64"
    assert config.http_host == "::"
    assert config.layouts_dir == tmp_path / "layouts"
    assert config.state_dir == Path("~/.local/state/apc64-host").expanduser()
    assert config.allowed_networks.allows("192.168.1.23") and config.allowed_networks.allows("fd00::23")
    assert not config.allowed_networks.allows("203.0.113.5")


def test_config_local_overrides_the_defaults_and_the_environment_overrides_both(tmp_path):
    local = tmp_path / "config.local"
    local.write_text("# my machine\nAPC64_HTTP_PORT=6000\nAPC64_AUTO_ACCEPT=0\nAPC64_LAYOUTS_DIR=/srv/layouts\n")
    config = Config.load({"APC64_AUTO_ACCEPT": "1"}, local)
    assert config.http_port == 6000 and config.auto_accept is True
    assert config.layouts_dir == Path("/srv/layouts")
    assert Config.load({"APC64_HTTP_PORT": "7000"}, local).http_port == 7000


@pytest.mark.parametrize("key, value", [
    ("APC64_HTTP_PORT", "abc"), ("APC64_HTTP_PORT", "70000"), ("APC64_AUTO_ACCEPT", "maybe"),
    ("APC64_ALLOWED_NETWORKS", "192.168.0.0/16, home"), ("APC64_PORT_STEM", " "), ("APC64_STATE_DIR", ""),
    ("APC64_HTTP_HOST", " "),
])
def test_a_bad_value_raises_a_config_error_naming_its_key(tmp_path, key, value):
    with pytest.raises(ConfigError) as raised:
        Config.load({key: value}, tmp_path / "config.local")
    assert raised.value.key == key


def test_the_allowed_networks_can_be_widened(tmp_path):
    config = Config.load({"APC64_ALLOWED_NETWORKS": "192.168.0.0/16 100.64.0.0/10"}, tmp_path / "x")
    assert config.allowed_networks.allows("100.64.1.2") and not config.allowed_networks.allows("127.0.0.1")


def test_a_local_config_file_is_read_as_key_value_lines(tmp_path):
    path = tmp_path / "config.local"
    path.write_text('# comment\n\nAPC64_HTTP_PORT=9001\nAPC64_PORT_STEM="APC64"\n not a line\n')
    assert read_local_config(path) == {"APC64_HTTP_PORT": "9001", "APC64_PORT_STEM": "APC64"}
    assert read_local_config(tmp_path / "missing") == {} and read_local_config(None) == {}


def test_the_example_file_documents_every_key_with_its_default():
    example = read_local_config(ROOT / "config.local.example")
    assert set(example) == set(DEFAULTS)
    assert example["APC64_HTTP_PORT"] == "5058" and example["APC64_AUTO_ACCEPT"] == "0"
    assert Config.load({}, ROOT / "config.local.example").http_port == 5058
    assert LOCAL_CONFIG.name == "config.local"
