export const quiescenceFor = s => ({ prior_revision: s.revision, prior_epoch: s.record.ownership_epoch, prior_owner: s.record.owner, processes_stopped: true, jobs_stopped: true, operations_reconciled: true });
export async function checkpoint(core, snapshot) {
  const draining = await core.transitionRole(snapshot, { state: "draining" });
  const quiescent = await core.transitionRole(draining, { state: "quiescent", quiescence: quiescenceFor(draining) });
  return core.transitionRole(quiescent, { state: "checkpointed", checkpoint_digest: "a".repeat(64) });
}
export async function handoff(core, snapshot, nextOwner) {
  const ready = await checkpoint(core, snapshot);
  return core.transferRole(ready, { priorOwner: ready.record.owner, priorEpoch: ready.record.ownership_epoch, nextOwner, quiescence: ready.record.quiescence, checkpoint_digest: ready.record.checkpoint_digest });
}
