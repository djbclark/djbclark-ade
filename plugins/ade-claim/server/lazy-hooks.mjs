/** Compatibility selection is DATA. Native namespace isolation is independent.
 * Loaders are fixed source closures supplied by the entry, never event input.
 * No imports, helpers or async contribution work occur during registration.
 */
export function registerLazyHooks(server, names, { ordinary, selected }) {
  const managed = server.managedSource;
  if (managed !== undefined && typeof managed !== "boolean")
    throw new Error("Invalid native managedSource classification");
  if (managed === true && typeof server.sourceDirectory !== "string")
    throw new Error("Managed source directory is required");
  const load = managed === true ? selected : ordinary;
  let handlers;
  let disposed = false;
  const offs = [];
  try {
    for (const name of names) offs.push(server.addHook(name, async (input, context) => {
      if (disposed) return;
      // A rejected load stays rejected. Never retry another route after failure.
      handlers ??= Promise.resolve().then(load);
      const callbacks = await handlers;
      if (disposed) return;
      if (typeof callbacks?.[name] !== "function") throw new Error("Missing ADE hook callback");
      return await callbacks[name](input, context);
    }));
  } catch (error) {
    disposed = true;
    offs.forEach((off) => off());
    throw error;
  }
  return () => {
    if (disposed) return;
    disposed = true;
    offs.forEach((off) => off());
  };
}
