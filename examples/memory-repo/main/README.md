# Portable Memory Repo Example

This repo mirrors the layout that `using-memory` reads when persisted memory is relevant. Commit it into Git so it can travel between machines through the same remote. Clone or pull the same repo on each host, then point the local config to this repo root and choose a stable namespace for that host, user, or environment.

- Git-managed markdown keeps history searchable and auditable.
- The repo includes sample `main/local/` files so readers can see the expected shape. A real setup reads only the configured `<namespace>/local/*` files during retrieval.
- The repo is portable: any machine that reads `config.example.yaml` and follows the layout can play the same role.
