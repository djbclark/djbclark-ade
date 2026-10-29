// 2026-10-28: require bg for Cargo compilation, including release builds.
// This is an accidental-bypass guard, not a sandbox for arbitrary scripts.
const reason = "Cargo builds and tests must run through ~/ops/site-private/bin/bg (use the full path). --release is not an exemption. If bg refuses or waits, use the repo's CI route or fix the refusal; never retry bare cargo.";
const compile = new Set(["build", "b", "test", "t", "check", "c", "clippy", "bench", "run", "r", "rustc", "rustdoc", "doc", "d", "install", "fix", "nextest", "miri", "llvm-cov", "package", "publish"]);
const wrappers = new Set(["env", "time", "nice", "nohup", "command", "exec", "rtk", "bg", "bgb", "timeout", "gtimeout", "sudo", "caffeinate", "xargs"]);
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
const fullBg = (s) => /^(?:~|\$HOME|\$\{HOME\})\/ops\/(?:site-private|site-djbclark)\/bin\/bg$/.test(s)
  || /^\/(?:[^/\s]+\/)*ops\/(?:site-private|site-djbclark)\/bin\/bg$/.test(s);

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
      if (!wrappers.has(name)) break;
      if (name === "bg" && fullBg(args[0])) { args.length = 0; break; }
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
