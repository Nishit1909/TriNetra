// Mock intelligence data for offline UI development.

export const caseStats = {
  activeCases: 47,
  openLeads: 312,
  flaggedEntities: 18,
  newIngest24h: 2140,
};

// 13-point trend, 2h increments, trailing 24h — feeds the KPI sparklines.
export const caseTrends = {
  activeCases: [39, 40, 41, 41, 42, 44, 44, 45, 45, 46, 46, 47, 47],
  openLeads: [268, 271, 279, 284, 288, 291, 296, 298, 301, 305, 307, 309, 312],
  flaggedEntities: [14, 14, 15, 15, 15, 16, 16, 16, 17, 17, 17, 18, 18],
  newIngest24h: [1180, 1240, 1340, 1410, 1490, 1560, 1650, 1740, 1830, 1920, 2010, 2080, 2140],
};

export const riskFeed = [
  { id: 'ENT-08841', name: 'R. Kaseem Voss', risk: 0.94, flag: 'kingpin', delta: 0.06, case: 'CASE-2291' },
  { id: 'ENT-02217', name: 'Dana M. Achterberg', risk: 0.88, flag: 'boss', delta: 0.02, case: 'CASE-2288' },
  { id: 'ENT-11930', name: 'Unidentified — Node 4471', risk: 0.81, flag: null, delta: 0.11, case: 'CASE-2291' },
  { id: 'ENT-00456', name: 'Teodor Blanco', risk: 0.77, flag: null, delta: -0.03, case: 'CASE-2276' },
  { id: 'ENT-09982', name: 'Priya Nathwani', risk: 0.73, flag: null, delta: 0.00, case: 'CASE-2301' },
  { id: 'ENT-03310', name: 'M. Okonkwo-Reyes', risk: 0.69, flag: 'boss', delta: 0.04, case: 'CASE-2288' },
  { id: 'ENT-07765', name: 'Unidentified — Node 8813', risk: 0.61, flag: null, delta: -0.08, case: 'CASE-2265' },
];

export const activityLog = [
  { t: '14:22:07', event: 'Entity resolution merged 2 identities', ref: 'ENT-08841 ← ENT-08843', actor: 'auto' },
  { t: '14:19:41', event: 'New communication record ingested', ref: 'CDR batch 88291', actor: 'ingest' },
  { t: '14:11:03', event: 'Community re-computed (Louvain, γ=1.10)', ref: '14 communities, mod=0.412', actor: 'auto' },
  { t: '13:58:22', event: 'Risk score recalculated', ref: 'ENT-11930 0.70 → 0.81', actor: 'model' },
  { t: '13:40:56', event: 'Case note added', ref: 'CASE-2291', actor: 'A. Reyes' },
  { t: '13:12:19', event: 'New entity flagged kingpin', ref: 'ENT-08841', actor: 'A. Reyes' },
  { t: '12:55:04', event: 'Dataset uploaded: financial_txn_q3.csv', ref: '188,204 rows', actor: 'D. Farah' },
];

export const caseLoad = [
  { case: 'CASE-2291', analyst: 'A. Reyes', entities: 214, priority: 'high', updated: '2m' },
  { case: 'CASE-2288', analyst: 'D. Farah', entities: 96, priority: 'high', updated: '18m' },
  { case: 'CASE-2301', analyst: 'A. Reyes', entities: 41, priority: 'med', updated: '41m' },
  { case: 'CASE-2276', analyst: 'K. Osei', entities: 132, priority: 'med', updated: '1h' },
  { case: 'CASE-2265', analyst: 'K. Osei', entities: 58, priority: 'low', updated: '3h' },
];

export const communitySnapshot = [
  { id: 'C-04', label: 'Northside distribution', members: 61, density: 0.34, flagged: 3 },
  { id: 'C-11', label: 'Financial layering ring', members: 24, density: 0.51, flagged: 2 },
  { id: 'C-02', label: 'Unresolved cluster', members: 88, density: 0.19, flagged: 1 },
];

export const systemStatus = {
  ingestQueue: 3,
  modelVersion: 'risk-v4.2.1',
  lastSync: '14:22:41',
  uptime: '312d 04h',
};

export const ingestSources = [
  { source: 'Call detail records', records24h: 812400, lastSync: '2m', nominal: true },
  { source: 'Financial transactions', records24h: 188204, lastSync: '18m', nominal: true },
  { source: 'Open-source / web intake', records24h: 4021, lastSync: '41m', nominal: false },
  { source: 'Case notes & analyst input', records24h: 312, lastSync: '2m', nominal: true },
];
