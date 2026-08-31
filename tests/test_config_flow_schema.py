"""Regression tests for Home Assistant config-flow serialization."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import voluptuous_serialize
from homeassistant.helpers import config_validation as cv

from custom_components.ssh_commander.config_flow import SSHCommanderConfigFlow
from custom_components.ssh_commander.const import (
    AUTH_TYPE_KEY,
    AUTH_TYPE_PASSWORD,
    CONF_AUTH_TYPE,
    CONF_COMMAND,
    CONF_COMMAND_ID,
    CONF_COMMAND_NAME,
    CONF_HOST,
    CONF_HOST_KEY_FINGERPRINT,
    CONF_MACHINE_ID,
    CONF_MACHINE_NAME,
    CONF_MACHINE_REF,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TIMEOUT,
    CONF_USERNAME,
)


def _serialize_flow_schema(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize a flow schema exactly as Home Assistant's HTTP view does."""
    return voluptuous_serialize.convert(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )


def test_add_flow_schema_is_serializable() -> None:
    """The first Add Integration form must not trigger an HTTP 500."""
    flow = SSHCommanderConfigFlow()
    flow.flow_id = "test-user"
    flow.handler = "ssh_commander"
    flow.context = {"source": "user"}

    result = asyncio.run(flow.async_step_user())

    assert result["step_id"] == "add_machine"
    assert _serialize_flow_schema(result)


def test_reconfigure_menu_schema_is_serializable() -> None:
    """The initial Reconfigure menu must not trigger an HTTP 500."""
    entry = SimpleNamespace(
        entry_id="entry",
        title="SSH Commander",
        options={},
        data={
            "machines": [{"machine_id": "m1", "machine_name": "Server"}],
            "commands": [
                {
                    "command_id": "c1",
                    "command_name": "Uptime",
                    "machine_id": "m1",
                    "command": "uptime",
                }
            ],
        },
    )
    flow = SSHCommanderConfigFlow()
    flow.flow_id = "test-reconfigure"
    flow.handler = "ssh_commander"
    flow.context = {"source": "reconfigure", "entry_id": "entry"}
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_known_entry=lambda _entry_id: entry)
    )

    result = asyncio.run(flow.async_step_reconfigure())

    assert result["step_id"] == "manage"
    assert _serialize_flow_schema(result)


def test_every_text_entry_schema_is_serializable() -> None:
    """Machine, credential, and command forms must all serialize."""
    machine = {
        CONF_MACHINE_ID: "m1",
        CONF_MACHINE_NAME: "Server",
        CONF_HOST: "server.lan",
        CONF_PORT: 22,
        CONF_USERNAME: "ha-ssh",
        CONF_AUTH_TYPE: AUTH_TYPE_PASSWORD,
        CONF_PASSWORD: "secret",
        CONF_TIMEOUT: 30,
        CONF_HOST_KEY_FINGERPRINT: "SHA256:test",
    }
    command = {
        CONF_COMMAND_ID: "c1",
        CONF_COMMAND_NAME: "Uptime",
        CONF_MACHINE_REF: "m1",
        CONF_COMMAND: "uptime",
    }
    flow = SSHCommanderConfigFlow()
    flow._machines = [machine]

    schemas = (
        flow._machine_schema(),
        flow._machine_schema(machine),
        flow._auth_schema(AUTH_TYPE_PASSWORD),
        flow._auth_schema(AUTH_TYPE_KEY),
        flow._command_schema(),
        flow._command_schema(command),
    )

    for schema in schemas:
        assert voluptuous_serialize.convert(
            schema, custom_serializer=cv.custom_serializer
        )
