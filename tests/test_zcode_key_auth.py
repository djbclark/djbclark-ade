"""bin/zcode-key-auth: puts zcode's account provider on the Coding Plan API key, in a scratch HOME."""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin/zcode-key-auth"
PROVIDER = "account:zai-individual-coding-plan"
KEY_NAME = f"account-provider:coding-plan:{PROVIDER}:account:u1:api-key"
SOURCE = f"account-provider:{PROVIDER}:auth-source"

# zcode's own cipher, in Node (the stdlib has no AES-GCM): encrypt/decrypt one value for a HOME.
CIPHER = r"""
const c=require("crypto"),os=require("os");
const k=c.createHash("sha256").update(`zcode-credential-fallback:${os.platform()}:${os.homedir()}:${os.userInfo().username}`).digest();
const [op,v]=process.argv.slice(1);
if(op==="enc"){const iv=c.randomBytes(12),x=c.createCipheriv("aes-256-gcm",k,iv),ct=Buffer.concat([x.update(v,"utf8"),x.final()]);
  console.log("enc:v1:"+[iv,x.getAuthTag(),ct].map(b=>b.toString("base64url")).join("."));}
else{const[a,b,u]=v.slice(7).split(".").map(p=>Buffer.from(p,"base64url"));const x=c.createDecipheriv("aes-256-gcm",k,a);
  x.setAuthTag(b);console.log(Buffer.concat([x.update(u),x.final()]).toString());}
"""


class TestZcodeKeyAuth(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="zka-"))
        (self.home / ".zcode/v2").mkdir(parents=True)
        self.cred = self.home / ".zcode/v2/credentials.json"
        self.env = {**os.environ, "HOME": str(self.home), "ZAI_CODING_PLAN_API_KEY": "vault-key-123"}
        self.env.pop("ZCODE_CREDENTIAL_SECRET", None)

    def cipher(self, op: str, value: str) -> str:
        return subprocess.run(["node", "-e", CIPHER, op, value], env=self.env, capture_output=True,
                              text=True, check=True).stdout.strip()

    def write(self, source: str, key: str) -> None:
        self.cred.write_text(json.dumps({
            "oauth:zai:access_token": "tok",
            f"account-provider:{PROVIDER}:identity": self.cipher("enc", "u1"),
            SOURCE: self.cipher("enc", source), KEY_NAME: self.cipher("enc", key)}))
        self.cred.chmod(0o600)

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(SCRIPT), *args], env=self.env, capture_output=True, text=True)

    def test_oauth_is_repaired_to_manual_with_the_vault_key(self):
        self.write("oauth", "exchanged-key")
        r = self.run_script("apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("repaired (auth-source oauth -> manual", r.stdout)
        self.assertNotIn("vault-key-123", r.stdout + r.stderr)
        d = json.loads(self.cred.read_text())
        self.assertEqual(self.cipher("dec", d[SOURCE]), "manual")
        self.assertEqual(self.cipher("dec", d[KEY_NAME]), "vault-key-123")
        self.assertEqual(d["oauth:zai:access_token"], "tok")
        self.assertEqual(self.cred.stat().st_mode & 0o777, 0o600)

    def test_already_manual_is_unchanged_and_status_matches(self):
        self.write("manual", "vault-key-123")
        before = self.cred.read_text()
        r = self.run_script("apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("unchanged", r.stdout)
        self.assertEqual(self.cred.read_text(), before)
        s = self.run_script("status")
        self.assertEqual(s.returncode, 0)
        fp = hashlib.sha256(b"vault-key-123").hexdigest()[:8]
        self.assertIn(f"auth-source=manual stored-key={fp} vault-key={fp} match=true", s.stdout)

    def test_status_fails_on_oauth(self):
        self.write("oauth", "x")
        self.assertEqual(self.run_script("status").returncode, 1)

    def test_no_identity_fails_with_a_hint(self):
        self.cred.write_text("{}")
        r = self.run_script("apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("zcode login", r.stderr)


if __name__ == "__main__":
    unittest.main()
