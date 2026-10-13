// autorename bridge for omp (djbclark-ade/skills/autorename/omp-bridge.ts).
//
// omp keeps a live session's title in memory and holds a write lease on its
// session file, so an outside writer would make omp move the session to a
// sibling file rather than rename it. autorename.py therefore asks the running
// omp to rename itself through this extension:
//
//   <state>/omp/<pid>.json            this omp's {pid, session_id, session_file}
//   <state>/omp/<pid>.request.json    {"title": ..., "nonce": ...} from autorename.py
//   <state>/omp/<pid>.result.<nonce>.json   {"accepted": bool, "error": ...} written back
//
// <state> is $AUTORENAME_STATE_DIR or ~/.local/state/autorename. autorename.py
// finds <pid> as the nearest `omp` process above itself (omp runs bash-tool
// commands in-process, so that is the session's own process).
// Installed as a symlink in ~/.omp/agent/extensions/ (auto-discovered at startup).
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const NONCE = /^[A-Za-z0-9_-]{1,64}$/;

// The slice of omp's extension API this bridge uses. No package import: the
// module loads inside omp with no dependencies (same choice as Orca's extensions).
interface Ctx {
  sessionManager?: { getSessionId?: () => unknown; getSessionFile?: () => unknown };
  setInterval: (callback: () => unknown, ms: number) => unknown;
}
interface Pi {
  on(event: string, handler: (event: unknown, ctx: Ctx) => unknown): void;
  setSessionName(name: string, source?: "auto" | "user"): Promise<unknown>;
}

function writeJson(file: string, data: unknown): void {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data), { mode: 0o600 });
  fs.renameSync(tmp, file);
}

export default function (pi: Pi) {
  const root = process.env.AUTORENAME_STATE_DIR || path.join(os.homedir(), ".local/state/autorename");
  const dir = path.join(root, "omp");
  const registry = path.join(dir, `${process.pid}.json`);
  const request = path.join(dir, `${process.pid}.request.json`);
  let timer: unknown;
  let current: Ctx | undefined;

  function publish(ctx: Ctx | undefined): void {
    const manager = ctx?.sessionManager;
    const id = manager?.getSessionId?.();
    if (typeof id !== "string" || !id) return;
    const file = manager?.getSessionFile?.();
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    writeJson(registry, {
      pid: process.pid,
      session_id: id,
      session_file: typeof file === "string" ? file : null,
      updated_at: new Date().toISOString(),
    });
  }

  async function serve(): Promise<void> {
    let raw: string;
    try {
      raw = fs.readFileSync(request, "utf8");
    } catch {
      return; // no pending request
    }
    fs.rmSync(request, { force: true });
    let body: unknown;
    try {
      body = JSON.parse(raw);
    } catch {}
    const field = (key: string): string =>
      body && typeof body === "object" && key in body && typeof (body as Record<string, unknown>)[key] === "string"
        ? String((body as Record<string, unknown>)[key])
        : "";
    const nonce = field("nonce");
    if (!NONCE.test(nonce)) return;
    const title = field("title").trim();
    const result: Record<string, unknown> = { nonce, title, accepted: false, error: null };
    try {
      if (!title) throw new Error("empty title");
      // "user": omp's automatic titling must not overwrite it afterwards.
      result.accepted = (await pi.setSessionName(title, "user")) !== false;
      publish(current);
    } catch (err) {
      result.error = err instanceof Error ? err.message : String(err);
    }
    writeJson(path.join(dir, `${process.pid}.result.${nonce}.json`), result);
  }

  pi.on("session_start", (_event, ctx) => {
    current = ctx;
    publish(ctx);
    if (timer === undefined) timer = ctx.setInterval(serve, 1000);
  });
  pi.on("session_switch", (_event, ctx) => {
    current = ctx;
    publish(ctx);
  });
  pi.on("session_shutdown", () => {
    fs.rmSync(registry, { force: true });
    fs.rmSync(request, { force: true });
  });
}
