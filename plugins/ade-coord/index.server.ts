import { contribute } from "./server/hook.mjs";

// Paseo eagerly copies CommonJS exports before module initialization completes.
// A hoisted default function remains available at that point.
export default function contributeAdeCoord(server: Parameters<typeof contribute>[0]) {
  return contribute(server);
}
