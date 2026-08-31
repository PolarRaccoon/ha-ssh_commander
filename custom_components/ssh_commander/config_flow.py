"""Config and reconfigure flows for SSH Commander."""

from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from typing import Any

import paramiko
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    AUTH_TYPE_KEY,
    AUTH_TYPE_PASSWORD,
    CONF_AUTH_TYPE,
    CONF_COMMAND,
    CONF_COMMAND_ID,
    CONF_COMMAND_NAME,
    CONF_COMMANDS,
    CONF_CONFIRM,
    CONF_HOST,
    CONF_HOST_KEY_FINGERPRINT,
    CONF_MACHINE_ID,
    CONF_MACHINE_NAME,
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
    DOMAIN,
    MAX_TIMEOUT,
    MIN_TIMEOUT,
)
from .ssh_client import InvalidPrivateKeyError, SSHClient, SSHCommanderError

_LOGGER = logging.getLogger(__name__)

_TEXT = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
_MULTILINE_TEXT = TextSelector(
    TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
)
_PASSWORD = TextSelector(
    TextSelectorConfig(
        type=TextSelectorType.PASSWORD,
        autocomplete="current-password",
    )
)
_PRIVATE_KEY = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, multiline=True)
)


def _clean_string(value: Any) -> str:
    """Trim a non-empty form value."""
    cleaned = str(value).strip()
    if not cleaned:
        raise vol.Invalid("value must not be empty")
    return cleaned


def _clean_input_fields(
    user_input: dict[str, Any], fields: tuple[str, ...]
) -> tuple[dict[str, str], dict[str, str]]:
    """Clean text fields without adding non-serializable schema validators."""
    cleaned: dict[str, str] = {}
    errors: dict[str, str] = {}
    for field in fields:
        try:
            cleaned[field] = _clean_string(user_input[field])
        except vol.Invalid:
            errors[field] = "empty_value"
    return cleaned, errors


def _suggested(value: Any) -> dict[str, Any]:
    """Create a Home Assistant suggested-value descriptor."""
    return {"suggested_value": value}


def _entry_title(machines: list[dict[str, Any]]) -> str:
    """Build a compact config-entry title."""
    title = ", ".join(machine[CONF_MACHINE_NAME] for machine in machines[:3])
    if len(machines) > 3:
        title += f" +{len(machines) - 3}"
    return title or "SSH Commander"


class SSHCommanderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create and reconfigure an SSH Commander entry."""

    VERSION = 2

    def __init__(self) -> None:
        self._machines: list[dict[str, Any]] = []
        self._commands: list[dict[str, Any]] = []
        self._current_machine: dict[str, Any] = {}
        self._original_machine: dict[str, Any] | None = None
        self._machine_operation = "add"
        self._host_key_algorithm = ""
        self._selected_command_id: str | None = None
        self._reconfigure_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start a new entry with its first machine."""
        del user_input
        return await self.async_step_add_machine()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Load existing data into the full configuration manager."""
        del user_input
        self._reconfigure_entry = self._get_reconfigure_entry()
        source = (
            self._reconfigure_entry.options
            if CONF_MACHINES in self._reconfigure_entry.options
            else self._reconfigure_entry.data
        )
        self._machines = deepcopy(list(source.get(CONF_MACHINES, [])))
        self._commands = deepcopy(list(source.get(CONF_COMMANDS, [])))
        return await self.async_step_manage()

    async def async_step_manage(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show configuration actions."""
        del user_input
        menu_options = ["add_machine"]
        if self._machines:
            menu_options.extend(["add_command", "edit_machine", "remove_machine"])
        if self._commands:
            menu_options.extend(["edit_command", "remove_command", "finish"])

        return self.async_show_menu(
            step_id="manage",
            menu_options=menu_options,
            description_placeholders={
                "machines": str(len(self._machines)),
                "commands": str(len(self._commands)),
            },
        )

    async def async_step_add_machine(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect connection details for a new SSH endpoint."""
        errors: dict[str, str] = {}
        if user_input is not None:
            cleaned, errors = _clean_input_fields(
                user_input,
                (CONF_MACHINE_NAME, CONF_HOST, CONF_USERNAME),
            )
            name = cleaned.get(CONF_MACHINE_NAME, "")
            if not errors and self._machine_name_exists(name):
                errors[CONF_MACHINE_NAME] = "duplicate_machine_name"
            elif not errors:
                self._machine_operation = "add"
                self._original_machine = None
                self._current_machine = self._machine_from_input(
                    {**user_input, **cleaned}, str(uuid.uuid4())
                )
                return await self.async_step_machine_auth()

        return self.async_show_form(
            step_id="add_machine",
            data_schema=self._machine_schema(),
            errors=errors,
        )

    async def async_step_edit_machine(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a machine to edit."""
        if user_input is not None:
            machine_id = user_input[CONF_MACHINE_ID]
            self._original_machine = deepcopy(self._machine_by_id(machine_id))
            return await self.async_step_edit_machine_details()

        return self.async_show_form(
            step_id="edit_machine",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MACHINE_ID): vol.In(
                        {
                            machine[CONF_MACHINE_ID]: machine[CONF_MACHINE_NAME]
                            for machine in self._machines
                        }
                    )
                }
            ),
        )

    async def async_step_edit_machine_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit non-secret machine connection fields."""
        assert self._original_machine is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            cleaned, errors = _clean_input_fields(
                user_input,
                (CONF_MACHINE_NAME, CONF_HOST, CONF_USERNAME),
            )
            name = cleaned.get(CONF_MACHINE_NAME, "")
            machine_id = self._original_machine[CONF_MACHINE_ID]
            if not errors and self._machine_name_exists(name, exclude_id=machine_id):
                errors[CONF_MACHINE_NAME] = "duplicate_machine_name"
            elif not errors:
                self._machine_operation = "edit"
                self._current_machine = self._machine_from_input(
                    {**user_input, **cleaned}, machine_id
                )
                return await self.async_step_machine_auth()

        return self.async_show_form(
            step_id="edit_machine_details",
            data_schema=self._machine_schema(self._original_machine),
            errors=errors,
        )

    async def async_step_machine_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials and test the SSH connection."""
        errors: dict[str, str] = {}
        auth_type = self._current_machine[CONF_AUTH_TYPE]

        if user_input is not None:
            try:
                self._merge_credentials(user_input)
            except vol.Invalid:
                errors["base"] = "credentials_required"
            else:
                try:
                    client = self._client_for_machine(
                        self._current_machine, verify_host_key=False
                    )
                    info = await self.hass.async_add_executor_job(
                        client.test_connection
                    )
                except paramiko.AuthenticationException:
                    errors["base"] = "invalid_auth"
                except InvalidPrivateKeyError:
                    errors["base"] = "invalid_private_key"
                except (
                    TimeoutError,
                    SSHCommanderError,
                    paramiko.SSHException,
                    OSError,
                ) as err:
                    _LOGGER.warning(
                        "SSH connection test to %s failed: %s",
                        self._current_machine[CONF_HOST],
                        err,
                    )
                    errors["base"] = "cannot_connect"
                else:
                    self._current_machine[CONF_HOST_KEY_FINGERPRINT] = (
                        info.host_key_fingerprint
                    )
                    self._host_key_algorithm = info.host_key_algorithm
                    return await self.async_step_confirm_host_key()

        return self.async_show_form(
            step_id="machine_auth",
            data_schema=self._auth_schema(auth_type),
            errors=errors,
            description_placeholders={
                "machine_name": self._current_machine[CONF_MACHINE_NAME],
                "host": self._current_machine[CONF_HOST],
            },
        )

    async def async_step_confirm_host_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Require explicit trust of the server's presented host key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_CONFIRM]:
                self._commit_current_machine()
                return await self.async_step_manage()
            errors["base"] = "host_key_not_confirmed"

        return self.async_show_form(
            step_id="confirm_host_key",
            data_schema=vol.Schema({vol.Required(CONF_CONFIRM, default=False): bool}),
            errors=errors,
            description_placeholders={
                "machine_name": self._current_machine[CONF_MACHINE_NAME],
                "host": self._current_machine[CONF_HOST],
                "algorithm": self._host_key_algorithm,
                "fingerprint": self._current_machine[CONF_HOST_KEY_FINGERPRINT],
            },
        )

    async def async_step_remove_machine(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a machine and every command that targets it."""
        if user_input is not None:
            machine_id = user_input[CONF_MACHINE_ID]
            self._machines = [
                machine
                for machine in self._machines
                if machine[CONF_MACHINE_ID] != machine_id
            ]
            self._commands = [
                command
                for command in self._commands
                if command[CONF_MACHINE_REF] != machine_id
            ]
            return await self.async_step_manage()

        return self.async_show_form(
            step_id="remove_machine",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MACHINE_ID): vol.In(
                        {
                            machine[CONF_MACHINE_ID]: machine[CONF_MACHINE_NAME]
                            for machine in self._machines
                        }
                    )
                }
            ),
        )

    async def async_step_add_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add one allow-listed command."""
        errors: dict[str, str] = {}
        if user_input is not None:
            cleaned, errors = _clean_input_fields(
                user_input,
                (CONF_COMMAND_NAME, CONF_COMMAND),
            )
            name = cleaned.get(CONF_COMMAND_NAME, "")
            machine_id = user_input[CONF_MACHINE_REF]
            if not errors and self._command_name_exists(name, machine_id):
                errors[CONF_COMMAND_NAME] = "duplicate_command_name"
            elif not errors:
                self._commands.append(
                    {
                        CONF_COMMAND_ID: str(uuid.uuid4()),
                        CONF_COMMAND_NAME: name,
                        CONF_MACHINE_REF: machine_id,
                        CONF_COMMAND: cleaned[CONF_COMMAND],
                    }
                )
                return await self.async_step_manage()

        return self.async_show_form(
            step_id="add_command",
            data_schema=self._command_schema(),
            errors=errors,
        )

    async def async_step_edit_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a command to edit."""
        if user_input is not None:
            self._selected_command_id = user_input[CONF_COMMAND_ID]
            return await self.async_step_edit_command_details()

        return self.async_show_form(
            step_id="edit_command",
            data_schema=vol.Schema(
                {vol.Required(CONF_COMMAND_ID): vol.In(self._command_choices())}
            ),
        )

    async def async_step_edit_command_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit a selected command while preserving its stable ID."""
        assert self._selected_command_id is not None
        command = self._command_by_id(self._selected_command_id)
        errors: dict[str, str] = {}

        if user_input is not None:
            cleaned, errors = _clean_input_fields(
                user_input,
                (CONF_COMMAND_NAME, CONF_COMMAND),
            )
            name = cleaned.get(CONF_COMMAND_NAME, "")
            machine_id = user_input[CONF_MACHINE_REF]
            if not errors and self._command_name_exists(
                name, machine_id, exclude_id=self._selected_command_id
            ):
                errors[CONF_COMMAND_NAME] = "duplicate_command_name"
            elif not errors:
                replacement = {
                    CONF_COMMAND_ID: self._selected_command_id,
                    CONF_COMMAND_NAME: name,
                    CONF_MACHINE_REF: machine_id,
                    CONF_COMMAND: cleaned[CONF_COMMAND],
                }
                self._commands = [
                    replacement
                    if item[CONF_COMMAND_ID] == self._selected_command_id
                    else item
                    for item in self._commands
                ]
                self._selected_command_id = None
                return await self.async_step_manage()

        return self.async_show_form(
            step_id="edit_command_details",
            data_schema=self._command_schema(command),
            errors=errors,
        )

    async def async_step_remove_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove one configured command."""
        if user_input is not None:
            command_id = user_input[CONF_COMMAND_ID]
            self._commands = [
                command
                for command in self._commands
                if command[CONF_COMMAND_ID] != command_id
            ]
            return await self.async_step_manage()

        return self.async_show_form(
            step_id="remove_command",
            data_schema=vol.Schema(
                {vol.Required(CONF_COMMAND_ID): vol.In(self._command_choices())}
            ),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create or atomically update the config entry."""
        del user_input
        data = {
            CONF_MACHINES: deepcopy(self._machines),
            CONF_COMMANDS: deepcopy(self._commands),
        }
        title = _entry_title(self._machines)

        if self._reconfigure_entry is not None:
            return self.async_update_reload_and_abort(
                self._reconfigure_entry,
                data_updates=data,
                title=title,
            )
        return self.async_create_entry(title=title, data=data)

    def _machine_schema(self, existing: dict[str, Any] | None = None) -> vol.Schema:
        """Return the common machine-details schema."""
        existing = existing or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_MACHINE_NAME,
                    description=_suggested(
                        existing.get(CONF_MACHINE_NAME, "My Server")
                    ),
                ): _TEXT,
                vol.Required(
                    CONF_HOST,
                    description=_suggested(existing.get(CONF_HOST, "")),
                ): _TEXT,
                vol.Required(
                    CONF_PORT,
                    default=existing.get(CONF_PORT, DEFAULT_PORT),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(
                    CONF_USERNAME,
                    description=_suggested(existing.get(CONF_USERNAME, "root")),
                ): _TEXT,
                vol.Required(
                    CONF_AUTH_TYPE,
                    default=existing.get(CONF_AUTH_TYPE, AUTH_TYPE_PASSWORD),
                ): vol.In(
                    {
                        AUTH_TYPE_PASSWORD: "Password",
                        AUTH_TYPE_KEY: "Private key",
                    }
                ),
                vol.Required(
                    CONF_TIMEOUT,
                    default=existing.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_TIMEOUT, max=MAX_TIMEOUT),
                ),
            }
        )

    def _auth_schema(self, auth_type: str) -> vol.Schema:
        """Return a masked credential schema, optionally allowing credential reuse."""
        original = self._original_machine
        can_reuse = bool(original and original.get(CONF_AUTH_TYPE) == auth_type)

        if auth_type == AUTH_TYPE_PASSWORD:
            marker = (
                vol.Optional(CONF_PASSWORD)
                if can_reuse
                else vol.Required(CONF_PASSWORD)
            )
            return vol.Schema({marker: _PASSWORD})

        key_marker = (
            vol.Optional(CONF_PRIVATE_KEY)
            if can_reuse
            else vol.Required(CONF_PRIVATE_KEY)
        )
        return vol.Schema(
            {
                key_marker: _PRIVATE_KEY,
                vol.Optional(CONF_PRIVATE_KEY_PASSPHRASE): _PASSWORD,
            }
        )

    def _command_schema(self, existing: dict[str, Any] | None = None) -> vol.Schema:
        """Return the add/edit command schema."""
        existing = existing or {}
        machine_choices = {
            machine[CONF_MACHINE_ID]: machine[CONF_MACHINE_NAME]
            for machine in self._machines
        }
        fields: dict[Any, Any] = {
            vol.Required(
                CONF_COMMAND_NAME,
                description=_suggested(existing.get(CONF_COMMAND_NAME, "Check uptime")),
            ): _TEXT,
            vol.Required(
                CONF_MACHINE_REF,
                default=existing.get(
                    CONF_MACHINE_REF, next(iter(machine_choices), None)
                ),
            ): vol.In(machine_choices),
            vol.Required(
                CONF_COMMAND,
                description=_suggested(existing.get(CONF_COMMAND, "uptime")),
            ): _MULTILINE_TEXT,
        }
        return vol.Schema(fields)

    def _machine_from_input(
        self, user_input: dict[str, Any], machine_id: str
    ) -> dict[str, Any]:
        """Normalize non-secret machine form data."""
        return {
            CONF_MACHINE_ID: machine_id,
            CONF_MACHINE_NAME: _clean_string(user_input[CONF_MACHINE_NAME]),
            CONF_HOST: _clean_string(user_input[CONF_HOST]),
            CONF_PORT: int(user_input[CONF_PORT]),
            CONF_USERNAME: _clean_string(user_input[CONF_USERNAME]),
            CONF_AUTH_TYPE: user_input[CONF_AUTH_TYPE],
            CONF_TIMEOUT: int(user_input[CONF_TIMEOUT]),
        }

    def _merge_credentials(self, user_input: dict[str, Any]) -> None:
        """Merge secret form values, retaining existing values when left blank."""
        auth_type = self._current_machine[CONF_AUTH_TYPE]
        original = self._original_machine or {}

        if auth_type == AUTH_TYPE_PASSWORD:
            password = user_input.get(CONF_PASSWORD) or (
                original.get(CONF_PASSWORD)
                if original.get(CONF_AUTH_TYPE) == AUTH_TYPE_PASSWORD
                else None
            )
            if password is None:
                raise vol.Invalid("password required")
            self._current_machine[CONF_PASSWORD] = password
            return

        private_key = user_input.get(CONF_PRIVATE_KEY)
        if private_key:
            self._current_machine[CONF_PRIVATE_KEY] = private_key
            self._current_machine[CONF_PRIVATE_KEY_PASSPHRASE] = user_input.get(
                CONF_PRIVATE_KEY_PASSPHRASE, ""
            )
            return

        if original.get(CONF_AUTH_TYPE) != AUTH_TYPE_KEY or not original.get(
            CONF_PRIVATE_KEY
        ):
            raise vol.Invalid("private key required")
        self._current_machine[CONF_PRIVATE_KEY] = original[CONF_PRIVATE_KEY]
        self._current_machine[CONF_PRIVATE_KEY_PASSPHRASE] = original.get(
            CONF_PRIVATE_KEY_PASSPHRASE, ""
        )

    def _client_for_machine(
        self, machine: dict[str, Any], *, verify_host_key: bool
    ) -> SSHClient:
        """Build a test client from staged machine data."""
        return SSHClient(
            host=machine[CONF_HOST],
            port=machine[CONF_PORT],
            username=machine[CONF_USERNAME],
            auth_type=machine[CONF_AUTH_TYPE],
            password=machine.get(CONF_PASSWORD),
            private_key=machine.get(CONF_PRIVATE_KEY),
            private_key_passphrase=machine.get(CONF_PRIVATE_KEY_PASSPHRASE),
            timeout=machine[CONF_TIMEOUT],
            host_key_fingerprint=(
                machine.get(CONF_HOST_KEY_FINGERPRINT) if verify_host_key else None
            ),
        )

    def _commit_current_machine(self) -> None:
        """Add or replace the staged machine after host-key confirmation."""
        machine = deepcopy(self._current_machine)
        if self._machine_operation == "edit":
            machine_id = machine[CONF_MACHINE_ID]
            self._machines = [
                machine if item[CONF_MACHINE_ID] == machine_id else item
                for item in self._machines
            ]
        else:
            self._machines.append(machine)

        self._current_machine = {}
        self._original_machine = None
        self._machine_operation = "add"
        self._host_key_algorithm = ""

    def _machine_by_id(self, machine_id: str) -> dict[str, Any]:
        return next(
            machine
            for machine in self._machines
            if machine[CONF_MACHINE_ID] == machine_id
        )

    def _command_by_id(self, command_id: str) -> dict[str, Any]:
        return next(
            command
            for command in self._commands
            if command[CONF_COMMAND_ID] == command_id
        )

    def _machine_name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        folded = name.casefold()
        return any(
            machine[CONF_MACHINE_NAME].casefold() == folded
            and machine[CONF_MACHINE_ID] != exclude_id
            for machine in self._machines
        )

    def _command_name_exists(
        self,
        name: str,
        machine_id: str,
        exclude_id: str | None = None,
    ) -> bool:
        folded = name.casefold()
        return any(
            command[CONF_MACHINE_REF] == machine_id
            and command[CONF_COMMAND_NAME].casefold() == folded
            and command[CONF_COMMAND_ID] != exclude_id
            for command in self._commands
        )

    def _command_choices(self) -> dict[str, str]:
        machine_names = {
            machine[CONF_MACHINE_ID]: machine[CONF_MACHINE_NAME]
            for machine in self._machines
        }
        return {
            command[CONF_COMMAND_ID]: (
                f"{command[CONF_COMMAND_NAME]} → "
                f"{machine_names.get(command[CONF_MACHINE_REF], '?')}"
            )
            for command in self._commands
        }
