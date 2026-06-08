# Nginx 502 Troubleshooting Runbook

## Symptoms

- The gateway returns `502 Bad Gateway`.
- Upstream latency rises sharply after a release or config change.
- Access logs show `upstream prematurely closed connection`.

## Quick Checks

- Confirm the upstream service is healthy and listening on the configured port.
- Review recent deployment records, gateway config changes, and timeout settings.
- Compare gateway error timestamps with upstream application logs.

## Common Root Causes

### Upstream service not healthy

- The application process exited after deployment.
- Health checks fail because required environment variables are missing.
- The container was restarted repeatedly due to memory pressure.

### Timeout or connection pool saturation

- Upstream request timeout is shorter than the actual processing time.
- Database connection exhaustion causes the service to respond too slowly.
- Thread pools are blocked by slow downstream calls.

### Gateway configuration mismatch

- The upstream target points to the wrong port or hostname.
- TLS termination is configured differently between environments.
- Header size or body size limits were lowered by a recent change.

## Ordered Troubleshooting Steps

1. Check the upstream service status, restart history, and readiness probes.
2. Inspect upstream application logs around the first 502 timestamp.
3. Verify Nginx upstream host, port, and timeout configuration.
4. Confirm database and cache dependencies are reachable from the service pod or host.
5. If latency increased after a release, compare build version and rollback if needed.

## Risk Notes

- In production, avoid blind Nginx restarts before preserving logs and active config.
- If many clients are affected, assess impact scope before applying a rollback.

