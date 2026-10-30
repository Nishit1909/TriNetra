import { describe, expect, it } from 'vitest';
import type { GraphResponse } from '../../api/types';
import { displayColor, edgeColor, filterGraph, nodeColor, pulse } from './graph-utils';

const node = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  label: id.toUpperCase(),
  department: 'IT',
  pagerank: 0.01,
  betweenness: 0,
  community_id: 'C00',
  hub_flag: false,
  degree: 1,
  ...extra,
});

const data = {
  nodes: [node('a', { department: 'IT', community_id: 'C01' }), node('b', { department: 'HR', community_id: 'C02' })],
  edges: [{ id: 'e', source: 'a', target: 'b', kind: 'observed', type: 'EMAILED', weight: 1 }],
} as unknown as GraphResponse;

describe('filterGraph', () => {
  it('removes dangling edges when a visual filter removes a person', () => {
    const result = filterGraph(data, 'IT', '');
    expect(result.nodes.map((n) => n.id)).toEqual(['a']);
    expect(result.links).toEqual([]);
  });

  it('clones graph data before force simulations mutate positions and endpoints', () => {
    const result = filterGraph(data, '', '');
    result.nodes[0].x = 42;
    result.links[0].source = result.nodes[0];
    expect(data.nodes[0].x).toBeUndefined();
    expect(data.edges[0].source).toBe('a');
  });

  it('handles graph-library endpoint objects', () => {
    const withObject = { ...data, edges: [{ ...data.edges[0], source: data.nodes[0] }] } as GraphResponse;
    expect(filterGraph(withObject, '', '').links[0].source).toBe('a');
  });

  it('handles an empty or missing case response', () => {
    expect(filterGraph(undefined, '', '')).toEqual({ nodes: [], links: [] });
    expect(filterGraph(null, '', '')).toEqual({ nodes: [], links: [] });
  });

  it('assigns tiers from PageRank: top three are key figures', () => {
    const many = {
      nodes: Array.from({ length: 12 }, (_, i) => node(`n${i}`, { pagerank: (12 - i) / 100 })),
      edges: [],
    } as unknown as GraphResponse;
    const tiers = filterGraph(many, '', '').nodes.map((n) => n.tier);
    expect(tiers.slice(0, 3)).toEqual(['key_figure', 'key_figure', 'key_figure']);
    expect(tiers.filter((t) => t === 'secondary_figure')).toHaveLength(7);
  });
});

describe('colours', () => {
  it('distinguishes string community IDs instead of colouring every group alike', () => {
    expect(nodeColor(data.nodes[0])).not.toBe(nodeColor(data.nodes[1]));
  });

  it('draws key figures in crimson and secondary figures in amber', () => {
    expect(displayColor({ ...data.nodes[0], tier: 'key_figure' })).toBe('#ff3b5c');
    expect(displayColor({ ...data.nodes[0], tier: 'secondary_figure' })).toBe('#ffb020');
    expect(displayColor({ ...data.nodes[0], tier: 'neutral' })).toBe(nodeColor(data.nodes[0]));
  });

  it('separates evidence-based and pattern-based predicted links', () => {
    const base = data.edges[0];
    expect(edgeColor({ ...base, kind: 'predicted', basis: 'evidence' })).not.toBe(
      edgeColor({ ...base, kind: 'predicted', basis: 'structural_pattern' }),
    );
  });

  it('pulses smoothly between 0 and 1', () => {
    expect(pulse(0, 1600)).toBeCloseTo(0);
    expect(pulse(800, 1600)).toBeCloseTo(1);
  });
});
