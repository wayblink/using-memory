# Dozo Built-in Memory Plugin Integration

## Goal

Make `using-memory` usable as Dozo's built-in memory plugin without tying Dozo core to the current CLI, hook protocol, Markdown layout, or any single storage backend.

The desired shape is:

- `using-memory` remains useful as a standalone skill and CLI.
- Dozo can embed it as a provider-neutral memory/context capability.
- Future memory and knowledge systems can coexist behind the same Dozo contracts.
- Agents see stable tools/capabilities such as `memory.read`, `memory.write_preference`, and `memory.search`, not implementation details like JSONL paths or Git roots.

## Current `using-memory` Shape

`using-memory` already has most of the right raw material:

- A Git/Markdown/JSONL storage layout scoped by namespace.
- Distinct data dimensions:
  - `PREFERENCES.md` for stable user preferences.
  - `MEMORY.md` for curated durable facts, decisions, and lessons.
  - `docs/` plus `docs/index.json` for structured topic documents.
  - `log/YYYY-MM-DD.jsonl` for operation continuity.
  - `STATS` for machine-local hook accounting.
- CLI commands for load/search/write/maintain/status/export.
- A small `memory_lib.core` with config/path/atomic IO primitives separated from the CLI.
- Optional remote forwarding via top-level `remote.endpoint` and `/api/v1/*` routes.
- Host-specific hooks for Claude/Codex that implement session-start reminders, stop gates, operation logging prompts, and distillation triggers.

The main mismatch with Dozo is not storage. It is ownership and integration level: `using-memory` is currently agent-host driven, while Dozo needs an app-owned capability that can be compiled into every `AgentAdapter` without branching on provider ids.

## Dozo Target Model

Dozo should treat memory as a built-in extension that provides context capabilities, not just an iframe tool page.

Recommended layers:

```text
Dozo Session / Run / Tool / Workspace events
        -> Memory Capture
        -> using-memory backend adapter
        -> Context Provider API
        -> Context Assembly
        -> AgentAdapter projection
```

The important boundary is between memory storage and context delivery.

- Storage answers: what is saved, where, with what provenance.
- Context delivery answers: what should be shown to this run, under this scope, within this token budget.

## Provider-neutral Contracts

Dozo should introduce contracts roughly like these in protocol/core, then implement a `using-memory` adapter behind them.

```ts
export type ContextScope = {
  principalId: string;
  workspaceIds: string[];
  sessionId?: string;
  runId?: string;
  workspacePath?: string;
};

export type ContextHit = {
  id: string;
  sourceId: string;
  kind: "preference" | "memory" | "doc" | "log" | "knowledge";
  title?: string;
  text: string;
  score?: number;
  provenance: Array<{ type: "file" | "entry" | "log" | "doc"; ref: string }>;
  metadata?: Record<string, unknown>;
};

export interface ContextProvider {
  id: string;
  displayName: string;
  search(input: { query: string; scope: ContextScope; limit?: number }): Promise<ContextHit[]>;
  read(input: { scope: ContextScope; slots?: string[] }): Promise<ContextHit[]>;
  write?(input: { scope: ContextScope; entry: MemoryWrite }): Promise<MemoryWriteResult>;
}
```

A `using-memory` implementation can map these to existing commands/functions:

- `read` -> `load` snapshot, preferences, durable memory, matching docs.
- `search` -> `search` over docs, `MEMORY.md`, and logs.
- `write(preference)` -> `write-preference`.
- `write(log)` -> `write-log` for operation history.
- `write(memory)` -> `write-memory` for curated fact/decision/lesson.
- `write(doc)` -> `upsert-doc`.

Dozo should not expose raw `write-log` as a normal agent tool. It should be used by Dozo-side lifecycle capture and explicit operation logging workflows.

## Required `using-memory` Changes

### 1. Extract a Python library API from `memory_tool.py`

The CLI is large and usable, but Dozo should not shell out for every memory request long term.

Add a small public module, for example:

```text
scripts/memory_lib/service.py
```

with functions such as:

```py
def load_snapshot(config: dict, selectors: LoadSelectors) -> dict: ...
def search_memory(config: dict, query: str, selectors: SearchSelectors) -> dict: ...
def write_log(config: dict, entry: LogEntryInput) -> dict: ...
def write_preference(config: dict, text: str) -> dict: ...
def write_memory(config: dict, entry: MemoryEntryInput) -> dict: ...
def upsert_doc(config: dict, input: DocInput) -> dict: ...
```

The existing CLI should become an adapter over this service API. That preserves the standalone `umem` workflow while giving Dozo a stable embedding surface.

### 2. Stabilize JSON schemas

The CLI outputs are currently practical but not declared as versioned protocol. Dozo needs versioned schemas for:

- `MemorySnapshot`
- `MemorySearchResult`
- `MemoryLogEntry`
- `MemoryDocEntry`
- `MemoryWriteResult`
- `MemoryStatus`

Keep them plain JSON and backward-compatible. Avoid exposing Python-only shapes.

### 3. Add an app/plugin mode config

Keep existing skill config, but allow Dozo to own the config path and namespace:

```yaml
mode: plugin
memory_roots:
  - path: <dozo-state>/memory
    namespace: main
    role: primary
    writable: true
```

Dozo should be able to create this non-interactively. `setup` remains for standalone users.

### 4. Keep hooks optional

The Claude/Codex hooks are useful outside Dozo, but inside Dozo they should be disabled by default. Dozo already observes Session/Run/Tool events; it should capture memory traces itself instead of relying on host-specific hook payloads.

### 5. Preserve remote forwarding

The existing `remote.endpoint` support is a good bridge. In early integration, Dozo can expose `/api/v1/load`, `/api/v1/search`, `/api/v1/log`, `/api/v1/memory`, `/api/v1/preference`, and `/api/v1/doc`, and local `umem` can forward to Dozo.

This gives two-way compatibility:

- Dozo can use local `using-memory` files.
- Standalone `umem` can talk to Dozo when Dozo is running.

## Required Dozo Changes

### 1. Move from iframe-only to capability provider

Dozo currently installs `dozo-memory` as a built-in shortcut pointing at `@using-memory/memory-web`. Keep the UI surface, but add actual compiled capability data:

```ts
provides: {
  shortcuts: [...],
  tools: [memory.read, memory.search, memory.write_preference],
  instructions: [memory usage guidance],
  contextProviders: [{ id: "using-memory", kind: "memory" }]
}
```

`contextProviders` does not exist yet; it should be added as a provider-neutral extension capability.

### 2. Add `MemoryService` in Dozo core/application boundary

This should wrap a `ContextProvider`, not implement `using-memory` details in core.

Responsibilities:

- Resolve Dozo principal/workspace/session scope into memory namespace/project/topic selectors.
- Capture important Run/Tool lifecycle events into structured operation logs.
- Serve Gateway routes for UI and CLI remote forwarding.
- Assemble a small context bundle before an agent run.

### 3. Add agent-visible tools through Dozo's existing tool executor path

Dozo already has `AgentToolExecutor` for terminal tools. Extend the model so memory tools can be executed provider-neutrally:

- `memory.read`
- `memory.search`
- `memory.write_preference`

Avoid broad `memory.write_log` as an agent-facing tool at first.

### 4. Inject context through compiled capabilities

Dozo should gather memory context before `SessionService.run()` calls the adapter, then attach it to `CreateSessionInput.capabilities` or run input metadata. Adapters project it differently:

- Claude SDK: system prompt/instructions plus optional MCP tools.
- Codex app-server: developer instructions plus MCP config when needed.
- Pi SDK: custom tools and prompt guidelines.

Core should not branch by adapter id.

## Phased Implementation

### Phase 0: Contract and adapter design

- Add this design to `using-memory`.
- Define Dozo protocol types for `ContextProvider`, `ContextHit`, and memory tool specs.
- Decide whether the first adapter shells out to `umem` or imports Python service code through a sidecar process.

### Phase 1: Remote-compatible Dozo memory routes

- Implement Dozo Gateway `/api/v1/load`, `/api/v1/search`, `/api/v1/log`, `/api/v1/memory`, `/api/v1/preference`, `/api/v1/doc` using a `using-memory` adapter.
- Configure `umem remote.endpoint` to point at Dozo for local testing.
- Keep fallback-to-local behavior in the CLI.

### Phase 2: Built-in memory tools

- Add `memory.read`, `memory.search`, and `memory.write_preference` as Dozo-owned tools.
- Project them through existing adapter capability mechanisms.
- Add permission policy for writes.

### Phase 3: Context assembly

- Before each run, read preferences and relevant project/topic docs/log summaries.
- Budget context explicitly.
- Include provenance in the injected block.
- Add UI visibility into what memory was injected.

### Phase 4: Knowledge-source interoperability

- Do not force knowledge bases into `using-memory` storage.
- Instead, add separate `KnowledgeConnector` providers and let the same Context Provider layer combine their hits with memory hits.
- `using-memory docs/` can be one knowledge source, but not the only one.

## Non-goals

- Do not replace Dozo durable state with the memory repo.
- Do not make Dozo core know Git/Markdown/JSONL paths.
- Do not make agent adapters branch on `using-memory` specifically.
- Do not auto-write long-term memory without provenance and policy checks.
- Do not use host-specific Claude/Codex hooks inside Dozo as the primary capture mechanism.

## Feasibility Assessment

This integration is feasible and low-risk if it is done through a provider-neutral Context Provider boundary.

`using-memory` is already close: it has a disciplined repo layout, namespace scoping, atomic writes, search/load/write commands, remote forwarding, and a separated low-level core module. The main work is extracting a stable service API from the CLI and adding Dozo-side context/tool contracts.

The best first implementation can still shell out to `umem` or call the existing remote API while the Python service API is extracted. That keeps the Dozo change small and preserves standalone `using-memory` behavior.
