import { findPackageJSON } from "node:module";
import { readFileSync, realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { accountProviders } from "./providers.mjs";

export default async function goAccounts(pi) {
  // Pi aliases SDK roots but not provider subpaths. Resolve the import-only
  // public export relative to its running host, with no extra SDK installation.
  const manifest = findPackageJSON("@earendil-works/pi-ai", pathToFileURL(realpathSync(process.argv[1])));
  const pkg = JSON.parse(readFileSync(manifest, "utf8"));
  const target = pkg.exports["./providers/*"].import.replace("*", "opencode-go");
  const { opencodeGoProvider } = await import(new URL(target, pathToFileURL(manifest)).href);
  for (const provider of accountProviders(opencodeGoProvider())) pi.registerProvider(provider);
}
