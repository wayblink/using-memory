# Portable Memory Repo Example

This repo mirrors the layout that `using-memory` reads when persisted memory is relevant. Commit it into Git so it can travel between machines and stay in sync via shared remotes. Clone or pull on each host, then point the local config to the writable primary root while keeping the reference roots read-only.

- Git-managed markdown keeps history searchable and auditable.
- The repo includes sample `local/` files so readers can see the expected shape, but only the writable primary root should actually rely on them during retrieval; other machines ignore foreign `local/*` while reading memory.
- The repo is portable: any machine that reads `config.example.yaml` and follows the layout can play the same role.
