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

export function renderSnapshot(raw: string): string | null {
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
    log_entries?: { ts?: string; tag?: string; level?: string; text?: string }[];
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

  const memory = (data.durable_memory ?? []).join("\n\n").trim();
  if (memory !== "") sections.push(`## Long-term memory\n\n${memory}`);

  const entries = data.log_entries ?? [];
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
