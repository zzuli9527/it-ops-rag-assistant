# Redis Authentication Troubleshooting

## Symptoms

- The client reports `NOAUTH Authentication required`.
- Services reconnect repeatedly after a credential update.
- Cache hit rate drops because requests bypass Redis after auth errors.

## Quick Checks

- Confirm the Redis endpoint and port used by the service.
- Verify whether ACL users or a single password is enabled.
- Compare application secrets with the latest credential management record.

## Common Root Causes

### Wrong password or ACL user

- The application still uses an old password after rotation.
- The ACL user exists but lacks the required command permissions.
- The secret injection job updated one service but missed another deployment.

### Environment mismatch

- The application points to the test Redis while using production credentials.
- Multiple clusters share similar names and the wrong endpoint was copied.

### Connection bootstrap issues

- TLS is required but the client is configured for plain TCP.
- Sentinel or cluster mode requires different bootstrap options.

## Ordered Troubleshooting Steps

1. Check whether the failure is password related, ACL related, or endpoint related.
2. Validate the deployed secret values against the latest rotation record.
3. Confirm client bootstrap mode, TLS settings, and Redis cluster role.
4. Test authentication from the same runtime environment as the service.
5. After fixing credentials, monitor reconnect rate and cache hit recovery.

## Risk Notes

- Avoid rotating credentials again before identifying which deployment still holds stale secrets.

