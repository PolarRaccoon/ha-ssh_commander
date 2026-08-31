"""Button platform: one pressable entity per configured SSH command."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_COMMAND_ID,
    ATTR_DURATION,
    ATTR_LAST_RUN,
    ATTR_MACHINE_ID,
    ATTR_RETURN_CODE,
    ATTR_STDERR,
    ATTR_STDERR_TRUNCATED,
    ATTR_STDOUT,
    ATTR_STDOUT_TRUNCATED,
    ATTR_SUCCESS,
    CONF_COMMAND_ID,
    CONF_COMMAND_NAME,
    CONF_HOST,
    CONF_MACHINE_ID,
    CONF_MACHINE_NAME,
    DOMAIN,
)
from .runtime import SSHCommanderRuntimeData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SSH Commander command buttons."""
    runtime: SSHCommanderRuntimeData = config_entry.runtime_data
    entities: list[SSHCommandButton] = []
    provided_machine_ids: set[str] = set()

    for command in runtime.commands.values():
        command_id = command[CONF_COMMAND_ID]
        try:
            _resolved_command, machine = runtime.command_and_machine(command_id)
        except KeyError:
            _LOGGER.warning(
                "Command %r references an unknown machine and was skipped",
                command.get(CONF_COMMAND_NAME, command_id),
            )
            continue
        provided_machine_ids.add(machine[CONF_MACHINE_ID])
        entities.append(SSHCommandButton(config_entry, runtime, machine, command))

    expected_unique_ids = {entity.unique_id for entity in entities}
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    ):
        if (
            registry_entry.platform == DOMAIN
            and registry_entry.unique_id not in expected_unique_ids
        ):
            entity_registry.async_remove(registry_entry.entity_id)

    expected_device_identifiers = {
        (
            DOMAIN,
            f"{config_entry.entry_id}_{machine_id}",
        )
        for machine_id in provided_machine_ids
    }
    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(
        device_registry, config_entry.entry_id
    ):
        if not device_entry.identifiers.intersection(expected_device_identifiers):
            device_registry.async_remove_device(device_entry.id)

    async_add_entities(entities)


class SSHCommandButton(ButtonEntity):
    """Run one fixed SSH command on one configured machine."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:console-network"

    def __init__(
        self,
        config_entry: ConfigEntry,
        runtime: SSHCommanderRuntimeData,
        machine: dict[str, Any],
        command: dict[str, Any],
    ) -> None:
        self._config_entry = config_entry
        self._runtime = runtime
        self._machine = machine
        self._command = command

        machine_id = machine[CONF_MACHINE_ID]
        command_id = command[CONF_COMMAND_ID]
        self._attr_unique_id = f"{config_entry.entry_id}_{machine_id}_{command_id}"
        self._attr_name = command[CONF_COMMAND_NAME]
        self._attr_available = True
        self._extra_attrs: dict[str, Any] = {
            ATTR_COMMAND_ID: command_id,
            ATTR_MACHINE_ID: machine_id,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Group commands for the same SSH endpoint under one device."""
        machine = self._machine
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{self._config_entry.entry_id}_{machine[CONF_MACHINE_ID]}",
                )
            },
            name=machine[CONF_MACHINE_NAME],
            manufacturer="SSH Commander",
            model=f"SSH endpoint ({machine[CONF_HOST]})",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the most recent bounded command result."""
        return self._extra_attrs

    async def async_press(self) -> None:
        """Execute the configured SSH command."""
        command_id = self._command[CONF_COMMAND_ID]
        command_name = self._command[CONF_COMMAND_NAME]
        host = self._machine[CONF_HOST]
        self._attr_available = False
        self.async_write_ha_state()

        try:
            result = await self._runtime.async_run_command(command_id)
        except Exception as err:
            _LOGGER.warning("SSH command %r on %s failed: %s", command_name, host, err)
            self._extra_attrs.update(
                {
                    ATTR_STDOUT: "",
                    ATTR_STDERR: str(err),
                    ATTR_RETURN_CODE: -1,
                    ATTR_SUCCESS: False,
                    ATTR_DURATION: None,
                    ATTR_STDOUT_TRUNCATED: False,
                    ATTR_STDERR_TRUNCATED: False,
                    ATTR_LAST_RUN: dt_util.now().isoformat(),
                }
            )
            raise HomeAssistantError(
                f"SSH command {command_name!r} on {host} failed: {err}"
            ) from err
        else:
            _LOGGER.info(
                "SSH command %r on %s returned %d in %.3fs",
                command_name,
                host,
                result.return_code,
                result.duration,
            )
            self._extra_attrs.update(
                {
                    ATTR_STDOUT: result.stdout,
                    ATTR_STDERR: result.stderr,
                    ATTR_RETURN_CODE: result.return_code,
                    ATTR_SUCCESS: result.success,
                    ATTR_DURATION: result.duration,
                    ATTR_STDOUT_TRUNCATED: result.stdout_truncated,
                    ATTR_STDERR_TRUNCATED: result.stderr_truncated,
                    ATTR_LAST_RUN: dt_util.now().isoformat(),
                }
            )
        finally:
            self._attr_available = True
            self.async_write_ha_state()
