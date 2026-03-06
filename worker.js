import { simulateTenhouTrials } from './simulator.js';

let stopRequested = false;
let jobRunning = false;

function clampChunkSize(value) {
  if (!Number.isFinite(value)) {
    return 200000;
  }
  return Math.max(10000, Math.floor(value));
}

function runInBatches(payload) {
  const totalTrials = Math.max(0, Math.floor(payload.trials || 0));
  const chunkSize = clampChunkSize(payload.chunkSize);

  let remaining = totalTrials;
  let seed = (payload.seed >>> 0) || 2463534242;

  function step() {
    if (!jobRunning) {
      return;
    }

    if (stopRequested || remaining <= 0) {
      jobRunning = false;
      postMessage({
        type: 'done',
        stopped: stopRequested,
        remaining,
      });
      return;
    }

    const batch = remaining > chunkSize ? chunkSize : remaining;
    const startedAt = performance.now();
    const result = simulateTenhouTrials(batch, seed);
    const elapsedMs = performance.now() - startedAt;

    remaining -= result.completed;
    seed = result.seed;

    postMessage({
      type: 'batch',
      completed: result.completed,
      hits: result.hitCount,
      elapsedMs,
    });

    setTimeout(step, 0);
  }

  step();
}

self.onmessage = (event) => {
  const { data } = event;

  if (!data || typeof data.type !== 'string') {
    return;
  }

  if (data.type === 'start') {
    if (jobRunning) {
      return;
    }
    stopRequested = false;
    jobRunning = true;
    runInBatches(data);
    return;
  }

  if (data.type === 'stop') {
    stopRequested = true;
  }
};
