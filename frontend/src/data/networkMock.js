// Deterministic mock network — same graph every load, so the workspace is stable to work in
// and to screenshot. Seeds from the dashboard's existing risk feed so IDs/names line up across
// pages, then fills out a realistic surrounding network of associates.

import { riskFeed } from './mock';

// mulberry32 — small, fast, deterministic PRNG. No crypto need; this is fixture data.
function mulberry32(seed) {
  let a = seed;
  return function rand() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rand = mulberry32(261890);
const pick = (arr) => arr[Math.floor(rand() * arr.length)];

const FIRST_NAMES = [
  'Marcus', 'Elena', 'Dmitri', 'Farida', 'Owen', 'Lucia', 'Tobias', 'Nadia', 'Rashid', 'Saoirse',
  'Kenji', 'Ingrid', 'Amara', 'Viktor', 'Priya', 'Callum', 'Zanele', 'Mateo', 'Yelena', 'Idris',
  'Freya', 'Emeka', 'Sofia', 'Aleksander', 'Naomi', 'Petra', 'Jonah', 'Anaya', 'Beckett', 'Ines',
];
const LAST_NAMES = [
  'Voss', 'Achterberg', 'Okonkwo-Reyes', 'Blanco', 'Nathwani', 'Farrow', 'Hollis', 'Damir',
  'Sundqvist', 'Okafor', 'Reyes', 'Farah', 'Osei', 'Castellano', 'Whitfield', 'Torbin', 'Adeyemi',
  'Larkspur', 'Moreau', 'Ibarra', 'Kessler', 'Draganov', 'Sancho', 'Weir', 'Akintola',
];

const COMMUNITIES = [
  { id: 'C-04', label: 'Northside distribution' },
  { id: 'C-11', label: 'Financial layering ring' },
  { id: 'C-02', label: 'Unresolved cluster' },
  { id: 'C-07', label: 'Port intake crew' },
  { id: 'C-09', label: 'Logistics & transport' },
];

const NODE_COUNT = 54;
const EXTRA_FLAGGED = [
  { name: 'V. Draganov-Sancho', flag: 'boss', community: 'C-07' },
];

function buildNodes() {
  const nodes = [];
  const usedIds = new Set();

  // Seed from the dashboard's own risk feed so this is one dataset, not a disconnected demo.
  riskFeed.forEach((r, i) => {
    usedIds.add(r.id);
    nodes.push({
      id: r.id,
      name: r.name,
      risk: r.risk,
      flag: r.flag,
      caseRefs: [r.case],
      community: COMMUNITIES[i % COMMUNITIES.length].id,
    });
  });

  EXTRA_FLAGGED.forEach((f, i) => {
    const id = 'ENT-' + String(20100 + i).padStart(5, '0');
    usedIds.add(id);
    nodes.push({
      id,
      name: f.name,
      risk: 0.7 + rand() * 0.25,
      flag: f.flag,
      caseRefs: [pick(riskFeed).case],
      community: f.community,
    });
  });

  let n = nodes.length;
  while (n < NODE_COUNT) {
    const id = 'ENT-' + String(30000 + n * 7 + Math.floor(rand() * 900)).padStart(5, '0');
    if (usedIds.has(id)) continue;
    usedIds.add(id);
    const first = pick(FIRST_NAMES);
    const last = pick(LAST_NAMES);
    const initial = first[0] + '.';
    nodes.push({
      id,
      name: rand() > 0.15 ? `${initial} ${last}` : `Unidentified — Node ${1000 + Math.floor(rand() * 8999)}`,
      risk: Math.round((0.15 + rand() * 0.55) * 100) / 100,
      flag: null,
      caseRefs: rand() > 0.6 ? [pick(riskFeed).case] : [],
      community: pick(COMMUNITIES).id,
    });
    n++;
  }

  return nodes;
}

function buildEdges(nodes) {
  const edges = [];
  const seen = new Set();
  const byId = new Map(nodes.map((node) => [node.id, node]));

  const addEdge = (a, b, strength, type) => {
    if (a === b) return;
    const key = a < b ? a + '|' + b : b + '|' + a;
    if (seen.has(key)) return;
    seen.add(key);
    edges.push({ source: a, target: b, strength, type });
  };

  const byCommunity = new Map();
  nodes.forEach((node) => {
    if (!byCommunity.has(node.community)) byCommunity.set(node.community, []);
    byCommunity.get(node.community).push(node);
  });

  // Dense-ish inside a community — this is what makes clusters visually resolve.
  byCommunity.forEach((members) => {
    for (let i = 0; i < members.length; i++) {
      for (let j = i + 1; j < members.length; j++) {
        if (rand() < 0.16) {
          const type = rand() > 0.6 ? 'financial' : 'comms';
          addEdge(members[i].id, members[j].id, 0.35 + rand() * 0.6, type);
        }
      }
    }
  });

  // Sparse bridges across communities — brokers, joint operations.
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      if (nodes[i].community === nodes[j].community) continue;
      if (rand() < 0.006) {
        addEdge(nodes[i].id, nodes[j].id, 0.15 + rand() * 0.3, 'associate');
      }
    }
  }

  // Flagged entities are hubs — that's what makes them worth flagging. Guarantee it.
  nodes.filter((node) => node.flag).forEach((hub) => {
    const communityPeers = byCommunity.get(hub.community).filter((peer) => peer.id !== hub.id);
    const extraLinks = 4 + Math.floor(rand() * 5);
    for (let k = 0; k < extraLinks; k++) {
      const target = rand() > 0.3 ? pick(communityPeers) : pick(nodes);
      if (target) addEdge(hub.id, target.id, 0.4 + rand() * 0.55, 'comms');
    }
  });

  // No stranded nodes — every entity in the workspace has at least one known connection.
  const degree = new Map(nodes.map((node) => [node.id, 0]));
  edges.forEach((e) => {
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
  });
  nodes.forEach((node) => {
    if (!degree.get(node.id)) {
      const peers = byCommunity.get(node.community).filter((peer) => peer.id !== node.id);
      const target = peers.length ? pick(peers) : pick(nodes.filter((n2) => n2.id !== node.id));
      addEdge(node.id, target.id, 0.25 + rand() * 0.3, 'associate');
    }
  });

  return { edges, byId };
}

export function buildNetwork() {
  const nodes = buildNodes();
  const { edges } = buildEdges(nodes);

  const degree = new Map(nodes.map((node) => [node.id, 0]));
  edges.forEach((e) => {
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
  });

  const withDegree = nodes.map((node) => ({ ...node, degree: degree.get(node.id) || 0 }));
  const byId = new Map(withDegree.map((node) => [node.id, node]));

  const connections = new Map(withDegree.map((node) => [node.id, []]));
  edges.forEach((e) => {
    connections.get(e.source).push({ id: e.target, strength: e.strength, type: e.type });
    connections.get(e.target).push({ id: e.source, strength: e.strength, type: e.type });
  });

  return { nodes: withDegree, edges, byId, connections, communities: COMMUNITIES };
}
