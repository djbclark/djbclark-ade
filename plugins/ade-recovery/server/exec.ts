// Hardened subprocess runner: argv arrays only, a from-scratch environment, hard timeouts.
// Used by git-evidence.ts and by the paseo-checkpoint CLI (critique finding 6 and 15).
import { spawn } from "node:child_process";

export interface RunOptions {
  cwd?: string;
  timeoutMs: number;
  signal?: AbortSignal;
  maxBuffer?: number; // bytes of stdout kept before the child is killed (default 16 MiB)
  input?: string | Buffer;
}

export interface RunResult {
  /** Exit code; -1 when the process did not exit normally (spawn failure, timeout, abort, overflow, signal). */
  code: number;
  stdout: Buffer;
  stderr: string;
  timedOut: boolean;
  aborted: boolean;
  overflow: boolean;
}

/** The only environment a child ever sees. No GIT_DIR, GIT_INDEX_FILE or GIT_CONFIG_* is inherited. */
export function cleanEnv(src: NodeJS.ProcessEnv = process.env): Record<string, string> {
  const env: Record<string, string> = {
    PATH: src.PATH ?? "/usr/local/bin:/usr/bin:/bin",
    LC_ALL: "C",
    GIT_OPTIONAL_LOCKS: "0",
    GIT_TERMINAL_PROMPT: "0",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_PAGER: "cat",
  };
  if (src.HOME !== undefined) env.HOME = src.HOME;
  return env;
}

const DEFAULT_MAX_BUFFER = 16 * 1024 * 1024;
const STDERR_CAP = 64 * 1024;

export function run(cmd: string, args: string[], opts: RunOptions): Promise<RunResult> {
  return new Promise((resolve) => {
    const maxBuffer = opts.maxBuffer ?? DEFAULT_MAX_BUFFER;
    const out: Buffer[] = [];
    let outBytes = 0;
    let err = "";
    let timedOut = false;
    let aborted = false;
    let overflow = false;
    let settled = false;
    let child: ReturnType<typeof spawn>;

    const finish = (code: number) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      opts.signal?.removeEventListener("abort", onAbort);
      resolve({ code, stdout: Buffer.concat(out), stderr: err, timedOut, aborted, overflow });
    };

    const kill = () => {
      try {
        child?.kill("SIGKILL");
      } catch {
        /* already gone */
      }
    };
    const onAbort = () => {
      aborted = true;
      kill();
    };
    const timer = setTimeout(() => {
      timedOut = true;
      kill();
    }, Math.max(1, opts.timeoutMs));

    if (opts.signal?.aborted) {
      aborted = true;
      finish(-1);
      return;
    }

    try {
      child = spawn(cmd, args, {
        cwd: opts.cwd,
        env: cleanEnv(),
        stdio: ["pipe", "pipe", "pipe"],
        shell: false,
        windowsHide: true,
      });
    } catch (e) {
      err = `spawn failed: ${(e as Error).message}`;
      finish(-1);
      return;
    }
    opts.signal?.addEventListener("abort", onAbort, { once: true });

    child.on("error", (e) => {
      err += `spawn error: ${(e as NodeJS.ErrnoException).code ?? e.message}`;
      finish(-1);
    });
    child.stdout!.on("data", (b: Buffer) => {
      if (overflow) return;
      outBytes += b.length;
      if (outBytes > maxBuffer) {
        overflow = true;
        kill();
        return;
      }
      out.push(b);
    });
    child.stderr!.on("data", (b: Buffer) => {
      if (err.length < STDERR_CAP) err += b.toString("utf8").slice(0, STDERR_CAP - err.length);
    });
    child.on("close", (code) => {
      finish(timedOut || aborted || overflow || code === null ? -1 : code);
    });

    child.stdin!.on("error", () => {
      /* child exited before reading input */
    });
    if (opts.input !== undefined) child.stdin!.end(opts.input);
    else child.stdin!.end();
  });
}
