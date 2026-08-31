"""Privacy-safe diagnostics for SSH Commander."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AUTH_TYPE,
    CONF_COMMAND_ID,
    CONF_COMMANDS,
    CONF_HOST_KEY_FINGERPRINT,
    CONF_MACHINE_ID,
    CONF_MACHINE_REF,
    CONF_MACHINES,
    CONF_PORT,
    CONF_TIMEOUT,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return metadata without credentials or shell command text."""
    del hass
    data = entry.data
    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
        },
        "machine_count": len(data.get(CONF_MACHINES, [])),
        "command_count": len(data.get(CONF_COMMANDS, [])),
        "machines": [
            {
                CONF_MACHINE_ID: machine.get(CONF_MACHINE_ID),
                CONF_PORT: machine.get(CONF_PORT),
                CONF_AUTH_TYPE: machine.get(CONF_AUTH_TYPE),
                CONF_TIMEOUT: machine.get(CONF_TIMEOUT),
                "host_key_pinned": bool(machine.get(CONF_HOST_KEY_FINGERPRINT)),
            }
            for machine in data.get(CONF_MACHINES, [])
        ],
        "commands": [
            {
                CONF_COMMAND_ID: command.get(CONF_COMMAND_ID),
                CONF_MACHINE_REF: command.get(CONF_MACHINE_REF),
            }
            for command in data.get(CONF_COMMANDS, [])
        ],
    }
