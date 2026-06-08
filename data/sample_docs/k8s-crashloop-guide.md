# Kubernetes CrashLoopBackOff Guide

## Symptoms

- The pod state becomes `CrashLoopBackOff`.
- Restart count keeps increasing after deployment.
- The application becomes ready for a short time and exits again.

## Common Root Causes

### Startup command or env config is wrong

- Required environment variables are missing.
- The startup command references a file path that does not exist in the image.
- The container expects a config file that was not mounted.

### Dependency not ready

- The application fails immediately because the database or cache is unreachable.
- A migration job locks startup because the schema version is incompatible.

### Resource or probe configuration issue

- Memory limits are too low and the container is OOM killed.
- Liveness probes are too aggressive during warm-up.
- Readiness probes call an endpoint that depends on a downstream system.

## Ordered Troubleshooting Steps

1. Inspect pod events, restart reason, and the previous container logs.
2. Compare environment variables, mounted configs, and image tag with the last healthy version.
3. Check dependency reachability from the cluster network.
4. Review probe thresholds, startup time, and container resource usage.
5. Roll back the deployment if the failure started after a release and the impact is broad.

