import { test } from "node:test";
import assert from "node:assert/strict";
import { redactPath } from "./redact.ts";

test("sensitive names are redacted per component", () => {
  for (const n of [".env", ".env.local", "a/b/server.pem", "tls.key", "id_rsa", "id_ed25519.pub", "my-secret.txt", "api_token.json", "aws-credentials", "SECRETS.md"]) {
    assert.match(redactPath(n), /\[redacted-name\]$/, n);
  }
  assert.equal(redactPath("src/.env/readme.md"), "src/[redacted-name]/readme.md");
});

test("ordinary paths are unchanged", () => {
  for (const n of ["src/app.ts", "README.md", "a/b/c.py", "./x", "../y", "tests/test_x.py"]) assert.equal(redactPath(n), n);
});

test("key-looking strings are stripped", () => {
  assert.equal(redactPath("notes-AKIAABCDEFGHIJKLMNOP.txt"), "notes-[redacted].txt");
  assert.ok(!redactPath("x/ghp_abcdefghijklmnopqrstuvwxyz0123456789.md").includes("ghp_"));
  assert.ok(!redactPath("github_pat_11ABCDEFG0abcdefghijklmnop_xyz.txt").includes("github_pat_"));
  assert.ok(!redactPath("sk-abcdefghijklmnopqrstuvwx.txt").includes("sk-abc"));
  assert.ok(!redactPath("xoxb-1234567890-abcdef.txt").includes("xoxb-1"));
  assert.equal(redactPath("a/" + "0123456789abcdef".repeat(2) + ".log"), "a/[redacted].log");
  assert.ok(!redactPath("b/" + "A".repeat(45) + ".log").includes("AAAA"));
});
