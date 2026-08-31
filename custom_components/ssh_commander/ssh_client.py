"""Synchronous Paramiko wrapper used from Home Assistant's executor."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import time
from dataclasses import dataclass
from typing import Any

import paramiko

from .const import (
    AUTH_TYPE_KEY,
    AUTH_TYPE_PASSWORD,
    DEFAULT_TIMEOUT,
    MAX_CAPTURE_BYTES,
)


class SSHCommanderError(Exception):
    """Base error for SSH Commander."""


class InvalidPrivateKeyError(SSHCommanderError):
    """Raised when a supplied private key cannot be parsed."""


class HostKeyMismatchError(SSHCommanderError):
    """Raised when the server no longer presents the pinned host key."""


class CommandTimeoutError(SSHCommanderError):
    """Raised when a remote command exceeds its configured timeout."""


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """Information learned while testing an SSH connection."""

    host_key_fingerprint: str
    host_key_algorithm: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of a remote command execution."""

    stdout: str
    stderr: str
    return_code: int
    duration: float
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    @property
    def success(self) -> bool:
        """Return whether the command exited successfully."""
        return self.return_code == 0


def format_host_key_fingerprint(key: paramiko.PKey) -> str:
    """Return an OpenSSH-style SHA256 host-key fingerprint."""
    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


def _load_private_key(private_key: str, passphrase: str | None) -> paramiko.PKey:
    """Parse RSA, ECDSA, or Ed25519 private key text."""
    parse_errors: list[Exception] = []
    password = passphrase or None

    for key_type in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return key_type.from_private_key(
                io.StringIO(private_key), password=password
            )
        except (paramiko.PasswordRequiredException, paramiko.SSHException) as err:
            parse_errors.append(err)

    detail = str(parse_errors[-1]) if parse_errors else "unknown key format"
    raise InvalidPrivateKeyError(
        "Unsupported or invalid private key (RSA, ECDSA, and Ed25519 are supported): "
        f"{detail}"
    )


class _PinnedHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Accept an unpinned key for enrollment, otherwise enforce its fingerprint."""

    def __init__(self, expected_fingerprint: str | None) -> None:
        self._expected_fingerprint = expected_fingerprint

    def missing_host_key(
        self,
        client: paramiko.SSHClient,
        hostname: str,
        key: paramiko.PKey,
    ) -> None:
        del client
        actual = format_host_key_fingerprint(key)
        expected = self._expected_fingerprint
        if expected and not hmac.compare_digest(actual, expected):
            raise HostKeyMismatchError(
                f"SSH host key for {hostname} changed: "
                f"expected {expected}, got {actual}"
            )


class SSHClient:
    """Connect for one operation, then close the SSH session immediately."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        auth_type: str,
        password: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        host_key_fingerprint: str | None = None,
        max_capture_bytes: int = MAX_CAPTURE_BYTES,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._auth_type = auth_type
        self._password = password
        self._private_key = private_key
        self._private_key_passphrase = private_key_passphrase
        self._timeout = timeout
        self._host_key_fingerprint = host_key_fingerprint or None
        self._max_capture_bytes = max_capture_bytes
        self._connected_fingerprint: str | None = None
        self._connected_algorithm: str | None = None

    def _connect(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(
            _PinnedHostKeyPolicy(self._host_key_fingerprint)
        )

        connect_kwargs: dict[str, Any] = {
            "hostname": self._host,
            "port": self._port,
            "username": self._username,
            "timeout": self._timeout,
            "banner_timeout": self._timeout,
            "auth_timeout": self._timeout,
            "channel_timeout": self._timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }

        if self._auth_type == AUTH_TYPE_PASSWORD:
            connect_kwargs["password"] = self._password
        elif self._auth_type == AUTH_TYPE_KEY:
            if not self._private_key:
                raise InvalidPrivateKeyError(
                    "A private key is required for key authentication"
                )
            connect_kwargs["pkey"] = _load_private_key(
                self._private_key, self._private_key_passphrase
            )
        else:
            raise SSHCommanderError(
                f"Unsupported authentication type: {self._auth_type}"
            )

        try:
            client.connect(**connect_kwargs)
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise SSHCommanderError("SSH transport did not become active")

            server_key = transport.get_remote_server_key()
            actual = format_host_key_fingerprint(server_key)
            if self._host_key_fingerprint and not hmac.compare_digest(
                actual, self._host_key_fingerprint
            ):
                raise HostKeyMismatchError(
                    f"SSH host key for {self._host} changed: expected "
                    f"{self._host_key_fingerprint}, got {actual}"
                )

            self._connected_fingerprint = actual
            self._connected_algorithm = server_key.get_name()
            return client
        except Exception:
            client.close()
            raise

    def test_connection(self) -> ConnectionInfo:
        """Authenticate, capture the server host key, and disconnect."""
        client = self._connect()
        try:
            if not self._connected_fingerprint or not self._connected_algorithm:
                raise SSHCommanderError("Could not read the SSH server host key")
            return ConnectionInfo(
                host_key_fingerprint=self._connected_fingerprint,
                host_key_algorithm=self._connected_algorithm,
            )
        finally:
            client.close()

    def run_command(self, command: str) -> CommandResult:
        """Run one command with bounded runtime and captured output."""
        started = time.monotonic()
        client = self._connect()
        channel: paramiko.Channel | None = None

        try:
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise SSHCommanderError("SSH transport is not active")

            channel = transport.open_session(timeout=self._timeout)
            channel.settimeout(min(float(self._timeout), 1.0))
            channel.exec_command(command)

            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []
            stdout_size = 0
            stderr_size = 0
            stdout_truncated = False
            stderr_truncated = False
            deadline = time.monotonic() + self._timeout

            while True:
                received = False

                if channel.recv_ready():
                    data = channel.recv(32768)
                    received = True
                    remaining = self._max_capture_bytes - stdout_size
                    if remaining > 0:
                        kept = data[:remaining]
                        stdout_chunks.append(kept)
                        stdout_size += len(kept)
                    stdout_truncated |= len(data) > max(remaining, 0)

                if channel.recv_stderr_ready():
                    data = channel.recv_stderr(32768)
                    received = True
                    remaining = self._max_capture_bytes - stderr_size
                    if remaining > 0:
                        kept = data[:remaining]
                        stderr_chunks.append(kept)
                        stderr_size += len(kept)
                    stderr_truncated |= len(data) > max(remaining, 0)

                if (
                    channel.exit_status_ready()
                    and not channel.recv_ready()
                    and not channel.recv_stderr_ready()
                ):
                    break

                if time.monotonic() >= deadline:
                    raise CommandTimeoutError(
                        f"SSH command on {self._host} exceeded {self._timeout} seconds"
                    )

                if not received:
                    time.sleep(0.02)

            return_code = channel.recv_exit_status()
            duration = round(time.monotonic() - started, 3)
            return CommandResult(
                stdout=b"".join(stdout_chunks)
                .decode("utf-8", errors="replace")
                .rstrip("\r\n"),
                stderr=b"".join(stderr_chunks)
                .decode("utf-8", errors="replace")
                .rstrip("\r\n"),
                return_code=return_code,
                duration=duration,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )
        finally:
            if channel is not None:
                channel.close()
            client.close()
