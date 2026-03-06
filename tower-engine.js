const MIN_TIER = 1;
const MAX_TIER = 18;
const BOX_COST = 10;

const FRAGMENT_GROUPS = ['A', 'S', 'SS', 'SSS'];

const GROUP_TIERS = {
  A: [3, 4, 5],
  S: [6, 7, 8],
  SS: [9, 10, 11, 12, 13],
  SSS: [14, 15, 16, 17, 18],
};

const BOX_WEIGHTS = {
  A: [0.46, 0.34, 0.2],
  S: [0.46, 0.34, 0.2],
  SS: [0.38, 0.27, 0.18, 0.11, 0.06],
  SSS: [0.5, 0.23, 0.14, 0.09, 0.04],
};

function clampTier(tier) {
  if (!Number.isFinite(tier)) {
    return MIN_TIER;
  }
  return Math.max(MIN_TIER, Math.min(MAX_TIER, Math.floor(tier)));
}

function makeTierArray() {
  return new Uint32Array(MAX_TIER + 1);
}

export function createSeededRng(seed = Date.now()) {
  let state = (seed >>> 0) || 0x9e3779b9;
  return () => {
    state += 0x6d2b79f5;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function createInitialState() {
  const state = {
    tickets: {
      single: makeTierArray(),
      party: makeTierArray(),
      trial: makeTierArray(),
    },
    fragments: {
      A: 0,
      S: 0,
      SS: 0,
      SSS: 0,
    },
    stats: {
      rounds: 0,
      breakCount: 0,
      highTierFallbackCount: 0,
      highestReached: 1,
      lastPlayedTier: 0,
      lastPlayedType: '',
    },
  };

  state.tickets.single[1] = 1;
  return state;
}

export function getFragmentGroupByTier(tier) {
  const t = clampTier(tier);
  if (t <= 5) {
    return 'A';
  }
  if (t <= 8) {
    return 'S';
  }
  if (t <= 13) {
    return 'SS';
  }
  return 'SSS';
}

function getContinueChanceByTier(tier) {
  if (tier <= 5) {
    return 0.92;
  }
  if (tier <= 8) {
    return 0.84;
  }
  if (tier <= 11) {
    return 0.72;
  }
  if (tier <= 13) {
    return 0.6;
  }
  if (tier === 14) {
    return 0.5;
  }
  if (tier === 15) {
    return 0.44;
  }
  if (tier === 16) {
    return 0.35;
  }
  if (tier === 17) {
    return 0.28;
  }
  return 0.22;
}

function addFragment(state, tier, quantity) {
  const group = getFragmentGroupByTier(tier);
  state.fragments[group] += quantity;
  return group;
}

function pickWeightedIndex(weights, rng) {
  const x = rng();
  let acc = 0;
  for (let i = 0; i < weights.length; i += 1) {
    acc += weights[i];
    if (x <= acc) {
      return i;
    }
  }
  return weights.length - 1;
}

function dropSingleTierFromSingleRun(playedTier, rng) {
  const tier = clampTier(playedTier);

  if (tier <= 13) {
    const roll = rng();
    if (roll < 0.58) {
      return tier;
    }
    if (roll < 0.9) {
      return clampTier(tier + 1);
    }
    return clampTier(tier + 2);
  }

  if (tier === 14) {
    const roll = rng();
    if (roll < 0.5) {
      return 14;
    }
    if (roll < 0.84) {
      return 15;
    }
    if (roll < 0.95) {
      return 16;
    }
    return 13;
  }

  if (tier === 15) {
    const roll = rng();
    if (roll < 0.5) {
      return 15;
    }
    if (roll < 0.77) {
      return 16;
    }
    if (roll < 0.87) {
      return 17;
    }
    return 14;
  }

  if (tier === 16) {
    const roll = rng();
    if (roll < 0.46) {
      return 16;
    }
    if (roll < 0.68) {
      return 17;
    }
    if (roll < 0.76) {
      return 18;
    }
    if (roll < 0.9) {
      return 15;
    }
    return 14;
  }

  if (tier === 17) {
    const roll = rng();
    if (roll < 0.43) {
      return 17;
    }
    if (roll < 0.61) {
      return 18;
    }
    if (roll < 0.77) {
      return 16;
    }
    if (roll < 0.91) {
      return 15;
    }
    return 14;
  }

  // tier 18
  {
    const roll = rng();
    if (roll < 0.36) {
      return 18;
    }
    if (roll < 0.57) {
      return 17;
    }
    if (roll < 0.74) {
      return 16;
    }
    if (roll < 0.88) {
      return 15;
    }
    return 14;
  }
}

function dropExtraTicket(state, playedTier, rng) {
  const tier = clampTier(playedTier);
  const out = [];

  // Group/Trial tickets mainly act as fragment generation channels.
  const partyChance = tier <= 8 ? 0.34 : tier <= 13 ? 0.28 : 0.22;
  const trialChance = tier <= 8 ? 0.06 : tier <= 13 ? 0.1 : 0.14;

  if (rng() < partyChance) {
    addTicket(state, 'party', tier, 1);
    out.push({ type: 'party', tier });
  }

  if (rng() < trialChance) {
    const trialTier = tier >= 16 ? tier : clampTier(tier + 1);
    addTicket(state, 'trial', trialTier, 1);
    out.push({ type: 'trial', tier: trialTier });
  }

  return out;
}

export function addTicket(state, ticketType, tier, count = 1) {
  const t = clampTier(tier);
  const c = Math.max(0, Math.floor(count));
  if (!state.tickets[ticketType]) {
    throw new Error(`Unknown ticket type: ${ticketType}`);
  }
  state.tickets[ticketType][t] += c;
}

function consumeTicket(state, ticketType, tier) {
  const t = clampTier(tier);
  if (!state.tickets[ticketType]) {
    throw new Error(`Unknown ticket type: ${ticketType}`);
  }
  if (state.tickets[ticketType][t] <= 0) {
    return false;
  }
  state.tickets[ticketType][t] -= 1;
  return true;
}

export function getHighestTierWithTicket(state, ticketType) {
  if (!state.tickets[ticketType]) {
    throw new Error(`Unknown ticket type: ${ticketType}`);
  }
  const arr = state.tickets[ticketType];
  for (let t = MAX_TIER; t >= MIN_TIER; t -= 1) {
    if (arr[t] > 0) {
      return t;
    }
  }
  return 0;
}

export function playTicket(state, ticketType, tier, rng = Math.random) {
  const t = clampTier(tier);
  if (!consumeTicket(state, ticketType, t)) {
    return {
      ok: false,
      message: `没有${t}阶${ticketType}票`,
    };
  }

  state.stats.rounds += 1;
  state.stats.lastPlayedTier = t;
  state.stats.lastPlayedType = ticketType;

  if (ticketType === 'single') {
    const contChance = getContinueChanceByTier(t);
    const continueRoll = rng();

    if (continueRoll > contChance) {
      const extras = dropExtraTicket(state, t, rng);
      state.stats.breakCount += 1;
      return {
        ok: true,
        outcome: 'break',
        played: { type: 'single', tier: t },
        rewards: extras,
        message: `${t}阶单人通关，但断票了。`,
      };
    }

    const droppedTier = dropSingleTierFromSingleRun(t, rng);
    addTicket(state, 'single', droppedTier, 1);

    if (droppedTier < t && t >= 14) {
      state.stats.highTierFallbackCount += 1;
    }

    if (droppedTier > state.stats.highestReached) {
      state.stats.highestReached = droppedTier;
    }

    const extras = dropExtraTicket(state, t, rng);
    return {
      ok: true,
      outcome: droppedTier > t ? 'up' : droppedTier < t ? 'down' : 'same',
      played: { type: 'single', tier: t },
      ticket: { type: 'single', tier: droppedTier },
      rewards: extras,
      message: `${t}阶单人通关，获得${droppedTier}阶单人票。`,
    };
  }

  if (ticketType === 'party') {
    const base = t >= 14 ? 2 : 1;
    const bonus = rng() < (t >= 14 ? 0.35 : 0.18) ? 1 : 0;
    const quantity = base + bonus;
    const group = addFragment(state, t, quantity);

    return {
      ok: true,
      outcome: 'fragment',
      played: { type: 'party', tier: t },
      fragment: { group, quantity },
      message: `${t}阶组队通关，获得${quantity}个${group}碎片。`,
    };
  }

  if (ticketType === 'trial') {
    const base = t >= 14 ? 3 : 2;
    const bonus = rng() < 0.5 ? 1 : 0;
    const quantity = base + bonus;
    const group = addFragment(state, t, quantity);

    return {
      ok: true,
      outcome: 'trial-fragment',
      played: { type: 'trial', tier: t },
      fragment: { group, quantity },
      message: `${t}阶试炼通关，获得${quantity}个${group}碎片。`,
    };
  }

  throw new Error(`Unknown ticket type: ${ticketType}`);
}

export function openFragmentBox(state, group, rng = Math.random) {
  if (!FRAGMENT_GROUPS.includes(group)) {
    throw new Error(`Unknown fragment group: ${group}`);
  }

  if (state.fragments[group] < BOX_COST) {
    return {
      ok: false,
      message: `${group}碎片不足${BOX_COST}，无法开箱。`,
    };
  }

  state.fragments[group] -= BOX_COST;

  const tiers = GROUP_TIERS[group];
  const weights = BOX_WEIGHTS[group];
  const idx = pickWeightedIndex(weights, rng);
  const tier = tiers[idx];

  addTicket(state, 'single', tier, 1);

  if (tier > state.stats.highestReached) {
    state.stats.highestReached = tier;
  }

  if (group === 'SSS' && state.stats.highestReached >= 16 && tier <= 15) {
    state.stats.highTierFallbackCount += 1;
  }

  return {
    ok: true,
    ticket: { type: 'single', tier },
    message: `开出${tier}阶单人票。`,
  };
}

export function chooseNextPlayableTicket(state) {
  const singleTier = getHighestTierWithTicket(state, 'single');
  if (singleTier > 0) {
    return { type: 'single', tier: singleTier };
  }

  const partyTier = getHighestTierWithTicket(state, 'party');
  if (partyTier > 0) {
    return { type: 'party', tier: partyTier };
  }

  const trialTier = getHighestTierWithTicket(state, 'trial');
  if (trialTier > 0) {
    return { type: 'trial', tier: trialTier };
  }

  return null;
}

export function autoPlayStep(state, rng = Math.random) {
  const ticket = chooseNextPlayableTicket(state);
  if (!ticket) {
    for (let i = FRAGMENT_GROUPS.length - 1; i >= 0; i -= 1) {
      const group = FRAGMENT_GROUPS[i];
      if (state.fragments[group] >= BOX_COST) {
        const opened = openFragmentBox(state, group, rng);
        if (opened.ok) {
          return {
            type: 'open-box',
            result: opened,
          };
        }
      }
    }

    return {
      type: 'idle',
      result: {
        ok: false,
        message: '没有可用司南，也没有足够碎片开箱。',
      },
    };
  }

  return {
    type: 'play-ticket',
    ticket,
    result: playTicket(state, ticket.type, ticket.tier, rng),
  };
}

export function snapshotState(state) {
  const toList = (arr) => {
    const out = [];
    for (let t = 1; t <= MAX_TIER; t += 1) {
      if (arr[t] > 0) {
        out.push({ tier: t, count: arr[t] });
      }
    }
    return out;
  };

  return {
    tickets: {
      single: toList(state.tickets.single),
      party: toList(state.tickets.party),
      trial: toList(state.tickets.trial),
    },
    fragments: { ...state.fragments },
    stats: { ...state.stats },
  };
}

export const ENGINE_CONST = {
  MIN_TIER,
  MAX_TIER,
  BOX_COST,
};
