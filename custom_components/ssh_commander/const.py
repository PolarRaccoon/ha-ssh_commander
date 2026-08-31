"""Constants for SSH Commander."""

from __future__ import annotations

DOMAIN = "ssh_commander"

# Config entry keys
CONF_MACHINES = "machines"
CONF_COMMANDS = "commands"

# Machine keys
CONF_MACHINE_ID = "machine_id"
CONF_MACHINE_NAME = "machine_name"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_AUTH_TYPE = "auth_type"
CONF_PASSWORD = "password"
CONF_PRIVATE_KEY = "private_key"
CONF_PRIVATE_KEY_PASSPHRASE = "private_key_passphrase"
CONF_HOST_KEY_FINGERPRINT = "host_key_fingerprint"
CONF_TIMEOUT = "timeout"

# Command keys
CONF_COMMAND_ID = "command_id"
CONF_COMMAND_NAME = "command_name"
CONF_COMMAND = "command"
CONF_MACHINE_REF = "machine_id"

# Flow-only keys
CONF_CONFIRM = "confirm"

# Authentication types
AUTH_TYPE_PASSWORD = "password"
AUTH_TYPE_KEY = "key"

# Defaults and validation limits
DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 30
MIN_TIMEOUT = 1
MAX_TIMEOUT = 300
MAX_CAPTURE_BYTES = 8192

# Service action
SERVICE_RUN_COMMAND = "run_command"
ATTR_ENTRY_ID = "entry_id"
ATTR_COMMAND_ID = "command_id"
ATTR_MACHINE_ID = "machine_id"

# Result attributes
ATTR_STDOUT = "stdout"
ATTR_STDERR = "stderr"
ATTR_RETURN_CODE = "return_code"
ATTR_SUCCESS = "success"
ATTR_DURATION = "duration_seconds"
ATTR_STDOUT_TRUNCATED = "stdout_truncated"
ATTR_STDERR_TRUNCATED = "stderr_truncated"
ATTR_LAST_RUN = "last_run"
