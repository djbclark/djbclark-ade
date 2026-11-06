// Canonical JSON (sorted keys, no whitespace) and sha256, for record integrity.
// canonicalJson(x) === canonicalJson(JSON.parse(JSON.stringify(x))) for any JSON-serializable x,
// so a digest computed before writing still matches after the record is read back.

import crypto from "node:crypto";

function encode(v: unknown, seen: Set<object>, inArray: boolean): string | undefined {
  if (v !== null && typeof v === "object" && typeof (v as { toJSON?: unknown }).toJSON === "function") {
    v = (v as { toJSON: () => unknown }).toJSON();
  }
  if (v === null) return "null";
  switch (typeof v) {
    case "string":
    case "boolean":
      return JSON.stringify(v);
    case "number":
      return JSON.stringify(v); // NaN/Infinity -> "null", -0 -> "0", as JSON.stringify does
    case "bigint":
      throw new TypeError("canonicalJson: BigInt is not JSON");
    case "undefined":
    case "function":
    case "symbol":
      return inArray ? "null" : undefined;
  }
  const obj = v as object;
  if (seen.has(obj)) throw new TypeError("canonicalJson: cyclic structure");
  seen.add(obj);
  try {
    if (Array.isArray(obj)) {
      return "[" + obj.map((x) => encode(x, seen, true) as string).join(",") + "]";
    }
    const rec = obj as Record<string, unknown>;
    const parts: string[] = [];
    for (const k of Object.keys(rec).sort()) {
      const e = encode(rec[k], seen, false);
      if (e !== undefined) parts.push(JSON.stringify(k) + ":" + e);
    }
    return "{" + parts.join(",") + "}";
  } finally {
    seen.delete(obj);
  }
}

/** JSON with object keys sorted (UTF-16 code-unit order) and no whitespace. */
export function canonicalJson(v: unknown): string {
  const out = encode(v, new Set(), false);
  if (out === undefined) throw new TypeError("canonicalJson: value has no JSON form");
  return out;
}

export function sha256Hex(s: string | Buffer): string {
  return crypto.createHash("sha256").update(s).digest("hex");
}
