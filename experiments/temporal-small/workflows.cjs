const { proxyActivities, defineSignal, defineQuery, setHandler, condition } = require('@temporalio/workflow');
const { fakeEffect } = proxyActivities({ startToCloseTimeout: '10 seconds',
  retry: { initialInterval: '100 milliseconds', maximumAttempts: 2 } });
const approve = defineSignal('approve');
const phase = defineQuery('phase');
async function messageLikeTask(operationId) {
  let state = 'activity';
  let approved = false;
  setHandler(approve, () => { approved = true; });
  setHandler(phase, () => state);
  const receipt = await fakeEffect(operationId);
  state = 'waiting-for-human';
  await condition(() => approved);
  state = 'finished';
  return receipt;
}
module.exports = { messageLikeTask };
