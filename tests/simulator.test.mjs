import test from 'node:test';
import assert from 'node:assert/strict';

import {
  isWinningHand,
  countsFromTiles,
  tileNameToIndex,
} from '../simulator.js';

function handFromNames(names) {
  return countsFromTiles(names.map(tileNameToIndex));
}

test('detects standard winning hand', () => {
  // 123m 123m 123p 456s 77z
  const counts = handFromNames([
    '1m', '2m', '3m',
    '1m', '2m', '3m',
    '1p', '2p', '3p',
    '4s', '5s', '6s',
    '7z', '7z',
  ]);

  assert.equal(isWinningHand(counts), true);
});

test('detects seven pairs', () => {
  // 1122m 3344p 5566s 77z
  const counts = handFromNames([
    '1m', '1m', '2m', '2m',
    '3p', '3p', '4p', '4p',
    '5s', '5s', '6s', '6s',
    '7z', '7z',
  ]);

  assert.equal(isWinningHand(counts), true);
});

test('detects kokushi musou', () => {
  // 19m19p19s1234567z + 1m
  const counts = handFromNames([
    '1m', '9m',
    '1p', '9p',
    '1s', '9s',
    '1z', '2z', '3z', '4z', '5z', '6z', '7z',
    '1m',
  ]);

  assert.equal(isWinningHand(counts), true);
});

test('rejects non-winning hand', () => {
  const counts = handFromNames([
    '1m', '1m', '1m',
    '2m', '2m', '2m',
    '3m', '3m', '3m',
    '4m', '5m', '6m',
    '7m', '9m',
  ]);

  assert.equal(isWinningHand(counts), false);
});

test('tile parser maps all tile kinds', () => {
  assert.equal(tileNameToIndex('1m'), 0);
  assert.equal(tileNameToIndex('9m'), 8);
  assert.equal(tileNameToIndex('1p'), 9);
  assert.equal(tileNameToIndex('9p'), 17);
  assert.equal(tileNameToIndex('1s'), 18);
  assert.equal(tileNameToIndex('9s'), 26);
  assert.equal(tileNameToIndex('1z'), 27);
  assert.equal(tileNameToIndex('7z'), 33);
});
