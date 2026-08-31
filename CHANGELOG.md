# Changelog

## 2.0.1

- Fixed Add Integration and text-entry forms returning HTTP 500 because custom
  validators wrapped Home Assistant selectors and could not be serialized.
- Added Home Assistant-backed regression tests for Add and Reconfigure flow
  response serialization.

## 2.0.0

- Fixed configuration changes being saved to options while runtime code read only the original entry data.
- Replaced the old dropdown wizard with a complete Home Assistant reconfigure menu.
- Added machine and command editing, input validation, and removal cleanup.
- Added SHA256 SSH host-key enrollment and pinning.
- Added RSA, ECDSA, and Ed25519 private-key support with masked credential fields.
- Added bounded command runtime and output capture with simultaneous stdout/stderr draining.
- Added command duplicate-run protection, richer button results, and action response data.
- Registered the action during integration setup and added `services.yaml` metadata.
- Added privacy-safe diagnostics, local Home Assistant brand assets, HACS metadata, and validation workflows.
- Updated Paramiko from 3.4.0 to 5.0.0.

## 1.0.0

- Initial release.
