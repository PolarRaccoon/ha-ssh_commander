"""Runtime command lookup and execution for SSH Commander."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_AUTH_TYPE,
    CONF_COMMAND,
    CONF_COMMAND_ID,
    CONF_COMMANDS,
    CONF_HOST,
    CONF_HOST_KEY_FINGERPRINT,
    CONF_MACHINE_ID,
    CONF_MACHINE_REF,
    CONF_MACHINES,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_PRIVATE_KEY,
    CONF_PRIVATE_KEY_PASSPHRASE,
    CONF_TIMEOUT,
    CONF_USERNAME,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
)
from .ssh_client import CommandResult, SSHClient


class CommandNotFoundError(KeyError):
    """Raised when a configured command cannot be found."""


class MachineNotFoundError(KeyError):
    """Raised when a command references a missing machine."""


class CommandAlreadyRunningError(RuntimeError):
    """Raised when the same command is triggered twice concurrently."""


@dataclass(slots=True)
class SSHCommanderRuntimeData:
    """Validated, indexed state for one SSH Commander config entry."""

    hass: HomeAssistant
    data: dict[str, Any]
    machines: dict[str, dict[str, Any]] = field(init=False)
    commands: dict[str, dict[str, Any]] = field(init=False)
    _locks: dict[str, asyncio.Lock] = field(init=False)

    def __post_init__(self) -> None:
        self.machines = {
            machine[CONF_MACHINE_ID]: machine
            for machine in self.data.get(CONF_MACHINES, [])
        }
        self.commands = {
            command[CONF_COMMAND_ID]: command
            for command in self.data.get(CONF_COMMANDS, [])
        }
        self._locks = {command_id: asyncio.Lock() for command_id in self.commands}

    def command_and_machine(
        self, command_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Resolve a command and its target machine."""
        if (command := self.commands.get(command_id)) is None:
            raise CommandNotFoundError(command_id)

        machine_id = command[CONF_MACHINE_REF]
        if (machine := self.machines.get(machine_id)) is None:
            raise MachineNotFoundError(machine_id)
        return command, machine

    async def async_run_command(self, command_id: str) -> CommandResult:
        """Execute one configured command without blocking Home Assistant."""
        command, machine = self.command_and_machine(command_id)
        lock = self._locks[command_id]
        if lock.locked():
            raise CommandAlreadyRunningError(command_id)

        client = SSHClient(
            host=machine[CONF_HOST],
            port=machine.get(CONF_PORT, DEFAULT_PORT),
            username=machine[CONF_USERNAME],
            auth_type=machine[CONF_AUTH_TYPE],
            password=machine.get(CONF_PASSWORD),
            private_key=machine.get(CONF_PRIVATE_KEY),
            private_key_passphrase=machine.get(CONF_PRIVATE_KEY_PASSPHRASE),
            timeout=machine.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            host_key_fingerprint=machine.get(CONF_HOST_KEY_FINGERPRINT),
        )

        async with lock:
            return await self.hass.async_add_executor_job(
                client.run_command, command[CONF_COMMAND]
            )
