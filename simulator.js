const TILE_KIND_COUNT = 34;
const HAND_TILE_COUNT = 14;
const PHYSICAL_TILE_COUNT = 136;
const SUIT_BASE = 5;

const POW5 = new Int32Array(9);
POW5[0] = 1;
for (let i = 1; i < POW5.length; i += 1) {
  POW5[i] = POW5[i - 1] * SUIT_BASE;
}

// 5^9 states for a 9-tile suit with counts in [0..4]
const SUIT_STATE_COUNT = 1953125;
const suitMeldMemo = new Int8Array(SUIT_STATE_COUNT);
suitMeldMemo.fill(-1);
suitMeldMemo[0] = 1;

const TERMINAL_HONOR_INDICES = new Uint8Array([
  0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33,
]);

const IS_TERMINAL_OR_HONOR = new Uint8Array(TILE_KIND_COUNT);
for (const index of TERMINAL_HONOR_INDICES) {
  IS_TERMINAL_OR_HONOR[index] = 1;
}

const decodeBuffer = new Uint8Array(9);

export function tileNameToIndex(name) {
  if (typeof name !== 'string' || name.length !== 2) {
    throw new Error(`Invalid tile name: ${String(name)}`);
  }

  const num = name.charCodeAt(0) - 48;
  const suit = name.charCodeAt(1);

  // m/p/s
  if (suit === 109 || suit === 112 || suit === 115) {
    if (num < 1 || num > 9) {
      throw new Error(`Invalid suited tile: ${name}`);
    }
    if (suit === 109) {
      return num - 1;
    }
    if (suit === 112) {
      return 9 + num - 1;
    }
    return 18 + num - 1;
  }

  // honors: 1z..7z
  if (suit === 122 && num >= 1 && num <= 7) {
    return 27 + num - 1;
  }

  throw new Error(`Invalid tile name: ${name}`);
}

export function countsFromTiles(tileIndices) {
  const counts = new Uint8Array(TILE_KIND_COUNT);
  for (let i = 0; i < tileIndices.length; i += 1) {
    const idx = tileIndices[i];
    if (idx < 0 || idx >= TILE_KIND_COUNT) {
      throw new Error(`Tile index out of range: ${idx}`);
    }
    counts[idx] += 1;
    if (counts[idx] > 4) {
      throw new Error(`Tile appears more than 4 times: ${idx}`);
    }
  }
  return counts;
}

function hasCorrectTileCount(counts) {
  let total = 0;
  for (let i = 0; i < TILE_KIND_COUNT; i += 1) {
    total += counts[i];
  }
  return total === HAND_TILE_COUNT;
}

function isSevenPairs(counts) {
  let pairCount = 0;
  for (let i = 0; i < TILE_KIND_COUNT; i += 1) {
    const c = counts[i];
    if (c === 2) {
      pairCount += 1;
      continue;
    }
    if (c !== 0) {
      return false;
    }
  }
  return pairCount === 7;
}

function isKokushiMusou(counts) {
  let hasPair = false;

  for (let i = 0; i < TILE_KIND_COUNT; i += 1) {
    const c = counts[i];
    if (IS_TERMINAL_OR_HONOR[i] === 1) {
      if (c === 0) {
        return false;
      }
      if (c === 2) {
        hasPair = true;
      } else if (c !== 1) {
        return false;
      }
    } else if (c !== 0) {
      return false;
    }
  }

  return hasPair;
}

function encodeSuit(counts, offset) {
  let code = 0;
  code += counts[offset] * POW5[0];
  code += counts[offset + 1] * POW5[1];
  code += counts[offset + 2] * POW5[2];
  code += counts[offset + 3] * POW5[3];
  code += counts[offset + 4] * POW5[4];
  code += counts[offset + 5] * POW5[5];
  code += counts[offset + 6] * POW5[6];
  code += counts[offset + 7] * POW5[7];
  code += counts[offset + 8] * POW5[8];
  return code;
}

function canMeldSuitDigits(digits, start) {
  let i = start;
  while (i < 9 && digits[i] === 0) {
    i += 1;
  }

  if (i === 9) {
    return true;
  }

  if (digits[i] >= 3) {
    digits[i] -= 3;
    if (canMeldSuitDigits(digits, i)) {
      digits[i] += 3;
      return true;
    }
    digits[i] += 3;
  }

  if (i <= 6 && digits[i + 1] > 0 && digits[i + 2] > 0) {
    digits[i] -= 1;
    digits[i + 1] -= 1;
    digits[i + 2] -= 1;
    if (canMeldSuitDigits(digits, i)) {
      digits[i] += 1;
      digits[i + 1] += 1;
      digits[i + 2] += 1;
      return true;
    }
    digits[i] += 1;
    digits[i + 1] += 1;
    digits[i + 2] += 1;
  }

  return false;
}

function isSuitMeldable(code) {
  const memo = suitMeldMemo[code];
  if (memo !== -1) {
    return memo === 1;
  }

  let tmp = code;
  for (let i = 0; i < 9; i += 1) {
    decodeBuffer[i] = tmp % SUIT_BASE;
    tmp = (tmp / SUIT_BASE) | 0;
  }

  const result = canMeldSuitDigits(decodeBuffer, 0);
  suitMeldMemo[code] = result ? 1 : 0;
  return result;
}

function areMeldsOnly(counts) {
  for (let i = 27; i < TILE_KIND_COUNT; i += 1) {
    if (counts[i] % 3 !== 0) {
      return false;
    }
  }

  return (
    isSuitMeldable(encodeSuit(counts, 0)) &&
    isSuitMeldable(encodeSuit(counts, 9)) &&
    isSuitMeldable(encodeSuit(counts, 18))
  );
}

function isStandardWinningHand(counts) {
  const codeM = encodeSuit(counts, 0);
  const codeP = encodeSuit(counts, 9);
  const codeS = encodeSuit(counts, 18);

  const honorMod0 = counts[27] % 3;
  const honorMod1 = counts[28] % 3;
  const honorMod2 = counts[29] % 3;
  const honorMod3 = counts[30] % 3;
  const honorMod4 = counts[31] % 3;
  const honorMod5 = counts[32] % 3;
  const honorMod6 = counts[33] % 3;
  const honorsAllMeldable =
    honorMod0 === 0 &&
    honorMod1 === 0 &&
    honorMod2 === 0 &&
    honorMod3 === 0 &&
    honorMod4 === 0 &&
    honorMod5 === 0 &&
    honorMod6 === 0;

  for (let i = 0; i < TILE_KIND_COUNT; i += 1) {
    if (counts[i] < 2) {
      continue;
    }

    if (i < 27) {
      if (!honorsAllMeldable) {
        continue;
      }

      if (i < 9) {
        if (
          isSuitMeldable(codeM - 2 * POW5[i]) &&
          isSuitMeldable(codeP) &&
          isSuitMeldable(codeS)
        ) {
          return true;
        }
        continue;
      }

      if (i < 18) {
        if (
          isSuitMeldable(codeM) &&
          isSuitMeldable(codeP - 2 * POW5[i - 9]) &&
          isSuitMeldable(codeS)
        ) {
          return true;
        }
        continue;
      }

      if (
        isSuitMeldable(codeM) &&
        isSuitMeldable(codeP) &&
        isSuitMeldable(codeS - 2 * POW5[i - 18])
      ) {
        return true;
      }
      continue;
    }

    const honorIndex = i - 27;
    const honorPairWorks =
      (honorIndex === 0 ? honorMod0 === 2 : honorMod0 === 0) &&
      (honorIndex === 1 ? honorMod1 === 2 : honorMod1 === 0) &&
      (honorIndex === 2 ? honorMod2 === 2 : honorMod2 === 0) &&
      (honorIndex === 3 ? honorMod3 === 2 : honorMod3 === 0) &&
      (honorIndex === 4 ? honorMod4 === 2 : honorMod4 === 0) &&
      (honorIndex === 5 ? honorMod5 === 2 : honorMod5 === 0) &&
      (honorIndex === 6 ? honorMod6 === 2 : honorMod6 === 0);

    if (
      honorPairWorks &&
      isSuitMeldable(codeM) &&
      isSuitMeldable(codeP) &&
      isSuitMeldable(codeS)
    ) {
      return true;
    }
  }

  return false;
}

function isWinningHandNoCountCheck(counts) {
  return (
    isKokushiMusou(counts) ||
    isSevenPairs(counts) ||
    isStandardWinningHand(counts)
  );
}

export function isWinningHand(counts) {
  if (!hasCorrectTileCount(counts)) {
    return false;
  }

  return isWinningHandNoCountCheck(counts);
}

export function createXorShift32(seed) {
  let state = seed >>> 0;
  if (state === 0) {
    state = 2463534242;
  }

  return {
    nextUint() {
      state ^= state << 13;
      state ^= state >>> 17;
      state ^= state << 5;
      return state >>> 0;
    },
    nextInt(maxExclusive) {
      return this.nextUint() % maxExclusive;
    },
    getState() {
      return state >>> 0;
    },
  };
}

export function simulateTenhouTrials(trials, seed = Date.now() >>> 0, onProgress, progressInterval = 50000, shouldStop) {
  const rng = createXorShift32(seed >>> 0);
  const counts = new Uint8Array(TILE_KIND_COUNT);
  const usedMask = new Uint32Array(5); // enough for 136 bits
  const pickedTypes = new Uint8Array(HAND_TILE_COUNT);

  const hasStop = typeof shouldStop === 'function';
  const stopFn = typeof shouldStop === 'function' ? shouldStop : () => false;
  const progressFn = typeof onProgress === 'function' ? onProgress : null;
  const step = progressInterval > 0 ? progressInterval : trials;

  let hitCount = 0;
  let completed = 0;

  if (!progressFn && !hasStop) {
    for (let t = 0; t < trials; t += 1) {
      usedMask[0] = 0;
      usedMask[1] = 0;
      usedMask[2] = 0;
      usedMask[3] = 0;
      usedMask[4] = 0;

      let picked = 0;
      while (picked < HAND_TILE_COUNT) {
        const physicalId = rng.nextInt(PHYSICAL_TILE_COUNT);
        const wordIndex = physicalId >>> 5;
        const bitMask = 1 << (physicalId & 31);
        if ((usedMask[wordIndex] & bitMask) !== 0) {
          continue;
        }
        usedMask[wordIndex] |= bitMask;

        const tileType = physicalId >>> 2;
        pickedTypes[picked] = tileType;
        counts[tileType] += 1;
        picked += 1;
      }

      if (isWinningHandNoCountCheck(counts)) {
        hitCount += 1;
      }

      for (let i = 0; i < HAND_TILE_COUNT; i += 1) {
        counts[pickedTypes[i]] -= 1;
      }
    }
    completed = trials;
  } else {
    while (completed < trials) {
      if (stopFn()) {
        break;
      }

      usedMask[0] = 0;
      usedMask[1] = 0;
      usedMask[2] = 0;
      usedMask[3] = 0;
      usedMask[4] = 0;

      let picked = 0;
      while (picked < HAND_TILE_COUNT) {
        const physicalId = rng.nextInt(PHYSICAL_TILE_COUNT);
        const wordIndex = physicalId >>> 5;
        const bitMask = 1 << (physicalId & 31);
        if ((usedMask[wordIndex] & bitMask) !== 0) {
          continue;
        }
        usedMask[wordIndex] |= bitMask;

        const tileType = physicalId >>> 2;
        pickedTypes[picked] = tileType;
        counts[tileType] += 1;
        picked += 1;
      }

      if (isWinningHandNoCountCheck(counts)) {
        hitCount += 1;
      }

      for (let i = 0; i < HAND_TILE_COUNT; i += 1) {
        counts[pickedTypes[i]] -= 1;
      }

      completed += 1;

      if (progressFn && completed % step === 0) {
        progressFn(completed, hitCount);
      }
    }

    if (progressFn && completed % step !== 0) {
      progressFn(completed, hitCount);
    }
  }

  return {
    completed,
    hitCount,
    seed: rng.getState(),
  };
}

export const INTERNALS = {
  encodeSuit,
  isSuitMeldable,
  isKokushiMusou,
  isSevenPairs,
  isStandardWinningHand,
  hasCorrectTileCount,
  TERMINAL_HONOR_INDICES,
};
