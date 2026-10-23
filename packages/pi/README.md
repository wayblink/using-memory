# using-memory for Pi

The Pi package: a `umem` tool, a `/umem` command, and the memory hooks, all thin
over `scripts/memory_tool.py` in the skill root.

Install with `scripts/link.sh pi` or `scripts/install.sh pi` from the repository
root. Full documentation — event mapping, the write gate and its latch,
`/umem web`, configuration and troubleshooting — is in
[`../../references/pi-integration.md`](../../references/pi-integration.md).

## Development

TypeScript sources are loaded by Pi directly (jiti), so there is no build step.
Tests and typechecking need the host packages available:

```bash
npm install          # installs the peer deps for typechecking only
npm test             # 56 cases, no Pi runtime required
npm run typecheck
```

The peer dependencies are declared `optional` on purpose: Pi supplies them at
runtime and a physical copy would create duplicate module instances.
