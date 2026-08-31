# SSH Commander for Home Assistant

![SSH Commander](custom_components/ssh_commander/brand/logo.png)

SSH Commander creates a Home Assistant button for each allow-listed SSH command. A button opens a short-lived SSH connection, runs exactly the configured command, captures a bounded result, and disconnects.

It is designed for small homelab actions such as restarting a service, waking a maintenance script, shutting down a machine, or requesting a backup without exposing arbitrary shell execution to automations.

## Highlights

- Password, RSA, ECDSA, and Ed25519 private-key authentication
- Explicit SHA256 host-key confirmation and pinning for new or edited machines
- Add, edit, and remove machines and commands through Home Assistant's reconfigure flow
- One device per SSH machine and one button entity per command
- Optional `ssh_commander.run_command` response data for scripts and automations
- Hard command timeout, simultaneous stdout/stderr draining, and 8 KiB capture limits
- Duplicate-trigger protection for the same command
- Privacy-safe diagnostics and automatic cleanup of removed command entities
- Automatic migration from the original v1 format, including recovery of changes saved by its broken options flow

## Requirements

- Home Assistant 2026.3.0 or newer
- An SSH server reachable from the Home Assistant host
- Non-interactive remote commands

## Installation

### HACS custom repository

1. Open HACS.
2. Add `https://github.com/PolarRaccoon/ha-ssh_commander` as a custom **Integration** repository.
3. Install **SSH Commander**.
4. Restart Home Assistant.

### Manual

Copy `custom_components/ssh_commander` into your Home Assistant configuration directory:

```text
/config/custom_components/ssh_commander
```

Restart Home Assistant afterward.

## Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **SSH Commander**.
3. Add a machine and its credentials.
4. Compare the displayed SHA256 host-key fingerprint with the matching key on the server:

   ```bash
   for key in /etc/ssh/ssh_host_*_key.pub; do
     ssh-keygen -lf "$key" -E sha256
   done
   ```

5. Confirm the key, add at least one command, then choose **Save and finish**.

Use **Reconfigure** on the integration entry to add, edit, or remove machines and commands. Changes are staged until **Save and finish** is selected.

## Using command buttons

Each command is a normal button entity and can be placed on a dashboard or called from an automation:

```yaml
action: button.press
target:
  entity_id: button.media_server_restart_jellyfin
```

The button attributes retain the last bounded result:

- `success`
- `return_code`
- `stdout` and `stderr`
- `duration_seconds`
- truncation flags
- `command_id` and `machine_id`

## Response-producing action

The integration action runs only a command already stored in the integration. It does not accept arbitrary shell text.

```yaml
action: ssh_commander.run_command
data:
  entry_id: 01J_EXAMPLE_ENTRY_ID
  command_id: 574ae70d-dca6-4497-987d-566e53276f6e
response_variable: ssh_result
```

Find the stable `command_id` and config-entry ID in the command button's attributes and integration details. `entry_id` can be omitted when the command ID is unique across loaded SSH Commander entries.

## Security guidance

SSH Commander is intentionally an allow-list, but every configured command still has the permissions of its remote account.

- Create a dedicated, unprivileged SSH user for Home Assistant.
- Prefer a dedicated private key over a password.
- Restrict `sudo` to exact commands and absolute paths. Do not grant unrestricted passwordless sudo.
- Do not place secrets directly in command strings; results can be recorded in entity history.
- Protect Home Assistant's `.storage` data and backups. Connection credentials are stored in the config entry and are not independently encrypted by this integration.
- Verify host-key fingerprints out of band. A changed key is blocked until the machine is explicitly edited and the new fingerprint confirmed.

Example narrow sudoers rule:

```text
ha-ssh ALL=(root) NOPASSWD: /usr/bin/systemctl restart jellyfin.service
```

The matching configured command would be:

```bash
sudo /usr/bin/systemctl restart jellyfin.service
```

## Behavior and limitations

- A fresh SSH connection is used for every invocation. This is slightly slower than pooling, but avoids stale sessions and keeps idle resource use at zero.
- Interactive prompts and commands requiring a TTY are unsupported. Configure key authentication or narrowly scoped `NOPASSWD` rules.
- The configured timeout is applied to each SSH connection phase and to remote command execution.
- Stdout and stderr are each capped at 8 KiB. Extra data is drained to avoid SSH channel deadlocks but is not retained.
- A non-zero remote exit status is a completed result with `success: false`; connection and timeout failures raise a Home Assistant action error.

## Upgrading from 1.x

Version 2 migrates existing machines and commands automatically. If the old configuration menu saved newer values into `entry.options`, those values take precedence during migration so the formerly ignored edits are recovered.

Existing machines do not have a pinned host key. Reconfigure and save each legacy machine once to test the connection, confirm its fingerprint, and enable pinning.

## Troubleshooting

### Authentication works in a terminal but not in Home Assistant

SSH Commander deliberately disables the Home Assistant process's SSH agent and local key search. Paste the intended private key into the integration or configure its password explicitly.

### `sudo` waits or fails

Commands are non-interactive. Use a command-specific `NOPASSWD` sudoers rule; do not use `sudo -S` or embed passwords.

### Host key changed

Confirm why the remote key changed first. If the machine was rebuilt or its SSH host keys were intentionally rotated, edit that machine in **Reconfigure**, verify the new fingerprint, and save.

## License

[MIT](LICENSE)
