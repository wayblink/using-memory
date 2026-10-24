/**
 * snapshot.ts — turn `load --json --brief` into the text Pi injects.
 *
 * Split out of index.ts so it can be tested without a Pi runtime. index.ts
 * imports `@earendil-works/pi-ai`, `pi-tui` and `typebox`, which are only
 * present inside Pi, so anything living there is untestable in CI — and this
 * function decides what the model actually reads about its rules. It was in
 * index.ts with no tests, which is exactly how its section title drifted from
 * "Saved preferences" to "Active spec" without any test noticing.
 *
 * Pure: no I/O, no imports.
 */

/** Collapse duplicate rules; the same rule twice is noise, not emphasis. */
function dedupe(lines: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of lines) {
    const key = line.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(line);
  }
  return out;
}

/** Strip list markers and the leading date, as the Python renderer does. */
function cleanRuleLine(raw: string): string {
  return raw
    .replace(/^[-*+]\s*/, "")
    .replace(/^\d+\.\s*/, "")
    .replace(/^\[\d{4}-\d{2}-\d{2}\]\s*/, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Return only the actual rule entries from a SPEC document.
 *
 * Content before the first list item is the file's heading and preamble, which
 * explain the format rather than constrain the agent. From there, plain lines
 * continue the preceding rule (multi-paragraph rules use `Why:` / `How to
 * apply:` blocks) and are joined onto it rather than dropped.
 */
export function ruleLines(doc: string): string[] {
  const out: string[] = [];
  let started = false;
  for (const raw of doc.split("\n")) {
    const stripped = raw.trim();
    if (stripped === "") continue;
    const isBullet = /^([-*+]|\d+\.)\s/.test(stripped);
    if (!isBullet) {
      if (!started) continue;
      if (stripped.startsWith("#")) continue;
      const line = cleanRuleLine(stripped);
      if (line !== "" && out.length > 0) out[out.length - 1] = `${out[out.length - 1]} ${line}`;
      continue;
    }
    started = true;
    const line = cleanRuleLine(stripped);
    if (line !== "") out.push(line);
  }
  return out;
}

/** One MEMORY.md entry as `[tag date] title`. */
interface MemoryRow {
  readonly tag: string;
  readonly date: string;
  readonly title: string;
}

const MEMORY_ENTRY_RE = /^- \[([A-Za-z0-9_-]+)(?:\|(\d{4}-\d{2}-\d{2}))?(?:\|([^\]]*))?\]\s+(.*)$/;

/** First clause of an entry, enough to recognise it later. */
function shortTitle(body: string, limit = 110): string {
  let text = body.replace(/^#+\s*/, "").replace(/\*\*|`/g, "").trim();
  if (text.length <= limit) return text;
  for (const sep of ["。", "；", ". ", "; "]) {
    const idx = text.indexOf(sep);
    if (idx > 0 && idx <= limit) return text.slice(0, idx);
  }
  return `${text.slice(0, limit).trimEnd()}…`;
}

/**
 * Index MEMORY as `[tag date] title` rows, newest first, de-duplicated.
 *
 * MEMORY is knowledge, not rules: it is retrieved on demand, so the model needs
 * to know *that* a fact exists rather than to carry every body in context. The
 * previous approach kept the file's tail and dropped its head, which on a
 * curated decision store is backwards — it retained the newest environment
 * snapshots and discarded the oldest product decisions. An index has no such
 * ordering problem: every title fits in roughly the space six whole entries
 * used to take.
 */
export function memoryIndex(docs: readonly string[], project: string | null = null): string[] {
  const wanted = (project ?? "").toLowerCase();
  const rows: (MemoryRow & { projects: string[] })[] = [];
  const seen = new Set<string>();
  for (const doc of docs) {
    for (const raw of doc.split("\n")) {
      const m = MEMORY_ENTRY_RE.exec(raw.trim());
      if (m === null) continue;
      const body = (m[4] ?? "").replace(/\s+/g, " ").trim();
      if (body === "") continue;
      const projects = (m[3] ?? "")
        .split(",")
        .map((p) => p.trim().toLowerCase())
        .filter((p) => p !== "");
      // Untagged entries are cross-cutting and stay visible everywhere; the
      // filter is here to keep other repositories' specifics out, not to hide
      // general knowledge.
      if (wanted !== "" && projects.length > 0 && !projects.includes(wanted)) continue;
      const key = body.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push({ tag: m[1] ?? "", date: m[2] ?? "", title: shortTitle(body), projects });
    }
  }
  rows.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  return rows.map((r) => `[${r.tag}${r.date === "" ? "" : ` ${r.date}`}] ${r.title}`);
}

/** One document catalogue row. */
interface DocRow {
  readonly path: string;
  readonly title: string;
  readonly type: string;
  readonly modified: string;
  readonly projects: string[];
}

/**
 * Narrow the document catalogue to the current repository.
 *
 * Documents are knowledge, retrieved on demand, so titles are what the context
 * needs. The catalogue is 66 entries on this machine and most belong to other
 * repositories; sending all of them spends tokens on documents the model will
 * never open here. Two kinds survive: entries tagged with the current repo, and
 * entries tagged with no project at all (cross-cutting guides). With no repo
 * resolved the whole catalogue is shown — the Python side does the same.
 */
export function docsIndex(entries: readonly DocRow[], repo: string | null): string[] {
  const wanted = (repo ?? "").toLowerCase();
  const chosen = entries.filter((e) => {
    const projects = (e.projects ?? []).map((p) => p.toLowerCase());
    if (wanted === "" || projects.length === 0) return true;
    return projects.includes(wanted);
  });
  chosen.sort((a, b) => ((a.modified ?? "") < (b.modified ?? "") ? 1 : -1));
  return chosen.map((e) => {
    const kind = e.type === "" ? "doc" : e.type;
    const path = e.path === "" ? "?" : e.path;
    return `[${kind}] ${e.title === "" ? path : e.title} (${path})`;
  });
}

export function renderSnapshot(raw: string, repo: string | null = null): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
  const data = parsed as {
    mode?: string;
    preferences?: string[];
    durable_memory?: string[];
    log_entries?: { ts?: string; tag?: string; level?: string; text?: string; project?: string }[];
    docs_index?: { path?: string; title?: string; type?: string; modified?: string; projects?: string[] }[];
    warnings?: string[];
  };

  const sections: string[] = [];
  // Rules go first and go whole: they must be in effect before the first answer.
  // Nothing here truncates them — a rule shown partially reads as a complete
  // rule and gets followed literally.
  //
  // File headings and preambles are stripped: a SPEC file opens with "# Spec"
  // and a sentence explaining where project specs live. Those describe the file
  // format, so rendering them as content makes the model treat documentation as
  // instructions. The Python side filters the same way in `_rule_lines`; both
  // hosts must deliver the same text.
  // Each document is processed on its own: joining them first would let the
  // last rule of one file absorb the heading/preamble of the next as a
  // continuation line (the Python side has the same per-document rule).
  const rules = dedupe((data.preferences ?? []).flatMap((doc) => ruleLines(doc)));
  if (rules.length > 0) {
    sections.push(
      `## Active spec\n\nRules for this project. They are constraints, not suggestions — apply them unless the user explicitly overrides one in the current turn:\n\n${rules.map((r) => `- ${r}`).join("\n")}`,
    );
  }

  const memoryRules = memoryIndex(data.durable_memory ?? [], repo);
  if (memoryRules.length > 0) {
    sections.push(
      `## Long-term memory (index)\n\n${memoryRules.length} saved facts, decisions and lessons. These are titles, not the entries themselves: when one could change your answer, fetch the body with \`umem search "<title keywords>"\` before relying on it. Do not guess at the contents of a title you have not read.\n\n${memoryRules.map((r) => `- ${r}`).join("\n")}`,
    );
  }

  // The log window is "today and yesterday" across every project. Narrowing it
  // to the current repo is the difference between a third of the context being
  // recent work and a third of it being other repositories' deployments.
  // Untagged entries stay, as everywhere else.
  const wanted = (repo ?? "").toLowerCase();
  const entries = (data.log_entries ?? []).filter((entry) => {
    const p = (entry.project ?? "").toLowerCase();
    return wanted === "" || p === "" || p === wanted;
  });
  if (entries.length > 0) {
    const lines = entries.map((entry) => {
      const head = [entry.ts, entry.tag, entry.level].filter(Boolean).join(" ");
      return `- ${head}: ${(entry.text ?? "").replace(/\s+/g, " ").slice(0, 240)}`;
    });
    sections.push(`## Recent operations\n\n${lines.join("\n")}`);
  }

  if (data.mode === "no_memory") {
    sections.push(
      "## Memory not configured\n\nNo memory store is configured on this machine. Run `umem setup` to create one.",
    );
  }

  const warnings = (data.warnings ?? []).filter((w) => typeof w === "string");
  if (warnings.length > 0) {
    sections.push(`## Memory warnings\n\n${warnings.map((w) => `- ${w}`).join("\n")}`);
  }

  return sections.length === 0 ? null : sections.join("\n\n---\n\n");
}
