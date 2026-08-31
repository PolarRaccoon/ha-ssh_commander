"""Tests for bounded SSH transport behavior."""

from __future__ import annotations

import io
from types import ModuleType
from typing import Any

import paramiko
import pytest


class FakeChannel:
    """Minimal Paramiko channel double."""

    def __init__(
        self,
        stdout: list[bytes] | None = None,
        stderr: list[bytes] | None = None,
        return_code: int = 0,
        never_finishes: bool = False,
    ) -> None:
        self.stdout = list(stdout or [])
        self.stderr = list(stderr or [])
        self.return_code = return_code
        self.never_finishes = never_finishes
        self.closed = False
        self.command: str | None = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def exec_command(self, command: str) -> None:
        self.command = command

    def recv_ready(self) -> bool:
        return bool(self.stdout)

    def recv(self, size: int) -> bytes:
        del size
        return self.stdout.pop(0)

    def recv_stderr_ready(self) -> bool:
        return bool(self.stderr)

    def recv_stderr(self, size: int) -> bytes:
        del size
        return self.stderr.pop(0)

    def exit_status_ready(self) -> bool:
        return not self.never_finishes and not self.stdout and not self.stderr

    def recv_exit_status(self) -> int:
        return self.return_code

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, channel: FakeChannel, key: paramiko.PKey) -> None:
        self.channel = channel
        self.key = key

    def is_active(self) -> bool:
        return True

    def get_remote_server_key(self) -> paramiko.PKey:
        return self.key

    def open_session(self, timeout: int) -> FakeChannel:
        self.timeout = timeout
        return self.channel


class FakeParamikoClient:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self.closed = False

    def get_transport(self) -> FakeTransport:
        return self.transport

    def close(self) -> None:
        self.closed = True


def make_client(
    ssh_module: ModuleType,
    channel: FakeChannel,
    *,
    max_capture_bytes: int = 8192,
) -> tuple[Any, FakeParamikoClient]:
    key = paramiko.RSAKey.generate(1024)
    fake = FakeParamikoClient(FakeTransport(channel, key))
    client = ssh_module.SSHClient(
        host="server.lan",
        port=22,
        username="ha-ssh",
        auth_type="password",
        password="test",
        timeout=1,
        max_capture_bytes=max_capture_bytes,
    )
    client._connect = lambda: fake
    return client, fake


def test_sha256_fingerprint(ssh_module: ModuleType) -> None:
    key = paramiko.RSAKey.generate(1024)
    fingerprint = ssh_module.format_host_key_fingerprint(key)
    assert fingerprint.startswith("SHA256:")
    assert "=" not in fingerprint
    assert fingerprint == ssh_module.format_host_key_fingerprint(key)


def test_rsa_private_key_parsing(ssh_module: ModuleType) -> None:
    key = paramiko.RSAKey.generate(1024)
    stream = io.StringIO()
    key.write_private_key(stream)
    parsed = ssh_module._load_private_key(stream.getvalue(), None)
    assert parsed.asbytes() == key.asbytes()


def test_host_key_mismatch_is_rejected(ssh_module: ModuleType) -> None:
    key = paramiko.RSAKey.generate(1024)
    policy = ssh_module._PinnedHostKeyPolicy("SHA256:not-the-server-key")
    with pytest.raises(ssh_module.HostKeyMismatchError):
        policy.missing_host_key(object(), "server.lan", key)


def test_run_command_drains_both_streams_and_caps_output(
    ssh_module: ModuleType,
) -> None:
    channel = FakeChannel(
        stdout=[b"abcdef", b"ghij"],
        stderr=[b"warning\n"],
        return_code=7,
    )
    client, fake = make_client(ssh_module, channel, max_capture_bytes=5)

    result = client.run_command("example")

    assert channel.command == "example"
    assert result.stdout == "abcde"
    assert result.stderr == "warni"
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert result.return_code == 7
    assert result.success is False
    assert channel.closed is True
    assert fake.closed is True


def test_run_command_timeout_closes_resources(
    ssh_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = FakeChannel(never_finishes=True)
    client, fake = make_client(ssh_module, channel)
    ticks = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(ssh_module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(ssh_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(ssh_module.CommandTimeoutError):
        client.run_command("sleep forever")

    assert channel.closed is True
    assert fake.closed is True
