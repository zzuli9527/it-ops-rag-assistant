# MySQL Connection Troubleshooting Playbook

## Symptoms

- Application startup fails with `Connection refused`.
- Connection pool acquisition time keeps rising.
- Error logs show `Too many connections` or frequent reconnect attempts.

## Diagnostic Signals

- MySQL process status and port listening state.
- Current active connections, max connections, and slow query count.
- Recent schema changes, failover events, or password rotation records.

## Common Root Causes

### Database not reachable

- The database process is down or the service endpoint is wrong.
- Security group or firewall rules block traffic from the application node.
- DNS resolution points to an old host after failover.

### Connection exhaustion

- The application leaks connections because transactions are not closed.
- Slow queries keep sessions occupied for too long.
- Pool size is larger than the database limit across replicas.

### Authentication or configuration errors

- Credentials were rotated but the application still uses old secrets.
- TLS or charset configuration changed after a version upgrade.
- Application configuration references the wrong environment.

## Ordered Troubleshooting Steps

1. Confirm the MySQL process is running and the application host can reach port 3306.
2. Check `Threads_connected`, `max_connections`, and slow query logs.
3. Review connection pool settings and recent release changes.
4. Validate the username, password, TLS settings, and target endpoint.
5. If `Too many connections` appears, find long-running queries before forcing session cleanup.

## Risk Notes

- Do not kill active sessions in production without checking transaction impact.
- If credential rotation is involved, verify all replicas and scheduled jobs use the same secret set.

