import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createInitialState,
  getFragmentGroupByTier,
  openFragmentBox,
  playTicket,
  getHighestTierWithTicket,
  createSeededRng,
  addTicket,
} from '../tower-engine.js';

function scriptedRng(values) {
  let i = 0;
  return () => {
    const value = values[Math.min(i, values.length - 1)];
    i += 1;
    return value;
  };
}

test('tier to fragment group mapping is correct at boundaries', () => {
  assert.equal(getFragmentGroupByTier(1), 'A');
  assert.equal(getFragmentGroupByTier(5), 'A');
  assert.equal(getFragmentGroupByTier(6), 'S');
  assert.equal(getFragmentGroupByTier(8), 'S');
  assert.equal(getFragmentGroupByTier(9), 'SS');
  assert.equal(getFragmentGroupByTier(13), 'SS');
  assert.equal(getFragmentGroupByTier(14), 'SSS');
  assert.equal(getFragmentGroupByTier(18), 'SSS');
});

test('single run can promote tier and update highest tier', () => {
  const state = createInitialState();
  state.tickets.single[1] = 1;

  // 0.01 -> continue single, 0.95 -> +2 tier
  const result = playTicket(state, 'single', 1, scriptedRng([0.01, 0.95, 0.99, 0.99]));

  assert.equal(result.ok, true);
  assert.equal(state.tickets.single[3], 1);
  assert.equal(state.stats.highestReached, 3);
  assert.equal(state.stats.breakCount, 0);
});

test('single run can break the chain at high tier', () => {
  const state = createInitialState();
  state.tickets.single[1] = 0;
  state.tickets.single[16] = 1;

  // 0.99 -> exceed continue chance, becomes break
  const result = playTicket(state, 'single', 16, scriptedRng([0.99]));

  assert.equal(result.ok, true);
  assert.equal(result.outcome, 'break');
  assert.equal(state.stats.breakCount, 1);
  assert.equal(getHighestTierWithTicket(state, 'single'), 0);
});

test('opening SSS fragment box always yields 14-18 ticket and consumes fragments', () => {
  const state = createInitialState();
  state.fragments.SSS = 12;

  const result = openFragmentBox(state, 'SSS', scriptedRng([0.0]));

  assert.equal(result.ok, true);
  assert.equal(result.ticket.type, 'single');
  assert.ok(result.ticket.tier >= 14 && result.ticket.tier <= 18);
  assert.equal(state.fragments.SSS, 2);
});

test('opening SSS box can record fallback from historical peak', () => {
  const state = createInitialState();
  state.fragments.SSS = 20;
  state.stats.highestReached = 18;

  // For SSS weights this should pick 14
  const result = openFragmentBox(state, 'SSS', scriptedRng([0.1]));

  assert.equal(result.ok, true);
  assert.equal(result.ticket.tier, 14);
  assert.equal(state.stats.highTierFallbackCount, 1);
});

test('seeded rng is deterministic', () => {
  const a = createSeededRng(42);
  const b = createSeededRng(42);

  const seqA = [a(), a(), a(), a(), a()];
  const seqB = [b(), b(), b(), b(), b()];

  assert.deepEqual(seqA, seqB);
});

test('addTicket clamps tier in legal range', () => {
  const state = createInitialState();

  addTicket(state, 'single', 99, 1);
  addTicket(state, 'single', -5, 1);

  assert.equal(state.tickets.single[18], 1);
  assert.equal(state.tickets.single[1], 2);
});
