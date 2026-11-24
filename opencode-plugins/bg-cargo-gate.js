// 2026-10-28: require bg for Cargo compilation, including release builds.
// This is an accidental-bypass guard, not a sandbox for arbitrary scripts.
import {realpathSync} from "node:fs";
const reason = "Cargo builds and tests must run through ~/.local/bin/bgrun (or ~/tendcf-ops/tendcf-{public,private}-<slug>/bin/bgrun or legacy ~/ops/site-private/bin/bgrun; use the full path). --release is not an exemption. If bgrun refuses or waits, use the repo's CI route or fix the refusal; never retry bare cargo.";
const compile = new Set(["build", "b", "test", "t", "check", "c", "clippy", "bench", "run", "r", "rustc", "rustdoc", "doc", "d", "install", "fix", "nextest", "miri", "llvm-cov", "package", "publish"]);
const wrappers = new Set(["env", "time", "nice", "nohup", "command", "exec", "rtk", "bgrun", "bg", "bgb", "timeout", "gtimeout", "sudo", "caffeinate", "xargs"]);
const valueOptions = new Set(["--manifest-path", "--config", "--color", "--target-dir", "--lockfile-path", "-Z", "-C"]);
const wrapperValues = {
  env: ["-u", "--unset", "-C", "--chdir", "-P"], nice: ["-n", "--adjustment"],
  time: ["-o", "-f"], exec: ["-a"],
  timeout: ["-k", "--kill-after", "-s", "--signal"], gtimeout: ["-k", "--kill-after", "-s", "--signal"],
  sudo: ["-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "-T", "-R", "--chroot", "--chdir"],
  caffeinate: ["-w", "-t"], xargs: ["-n", "-I", "-L", "-P", "-s", "-d", "-a", "-E", "-J", "-R", "-S", "--max-args", "--max-lines", "--max-procs", "--replace"],
};
const basename = (s) => s.split("/").pop();
const assignment = (s) => /^[A-Za-z_][A-Za-z0-9_]*=/.test(s);
const SITE_SLUG_RE = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;
const LEGACY_SITE_RE = /^site-[A-Za-z0-9][A-Za-z0-9._-]*$/;
const isValidSiteSlug = (slug) => slug.length > 0 && slug.length <= 64 && SITE_SLUG_RE.test(slug) && !slug.endsWith("-wt");
const isTendcfSiteDir = (name) => {
  if (name.startsWith("tendcf-public-")) return isValidSiteSlug(name.slice("tendcf-public-".length));
  if (name.startsWith("tendcf-private-")) return isValidSiteSlug(name.slice("tendcf-private-".length));
  return false;
};
const isLegacySiteDir = (name) => LEGACY_SITE_RE.test(name) && !name.endsWith("-wt");
const splitAbsParts = (raw) => {
  if (!raw || typeof raw !== "string" || !raw.startsWith("/") || raw.includes("\0") || raw.includes("//")) return null;
  const trimmed = raw.replace(/\/+$/, "");
  if (!trimmed) return null;
  const parts = trimmed.slice(1).split("/");
  if (!parts.length || parts.some((p) => p === "" || p === "." || p === "..")) return null;
  return parts;
};
const expandEnvRoot = (raw, homeParts) => {
  if (!raw || !raw.trim() || raw.includes("\0")) return null;
  if (raw === "~") return homeParts;
  if (raw.startsWith("~/")) {
    const rest = raw.slice(2);
    if (!homeParts || !rest || rest.startsWith("/")) return null;
    return splitAbsParts(`/${homeParts.join("/")}/${rest}`);
  }
  if (raw.startsWith("~")) return null;
  return splitAbsParts(raw);
};
const hasPrefix = (parts, prefix) => {
  if (!prefix || parts.length < prefix.length) return false;
  for (let i = 0; i < prefix.length; i++) {
    if (parts[i] !== prefix[i]) return false;
  }
  return true;
};
const addRootWithCanonical = (list, parts) => {
  if (!parts) return;
  const key = parts.join("/");
  if (!list.some((p) => p.join("/") === key)) list.push(parts);
  try {
    const real = realpathSync(`/${key}`);
    const realParts = splitAbsParts(real);
    if (realParts) {
      const rkey = realParts.join("/");
      if (!list.some((p) => p.join("/") === rkey)) list.push(realParts);
    }
  } catch {
    // Path may not exist on disk in static/unit-test checks; lexical root remains active.
  }
};
const getConfiguredRoots = () => {
  const homeRoots = [];
  const homeParts = splitAbsParts(process?.env?.HOME);
  addRootWithCanonical(homeRoots, homeParts);
  const tendcfRoots = [];
  if (process?.env && Object.prototype.hasOwnProperty.call(process.env, "TENDCF_OPS_ROOT")) {
    const custom = expandEnvRoot(process.env.TENDCF_OPS_ROOT, homeParts);
    if (custom) {
      addRootWithCanonical(tendcfRoots, custom);
      for (const h of homeRoots) addRootWithCanonical(tendcfRoots, [...h, "tendcf-ops"]);
    }
  } else {
    for (const h of homeRoots) addRootWithCanonical(tendcfRoots, [...h, "tendcf-ops"]);
  }
  const legacyRoots = [];
  if (process?.env?.OPS_ROOT) {
    const customLegacy = expandEnvRoot(process.env.OPS_ROOT, homeParts);
    addRootWithCanonical(legacyRoots, customLegacy);
  }
  for (const h of homeRoots) addRootWithCanonical(legacyRoots, [...h, "ops"]);
  return {homeParts, homeRoots, tendcfRoots, legacyRoots};
};
const matchesAnchoredOpsRoots = (absParts) => {
  const {tendcfRoots, legacyRoots} = getConfiguredRoots();
  for (const root of tendcfRoots) {
    if (absParts.length === root.length + 3 && hasPrefix(absParts, root)
        && absParts[root.length + 1] === "bin" && isTendcfSiteDir(absParts[root.length])) {
      return true;
    }
  }
  for (const root of legacyRoots) {
    if (absParts.length === root.length + 3 && hasPrefix(absParts, root)
        && absParts[root.length + 1] === "bin" && isLegacySiteDir(absParts[root.length])) {
      return true;
    }
  }
  return false;
};
const fullBg = (s) => {
  if (typeof s !== "string" || !s || s.includes("\0") || /\s/.test(s)) return false;
  let rel = null;
  for (const prefix of ["~/", "$HOME/", "${HOME}/"]) {
    if (s.startsWith(prefix)) { rel = s.slice(prefix.length); break; }
  }
  if (rel !== null) {
    if (!rel || rel.startsWith("/")) return false;
    const parts = rel.split("/");
    if (parts.some((p) => p === "" || p === "." || p === "..")) return false;
    const exe = parts[parts.length - 1];
    if (exe !== "bgrun" && exe !== "bg") return false;
    if (parts.length === 3 && parts[0] === ".local" && parts[1] === "bin") return true;
    if (parts.length === 4 && parts[0] === "tendcf-ops" && parts[2] === "bin") return isTendcfSiteDir(parts[1]);
    if (parts.length === 4 && parts[0] === "ops" && parts[2] === "bin") return isLegacySiteDir(parts[1]);
    const {homeParts} = getConfiguredRoots();
    return homeParts ? matchesAnchoredOpsRoots([...homeParts, ...parts]) : false;
  }
  const parts = splitAbsParts(s);
  if (!parts) return false;
  const exe = parts[parts.length - 1];
  if (exe !== "bgrun" && exe !== "bg") return false;
  const {homeRoots} = getConfiguredRoots();
  for (const h of homeRoots) {
    if (parts.length === h.length + 3 && hasPrefix(parts, h)
        && parts[h.length] === ".local" && parts[h.length + 1] === "bin") {
      return true;
    }
  }
  return matchesAnchoredOpsRoots(parts);
};

function heredocs(line, state) {
  const result = []; let {quote, arithmetic} = state;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "\\" && quote !== "'") { i++; continue; }
    if (quote) { if (c === quote) quote = ""; continue; }
    if (c === "'" || c === '"') { quote = c; continue; }
    if (c === "#" && (i === 0 || /\s/.test(line[i - 1]))) break;
    if (line.slice(i, i + 3) === "$((") { arithmetic++; i += 2; continue; }
    if (!arithmetic && line.slice(i, i + 2) === "((") { arithmetic++; i++; continue; }
    if (arithmetic) { if (line.slice(i, i + 2) === "))") { arithmetic--; i++; } continue; }
    if (c !== "<" || line[i - 1] === "<" || line[i + 2] === "<") continue;
    const m = line.slice(i).match(/^<<(-?)\s*\\?(['"]?)([A-Za-z_][\w-]*)\2(?=\s|;|$)/);
    if (m) { result.push({delimiter: m[3], tabs: m[1] === "-"}); i += m[0].length - 1; }
  }
  Object.assign(state, {quote, arithmetic}); return result;
}

// Keep quoted arguments as arguments, so echo 'cargo build' is harmless and a
// quoted executable path remains executable. Do not inspect heredoc data.
function segments(command) {
  const lines = command.split("\n"), kept = [], state = {quote: "", arithmetic: 0};
  for (let i = 0; i < lines.length; i++) {
    kept.push(lines[i]);
    for (const h of heredocs(lines[i], state)) {
      while (++i < lines.length && (h.tabs ? lines[i].replace(/^\t+/, "") : lines[i]) !== h.delimiter) {}
    }
  }
  const result = []; let args = [], word = "", quote = "", started = false;
  const token = () => { if (started) args.push(word); word = ""; started = false; };
  const segment = () => { token(); if (args.length) result.push(args); args = []; };
  const text = kept.join("\n");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "\\" && quote !== "'") {
      if (text[i + 1] === "\n") { i++; continue; }
      started = true; word += text[++i] ?? ""; continue;
    }
    if (quote) { if (c === quote) quote = ""; else word += c; continue; }
    if (c === "'" || c === '"') { quote = c; started = true; continue; }
    if (c === "#" && !started) { while (i < text.length && text[i] !== "\n") i++; segment(); continue; }
    if (";|&()\n".includes(c)) { segment(); continue; }
    if (/\s/.test(c)) { token(); continue; }
    word += c; started = true;
  }
  segment(); return result;
}

export function requiresBg(command, depth = 0) {
  if (typeof command !== "string" || depth > 4) return false;
  for (const original of segments(command)) {
    const args = [...original];
    while (args.length) {
      if (assignment(args[0]) || ["if", "elif", "while", "until", "then", "do", "else", "!", "{"].includes(args[0])) { args.shift(); continue; }
      const name = basename(args[0]);
      if (name === "rustup" && args[1] === "run") {
        args.splice(0, 2); if (args[0] === "--install") args.shift(); args.shift();
        if (args[0] === "--") args.shift(); continue;
      }
      if (!wrappers.has(name) && !/^bgrun/.test(name)) break;
      if (["bgrun", "bg"].includes(name) && fullBg(args[0])) { args.length = 0; break; }
      args.shift();
      if (name === "command" && ["-v", "-V"].includes(args[0])) { args.length = 0; break; }
      if (name === "rtk") {
        while (args[0]?.startsWith("-")) args.shift();
        const runner = ["test", "err", "run", "proxy", "bypass", "summary"].includes(args[0]) ? args.shift() : null;
        let shellMode = false;
        if (runner) {
          while (args[0]?.startsWith("-")) {
            const option = args.shift();
            if (["-c", "--command"].includes(option) || option.startsWith("--command=") || /^-c./.test(option)) {
              const text = option.startsWith("--command=") ? option.slice(10) : /^-c./.test(option) ? option.slice(2) : args.shift();
              if (requiresBg(text, depth + 1)) return true;
              args.length = 0; break;
            }
            if (option === "--shell" || option.startsWith("--shell=")) {
              if (option === "--shell") args.shift();
              shellMode = true;
            }
          }
          if (shellMode && runner !== "run" && args.length) {
            if (requiresBg(args[0], depth + 1)) return true;
            args.length = 0;
          }
        }
      }
      while (args[0]?.startsWith("-")) {
        const option = args.shift();
        if (name === "env" && ["-S", "--split-string"].includes(option)) {
          args.unshift(...segments(args.shift() ?? "").flat()); break;
        }
        if ((wrapperValues[name] ?? []).includes(option)) args.shift();
      }
      if (["timeout", "gtimeout"].includes(name)) args.shift();
    }
    if (!args.length) continue;
    if (["bash", "sh", "zsh"].includes(basename(args[0]))) {
      const i = args.findIndex((s) => /^-[^-]*c/.test(s));
      if (i > 0 && requiresBg(args[i + 1], depth + 1)) return true;
      continue;
    }
    if (basename(args.shift()) !== "cargo") continue;
    while (args.length && (args[0].startsWith("-") || args[0].startsWith("+"))) {
      const option = args.shift();
      if (valueOptions.has(option)) args.shift();
    }
    const subcommand = args.shift();
    if (!compile.has(subcommand)) continue;
    const separator = args.indexOf("--");
    const options = separator < 0 ? args : args.slice(0, separator);
    if (options.some((s) => ["--help", "-h"].includes(s))
      || (subcommand !== "install" && options.some((s) => ["--version", "-V"].includes(s)))
      || (subcommand === "install" && options.includes("--list"))) continue;
    return true;
  }
  return false;
}

export default {
  id: "ade.bg-cargo-gate",
  async setup(ctx) {
    if (typeof ctx?.permission?.hook !== "function") {
      throw new Error("ade.bg-cargo-gate needs the native OpenCode V2 permission hook");
    }
    const registration = await ctx.permission.hook("evaluate", (event) => {
      if (event.action !== "shell") return;
      if ((event.resources ?? []).some((resource) => requiresBg(resource))) {
        event.effect = "deny";
        event.message = reason;
      }
    });
    return async () => { await registration?.dispose(); };
  },
};
