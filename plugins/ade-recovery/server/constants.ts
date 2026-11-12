// Constants shared by the ade-recovery modules (issue 278).
// SCHEMA is the one value types.ts exports; it is re-exported here so value imports have one home.

export { SCHEMA } from "./types.ts";

export const PLUGIN_ID = "ade-recovery";

/** Caps on the record's lists (the writer trims; readers tolerate any length). */
export const MAX_TURNS = 20;
export const MAX_INTERRUPTIONS = 20;
export const MAX_PATHS = 200;
/** A serialized record larger than this is refused by the writer and rejected by the reader. */
export const MAX_RECORD_BYTES = 262144;

/** File names inside a state root. */
export const LOCK_FILE = "writer.lock";
export const TMP_PREFIX = ".tmp-";
/** sweepTmp removes only `.tmp-*` files older than this. */
export const TMP_SWEEP_AGE_MS = 10 * 60 * 1000;

/** Deterministic crash points of the generation write (honoured only when ADE_RECOVERY_TEST=1). */
export const CRASH_POINTS = [
  "after-tmp-write",
  "after-tmp-sync",
  "after-prev-link",
  "after-prev-rename",
  "after-rename",
] as const;
export type CrashPoint = (typeof CRASH_POINTS)[number];

/**
 * The plugin's version (the Paseo manifest has none). A literal, not read from package.json at load
 * time: Paseo bundles server code as CommonJS and evaluates it, where `import.meta.url` is absent
 * (compiler-build.ts, bundle-evaluator.ts). constants.test.ts keeps it equal to package.json.
 */
export const PLUGIN_VERSION: string = "0.1.0";
