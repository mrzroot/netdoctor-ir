import pytest

from netdoctor.models import Resolver, ResolverKind
from netdoctor.osapply import current_os, dns_instructions, render_script

R = Resolver("shecan", "Shecan", ResolverKind.ANTI_SANCTION, ("178.22.122.100", "185.51.200.2"))


def test_current_os(monkeypatch):
    for system, expected in (("Darwin", "macos"), ("Windows", "windows"), ("Linux", "linux")):
        monkeypatch.setattr("platform.system", lambda s=system: s)
        assert current_os() == expected


def test_linux_instructions():
    ins = dns_instructions(R, "linux", "wlan0")
    assert ins[0].commands[0] == "sudo resolvectl dns wlan0 178.22.122.100 185.51.200.2"
    assert "nmcli" in ins[1].commands[0]
    assert ins[0].revert == ["sudo resolvectl revert wlan0"]


def test_macos_and_windows():
    mac = dns_instructions(R, "macos")
    assert 'networksetup -setdnsservers "Wi-Fi" 178.22.122.100 185.51.200.2' in mac[0].commands
    win = dns_instructions(R, "windows", "Ethernet")
    assert '-ServerAddresses ("178.22.122.100","185.51.200.2")' in win[0].commands[0]
    assert "Ethernet" in win[0].revert[0]


@pytest.mark.parametrize("os_name", ["linux", "macos", "windows"])
def test_render_script(os_name):
    text = render_script(R, dns_instructions(R, os_name), os_name)
    assert "never runs these commands" in text
    assert text.startswith("#!/bin/sh") == (os_name != "windows")
    if os_name == "linux":
        assert "# --- Alternative:" in text and "# nmcli" in text
