import type { GraphEdge, GraphNode, GraphResponse } from '../../api/types';
import { computeNodeTiers, tierMeta } from '../../utils/format';

/** Graph libraries replace string endpoints with node objects; normalise either form to an ID. */
export const endpoint = (v: string | GraphNode) => (typeof v === 'object' ? v.id : v);

/** Muted community hues for everyone outside the highlighted tiers. */
export const palette = ['#7c8db5', '#5fa8c4', '#9a8bd1', '#c9a26e', '#c98aa2', '#6fb7a1'];

export const communityIndex = (id: string | number) =>
  typeof id === 'number' ? Math.abs(id) : Array.from(id).reduce((n, c) => (n * 31 + c.charCodeAt(0)) >>> 0, 0);

/** Community colour (stable per community ID). */
export const nodeColor = (n: Pick<GraphNode, 'community_id'>) =>
  n.community_id == null ? '#8a99ab' : palette[communityIndex(n.community_id) % palette.length];

/** What the canvas draws: tier colour for key / secondary figures, community colour otherwise. */
export const displayColor = (n: GraphNode) =>
  n.tier === 'key_figure' || n.tier === 'secondary_figure' ? tierMeta(n.tier).color : nodeColor(n);

export const EDGE_COLORS = {
  observed: '#7f9db0',
  inferred: '#a78bfa',
  predictedEvidence: '#ff5c77',
  predictedPattern: '#22d3ee',
} as const;

export const edgeColor = (e: GraphEdge) =>
  e.kind === 'predicted'
    ? e.basis === 'evidence'
      ? EDGE_COLORS.predictedEvidence
      : EDGE_COLORS.predictedPattern
    : e.kind === 'inferred'
      ? EDGE_COLORS.inferred
      : EDGE_COLORS.observed;

/** Node radius from PageRank (graph units). Kept small so labels stay readable. */
export const nodeRadius = (n: GraphNode) => {
  const base = 4 + Math.min(8, Math.sqrt(Math.max(0, n.pagerank || 0)) * 28);
  return n.tier === 'key_figure' ? base + 2 : base;
};

/**
 * Visual filtering for the current view. Returns fresh copies, because the force
 * simulation mutates nodes (x/y) and replaces link endpoints with node objects.
 * Analysis always uses the full case; this only changes what is drawn.
 */
export function filterGraph(
  data: Pick<GraphResponse, 'nodes' | 'edges'> | undefined | null,
  department: string,
  community: string,
): { nodes: GraphNode[]; links: GraphEdge[] } {
  const raw = data?.nodes || [];
  // Tiers need an analysis run (PageRank). Without one, nobody is highlighted rather than an arbitrary top three.
  const hasMetrics = raw.some((n) => n.pagerank != null);
  const tiered = hasMetrics ? computeNodeTiers(raw) : raw.map((n) => ({ ...n, tier: 'neutral' as const }));
  const nodes = tiered
    .filter((n) => (!department || n.department === department) && (!community || String(n.community_id) === community))
    .map((n) => ({ ...n }));
  const ids = new Set(nodes.map((n) => n.id));
  return {
    nodes,
    links: (data?.edges || [])
      .filter((e) => ids.has(endpoint(e.source)) && ids.has(endpoint(e.target)))
      .map((e) => ({ ...e, source: endpoint(e.source), target: endpoint(e.target) })),
  };
}

/** Smooth 0..1 pulse used by the blinking key / secondary figures (period in ms). */
export const pulse = (t: number, period: number) => 0.5 - 0.5 * Math.cos((2 * Math.PI * (t % period)) / period);
