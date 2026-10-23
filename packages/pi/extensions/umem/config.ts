/**
 * config.ts — the `pi:` block of the using-memory `config.yaml`.
 *
 * The Python side owns this file; this module only reads the handful of values
 * the extension needs at load time (which tool to call, how big a snapshot to
 * inject, whether the gate runs). It deliberately does not write.
 *
 * There is no YAML parser here on purpose: adding a dependency for six scalar
 * keys would drag a runtime package into a skill that otherwise has none. The
 * `pi:` block is flat `key: value` with optional comments, so a small
 * indentation-aware scan covers it, and anything it cannot parse falls back to
 * the default rather than failing the session.
 */

import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

/** Resolve the config file the same way the Python hooks do. */
export function resolveConfigPath(explicit?: string): string | null {
  const env = process.env.USING_MEMORY_CONFIG?.trim();
  if (env) {
    const expanded = env.replace(/^~(?=$|\/)/, homedir());
    if (existsSync(expanded)) return expanded;
  }
  if (explicit) {
    const expanded = explicit.replace(/^~(?=$|\/)/, homedir());
    if (existsSync(expanded)) return expanded;
  }
  const fallback = join(homedir(), ".skills", "using-memory", "config.yaml");
  return existsSync(fallback) ? fallback : null;
}

export interface UmemPiConfig {
  /** `message` injects the write gate; `off` disables it. */
  readonly gate: "message" | "off";
  /** Human turns between gate fires. Looser than the hook hosts' 20 by default. */
  readonly detailTurnInterval: number;
  readonly silentSummary: boolean;
  readonly injectPreferences: boolean;
  readonly briefSnapshot: boolean;
  /** Overrides for `resolveMemoryTool` / `resolveMemoryWeb`. */
  readonly memoryToolPath?: string;
  readonly memoryWebPath?: string;
  /** Whether the config file was found — a missing one means no-memory mode. */
  readonly configFound: boolean;
}

export const DEFAULT_PI_CONFIG: UmemPiConfig = {
  gate: "message",
  detailTurnInterval: 30,
  silentSummary: false,
  injectPreferences: true,
  briefSnapshot: true,
  configFound: false,
};

function unquote(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

/** Flatten the indented `pi:` block into key → raw string value. */
export function parsePiBlock(yaml: string): Record<string, string> {
  const out: Record<string, string> = {};
  const lines = yaml.split("\n");
  let inBlock = false;
  let blockIndent = -1;

  for (const raw of lines) {
    const withoutComment = raw.replace(/(^|\s)#.*$/, "");
    if (withoutComment.trim() === "") continue;
    const indent = withoutComment.length - withoutComment.trimStart().length;

    if (!inBlock) {
      if (/^\s*pi:\s*$/.test(withoutComment)) {
        inBlock = true;
        blockIndent = indent;
      }
      continue;
    }

    // A line at or left of `pi:` ends the block.
    if (indent <= blockIndent) break;

    const match = /^\s*([A-Za-z0-9_.-]+)\s*:\s*(.*)$/.exec(withoutComment);
    if (match?.[1] !== undefined && match[2] !== undefined) {
      out[match[1]] = unquote(match[2]);
    }
  }
  return out;
}

function asBool(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) return fallback;
  const lowered = value.trim().toLowerCase();
  if (["1", "true", "yes", "on", "enabled"].includes(lowered)) return true;
  if (["0", "false", "no", "off", "disabled"].includes(lowered)) return false;
  return fallback;
}

function asPositiveInt(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 1 ? parsed : fallback;
}

export function loadPiConfig(explicit?: string): UmemPiConfig {
  const path = resolveConfigPath(explicit);
  if (path === null) return DEFAULT_PI_CONFIG;

  let yaml: string;
  try {
    yaml = readFileSync(path, "utf8");
  } catch {
    return DEFAULT_PI_CONFIG;
  }

  const block = parsePiBlock(yaml);
  const gate = block["gate"]?.trim().toLowerCase() === "off" ? "off" : "message";
  const toolPath = block["memory_tool_path"];
  const webPath = block["memory_web_path"];

  return {
    gate,
    detailTurnInterval: asPositiveInt(
      block["detail_turn_interval"],
      DEFAULT_PI_CONFIG.detailTurnInterval,
    ),
    silentSummary: asBool(block["silent_summary"], DEFAULT_PI_CONFIG.silentSummary),
    injectPreferences: asBool(
      block["inject_preferences"],
      DEFAULT_PI_CONFIG.injectPreferences,
    ),
    briefSnapshot: asBool(block["brief_snapshot"], DEFAULT_PI_CONFIG.briefSnapshot),
    ...(toolPath ? { memoryToolPath: toolPath } : {}),
    ...(webPath ? { memoryWebPath: webPath } : {}),
    configFound: true,
  };
}

/** The config directory — used to place per-machine extension state if needed. */
export function configDir(path: string | null): string | null {
  return path === null ? null : dirname(path);
}
