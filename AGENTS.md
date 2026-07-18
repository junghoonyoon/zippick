# Repository instructions

## exe.dev deployment

Deployments to exe.dev must always use this order:

1. Commit the intended changes locally.
2. Push the commit to `origin/main` on GitHub.
3. Run `./scripts/deploy-exe-dev.sh`.

Never copy an uncommitted local workspace directly to exe.dev with `scp`, `rsync`,
or a similar command. The exe.dev release must be built from the exact commit
already present on GitHub.
