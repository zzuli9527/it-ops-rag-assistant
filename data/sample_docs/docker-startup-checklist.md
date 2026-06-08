# Docker Service Startup Checklist

## Symptoms

- The container exits immediately after start.
- Startup logs show port binding conflict or missing environment variables.
- The process runs locally but fails in the target host environment.

## Common Root Causes

### Port conflict

- Another process is already using the exposed port.
- The compose file maps the wrong internal port.

### Missing runtime dependencies

- Required config files or environment variables were not mounted.
- The service depends on a database, cache, or volume that is unavailable.

### Image or command issue

- The image entrypoint differs from the expected startup command.
- The startup script lacks execute permissions.

## Ordered Troubleshooting Steps

1. Inspect container logs and exit code.
2. Verify port usage on the host and compare with the compose mapping.
3. Check mounted files, environment variables, and secrets.
4. Validate dependency endpoints and network attachment.
5. If the startup command changed, inspect the image diff or roll back to the last known good version.

