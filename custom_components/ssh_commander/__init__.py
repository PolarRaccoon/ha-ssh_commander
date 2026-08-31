"""SSH Commander — run allow-listed SSH commands from Home Assistant."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_COMMAND_ID,
    ATTR_DURATION,
    ATTR_ENTRY_ID,
    ATTR_RETURN_CODE,
    ATTR_STDERR,
    ATTR_STDERR_TRUNCATED,
    ATTR_STDOUT,
    ATTR_STDOUT_TRUNCATED,
    ATTR_SUCCESS,
    CONF_COMMANDS,
    CONF_MACHINES,
    DOMAIN,
    SERVICE_RUN_COMMAND,
)
from .runtime import (
    CommandAlreadyRunningError,
    CommandNotFoundError,
    SSHCommanderRuntimeData,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON]
CONFIG_ENTRY_VERSION = 2


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up SSH Commander and its service action."""
    del config
    hass.data.setdefault(DOMAIN, {})

    async def async_handle_run_command(
        call: ServiceCall,
    ) -> ServiceResponse | None:
        command_id: str = call.data[ATTR_COMMAND_ID]
        requested_entry_id: str | None = call.data.get(ATTR_ENTRY_ID)
        runtime = _resolve_runtime(hass, requested_entry_id, command_id)

        try:
            result = await runtime.async_run_command(command_id)
        except CommandAlreadyRunningError as err:
            raise ServiceValidationError(
                f"Command {command_id!r} is already running"
            ) from err
        except (CommandNotFoundError, KeyError) as err:
            raise ServiceValidationError(
                f"Configured command {command_id!r} was not found"
            ) from err
        except Exception as err:
            raise HomeAssistantError(f"SSH command failed: {err}") from err

        response: ServiceResponse = {
            ATTR_SUCCESS: result.success,
            ATTR_RETURN_CODE: result.return_code,
            ATTR_STDOUT: result.stdout,
            ATTR_STDERR: result.stderr,
            ATTR_DURATION: result.duration,
            ATTR_STDOUT_TRUNCATED: result.stdout_truncated,
            ATTR_STDERR_TRUNCATED: result.stderr_truncated,
        }
        return response if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_COMMAND,
        async_handle_run_command,
        schema=vol.Schema(
            {
                vol.Required(ATTR_COMMAND_ID): cv.string,
                vol.Optional(ATTR_ENTRY_ID): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


def _resolve_runtime(
    hass: HomeAssistant,
    entry_id: str | None,
    command_id: str,
) -> SSHCommanderRuntimeData:
    """Resolve a loaded runtime, optionally constrained to one entry."""
    runtimes: dict[str, SSHCommanderRuntimeData] = hass.data.get(DOMAIN, {})

    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                f"SSH Commander config entry {entry_id!r} was not found"
            )
        if entry.state is not ConfigEntryState.LOADED or entry_id not in runtimes:
            raise ServiceValidationError(
                f"SSH Commander config entry {entry_id!r} is not loaded"
            )
        runtime = runtimes[entry_id]
        if command_id not in runtime.commands:
            raise ServiceValidationError(
                f"Configured command {command_id!r} was not found in entry {entry_id!r}"
            )
        return runtime

    matches = [
        runtime for runtime in runtimes.values() if command_id in runtime.commands
    ]
    if not matches:
        raise ServiceValidationError(
            f"Configured command {command_id!r} was not found in any loaded entry"
        )
    if len(matches) > 1:
        raise ServiceValidationError(
            f"Command {command_id!r} exists in more than one entry; provide entry_id"
        )
    return matches[0]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one SSH Commander config entry."""
    runtime = SSHCommanderRuntimeData(hass=hass, data=deepcopy(dict(entry.data)))
    entry.runtime_data = runtime
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one SSH Commander config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate v1 entries and recover configuration saved by the old options flow."""
    if entry.version > CONFIG_ENTRY_VERSION:
        _LOGGER.error(
            "Cannot downgrade SSH Commander entry %s from version %s",
            entry.entry_id,
            entry.version,
        )
        return False

    if entry.version == CONFIG_ENTRY_VERSION:
        return True

    data: dict[str, Any]
    if CONF_MACHINES in entry.options or CONF_COMMANDS in entry.options:
        data = deepcopy(dict(entry.options))
        _LOGGER.info(
            "Recovered SSH Commander configuration from the legacy options flow"
        )
    else:
        data = deepcopy(dict(entry.data))

    data.setdefault(CONF_MACHINES, [])
    data.setdefault(CONF_COMMANDS, [])
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options={},
        version=CONFIG_ENTRY_VERSION,
    )
    return True
