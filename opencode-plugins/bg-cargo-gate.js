// 2026-10-28: require bg for Cargo compilation, including release builds.
// This is an accidental-bypass guard, not a sandbox for arbitrary scripts.
const reason = "Cargo builds and tests must run through ~/ops/site-private/bin/bg (use the full path). --release is not an exemption. If bg refuses or waits, use the repo's CI route or fix the refusal; never retry bare cargo.";
const compile = new Set(["build", "b", "test", "t", "check", "c", "clippy", "bench", "run", "r", "rustc", "rustdoc", "doc", "install"]);
const wrappers = new Set(["env", "time", "nice", "nohup", "command", "exec", "rtk", "bg", "bgb"]);
const valueOptions = new Set(["--manifest-path", "--config", "--color", "--target-dir", "--lockfile-path", "-Z", "-C"]);
const basename = (s) => s.split("/").pop();
const assignment = (s) => /^[A-Za-z_][A-Za-z0-9_]*=/.test(s);

// Keep quoted arguments as arguments, so echo 'cargo build' is harmless and a
// quoted executable path remains executable. Do not inspect heredoc data.
function segments(command) {
  const lines = command.split("\n"), kept = [];
  for (let i = 0; i < lines.length; i++) {
    kept.push(lines[i]);
    const m = lines[i].match(/<<-?\s*['"]?(\w+)['"]?/);
    if (m) while (++i < lines.length && lines[i].trim() !== m[1]) {}
  }
  const result = []; let args = [], word = "", quote = "", started = false;
  const token = () => { if (started) args.push(word); word = ""; started = false; };
  const segment = () => { token(); if (args.length) result.push(args); args = []; };
  const text = kept.join("\n");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "\\" && quote !== "'") { started = true; word += text[++i] ?? ""; continue; }
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
      if (assignment(args[0]) || ["then", "do", "else", "!", "{"].includes(args[0])) { args.shift(); continue; }
      const name = basename(args[0]);
      if (!wrappers.has(name)) break;
      if (name === "bg" && /^(?:\/|~\/)/.test(args[0])) { args.length = 0; break; }
      args.shift();
      if (name === "command" && ["-v", "-V"].includes(args[0])) { args.length = 0; break; }
      while (args[0]?.startsWith("-")) {
        const option = args.shift();
        if (["-n", "-u", "--unset", "-C", "--chdir"].includes(option)) args.shift();
      }
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
    if (!compile.has(args.shift())) continue;
    const separator = args.indexOf("--");
    const options = separator < 0 ? args : args.slice(0, separator);
    if (options.some((s) => ["--help", "-h", "--version", "-V", "--list"].includes(s))) continue;
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
