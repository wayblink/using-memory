/**
 * web.ts — `/umem web` without freezing the session.
 *
 * `memory-web` is a server: it serves until signalled. Awaiting it from a
 * command handler parks the whole TUI on a child that has no intention of
 * finishing — the same trap `/ukb web` hit. So it is spawned detached, its
 * banner URL is read back out of stdout, and this session owns stopping it.
 *
 * Reading the URL from the process that bound it (rather than rebuilding it
 * from `--port`) matters because uvicorn prints the address it actually got:
 * `--port 0` and an in-use port would both make a reconstructed URL wrong.
 *
 * Deliberately simpler than the kanban launcher: `memory-web` prints its banner
 * via uvicorn's logger on **stderr**, not stdout, and there is no per-launch
 * token to capture. Both differences are why this is its own module rather
 * than an import.
 */

import { spawn } from "node:child_process";

export const WEB_USAGE =
  "usage: /umem web [--port N] [--host H] [--open] | /umem web stop";

export interface WebCommand {
  readonly action: "start" | "stop";
  readonly args: readonly string[];
  readonly error: string | null;
}

export function parseWebCommand(tokens: readonly string[]): WebCommand {
  const [first, ...rest] = tokens;
  if (first === undefined || first === "") {
    return { action: "start", args: [], error: null };
  }
  if (first.toLowerCase() === "stop") {
    return rest.length === 0
      ? { action: "stop", args: [], error: null }
      : { action: "stop", args: [], error: `umem web stop takes no arguments — ${WEB_USAGE}` };
  }
  if (first.startsWith("-")) {
    return { action: "start", args: [...tokens], error: null };
  }
  return {
    action: "start",
    args: [],
    error: `unknown umem web argument: ${first} — ${WEB_USAGE}`,
  };
}

/**
 * The first http(s) URL in `text`.
 *
 * Trailing whitespace is required, not cosmetic: this runs against a growing
 * buffer, and a URL split across a chunk boundary would otherwise be reported
 * as a working address.
 */
const URL_PATTERN = /https?:\/\/[^\s]+(?=\s)/;

export function extractServerUrl(text: string): string | null {
  const match = URL_PATTERN.exec(text);
  return match === null ? null : match[0];
}

export interface WebStream {
  on(event: "data", listener: (chunk: { toString(): string }) => void): void;
  destroy(): void;
}

export interface WebChildProcess {
  readonly stdout: WebStream | null;
  readonly stderr: WebStream | null;
  onExit(listener: (code: number | null, signal: NodeJS.Signals | null) => void): void;
  onError(listener: (error: Error) => void): void;
  kill(signal?: NodeJS.Signals): boolean;
  unref(): void;
}

export type WebSpawner = (command: string, args: readonly string[]) => WebChildProcess;

export function createDetachedWebSpawner(): WebSpawner {
  return (command, args) => {
    const child = spawn(command, [...args], {
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    return {
      stdout: child.stdout,
      stderr: child.stderr,
      onExit: (listener) => {
        child.once("exit", (code, signal) => listener(code, signal));
      },
      onError: (listener) => {
        child.once("error", listener);
      },
      kill: (signal) => child.kill(signal),
      unref: () => child.unref(),
    };
  };
}

export interface WebServer {
  readonly url: string;
  readonly exited: boolean;
  stop(): Promise<void>;
}

export type WebLaunch =
  | { readonly ok: true; readonly server: WebServer }
  | { readonly ok: false; readonly error: string; readonly code: number | null };

export interface LaunchWebOptions {
  readonly command: string;
  readonly argv: readonly string[];
  readonly spawn: WebSpawner;
  readonly startTimeoutMs?: number;
  readonly stopTimeoutMs?: number;
  readonly detachDelayMs?: number;
}

const START_TIMEOUT_MS = 15_000;
const STOP_TIMEOUT_MS = 3_000;
const DETACH_DELAY_MS = 250;

type Exit = "exited" | "timeout";

export async function launchWebServer(options: LaunchWebOptions): Promise<WebLaunch> {
  const startTimeoutMs = options.startTimeoutMs ?? START_TIMEOUT_MS;
  const stopTimeoutMs = options.stopTimeoutMs ?? STOP_TIMEOUT_MS;
  const detachDelayMs = options.detachDelayMs ?? DETACH_DELAY_MS;

  let child: WebChildProcess;
  try {
    child = options.spawn(options.command, options.argv);
  } catch (error) {
    return { ok: false, error: `could not start memory-web — ${message(error)}`, code: null };
  }

  let exited = false;
  let settleExit: (code: number | null) => void = () => undefined;
  const exit = new Promise<number | null>((resolve) => {
    settleExit = resolve;
  });
  child.onExit((code) => {
    exited = true;
    settleExit(code);
  });
  child.onError(() => {
    exited = true;
    settleExit(null);
  });

  const waitForExit = async (ms: number): Promise<Exit> => {
    let timer: NodeJS.Timeout | undefined;
    const timeout = new Promise<Exit>((resolve) => {
      timer = setTimeout(() => resolve("timeout"), ms);
    });
    const result = await Promise.race([exit.then((): Exit => "exited"), timeout]);
    if (timer !== undefined) clearTimeout(timer);
    return result;
  };

  const stop = async (): Promise<void> => {
    if (exited) return;
    child.kill("SIGTERM");
    if ((await waitForExit(stopTimeoutMs)) === "timeout") {
      child.kill("SIGKILL");
      await waitForExit(1_000);
    }
  };

  const launched = await new Promise<WebLaunch>((resolve) => {
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (result: WebLaunch): void => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    // uvicorn's banner goes to stderr; a wrapper script might use either. Watch
    // both and take the first URL from whichever produces one.
    const scan = (chunk: { toString(): string }, into: "out" | "err"): void => {
      if (into === "out") stdout += chunk.toString();
      else stderr += chunk.toString();
      const url = extractServerUrl(stdout) ?? extractServerUrl(stderr);
      if (url !== null) {
        finish({
          ok: true,
          server: {
            url,
            get exited() {
              return exited;
            },
            stop,
          },
        });
      }
    };

    child.stdout?.on("data", (chunk) => scan(chunk, "out"));
    child.stderr?.on("data", (chunk) => scan(chunk, "err"));
    child.onError((error) =>
      finish({ ok: false, error: `memory-web could not start — ${error.message}`, code: null }),
    );
    child.onExit((code, signal) =>
      finish({ ok: false, error: describeExit(code, signal, stderr, stdout), code }),
    );

    const timer = setTimeout(() => {
      if (settled) return;
      // An address the user never saw is a leaked process, not a server.
      child.kill("SIGKILL");
      finish({
        ok: false,
        error: `memory-web reported no URL within ${Math.round(startTimeoutMs / 1000)}s${tail(stderr)}`,
        code: null,
      });
    }, startTimeoutMs);
    timer.unref();
  });

  if (launched.ok) {
    // The server must outlive the session, and its pipes must not hold Pi's
    // event loop open: a detached child that is still "waited for" keeps the
    // process alive on quit.
    child.unref();
    setTimeout(() => {
      child.stdout?.destroy();
      child.stderr?.destroy();
    }, detachDelayMs).unref();
  }

  return launched;
}

function describeExit(
  code: number | null,
  signal: NodeJS.Signals | null,
  stderr: string,
  stdout: string,
): string {
  const how = code !== null ? ` (code ${code})` : signal !== null ? ` (signal ${signal})` : "";
  return `memory-web exited before serving${how}${tail(stderr) || tail(stdout)}`;
}

function tail(text: string, lines = 3): string {
  const trimmed = text.trim();
  if (trimmed === "") return "";
  const recent = trimmed.split("\n").slice(-lines).join(" ").trim();
  return `: ${recent.length > 300 ? `${recent.slice(0, 297)}…` : recent}`;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
