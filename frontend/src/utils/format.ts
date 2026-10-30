import { GraphNode, NodeTier } from '../api/types';

export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('en-IN');
}

export function formatIST(iso: string | null | undefined): { formatted: string; relative: string } {
  if (!iso) return { formatted: '—', relative: '' };
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return { formatted: String(iso), relative: '' };
    const formatted =
      new Intl.DateTimeFormat('en-IN', {
        timeZone: 'Asia/Kolkata',
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(d) + ' IST';
    const diffSec = Math.round((Date.now() - d.getTime()) / 1000);
    const absSec = Math.abs(diffSec);
    let relative = 'just now';
    if (absSec >= 86400) {
      const days = Math.round(absSec / 86400);
      relative = diffSec >= 0 ? `${days}d ago` : `in ${days}d`;
    } else if (absSec >= 3600) {
      const hrs = Math.round(absSec / 3600);
      relative = diffSec >= 0 ? `${hrs}h ago` : `in ${hrs}h`;
    } else if (absSec >= 60) {
      const mins = Math.round(absSec / 60);
      relative = diffSec >= 0 ? `${mins}m ago` : `in ${mins}m`;
    }
    return { formatted, relative };
  } catch {
    return { formatted: String(iso), relative: '' };
  }
}

export function methodLabel(method: string): string {
  switch (method) {
    case 'tie_without_recorded_communication':
      return 'Meets but never communicates';
    case 'hidden_link_ranker':
      return 'Hidden-link pattern (ML)';
    case 'network_proximity_ppr':
      return 'Network proximity (PPR fallback)';
    case 'network_proximity_adamic_adar':
      return 'Shared contacts (Adamic-Adar)';
    default:
      return method.replace(/_/g, ' ');
  }
}

/**
 * Compute node tiers strictly according to SPEC §3:
 * - Key figure: top 3 people by pagerank in the shown graph, OR anyone with hub_flag: true among top 10
 * - Secondary figure: next 7 by pagerank
 * - Connector: top 5 by betweenness not already above
 * - Everyone else: neutral
 */
export function computeNodeTiers(nodes: GraphNode[]): GraphNode[] {
  const byPr = [...nodes].sort(
    (a, b) => Number(b.pagerank || 0) - Number(a.pagerank || 0) || a.id.localeCompare(b.id)
  );
  const byBt = [...nodes].sort(
    (a, b) => Number(b.betweenness || 0) - Number(a.betweenness || 0) || a.id.localeCompare(b.id)
  );

  const prRankMap = new Map<string, number>();
  byPr.forEach((n, idx) => prRankMap.set(n.id, idx + 1));

  const btRankMap = new Map<string, number>();
  byBt.forEach((n, idx) => btRankMap.set(n.id, idx + 1));

  const keyIds = new Set<string>();
  const secondaryIds = new Set<string>();
  const connectorIds = new Set<string>();

  byPr.slice(0, 10).forEach((n, idx) => {
    if (idx < 3 || n.hub_flag) {
      keyIds.add(n.id);
    }
  });

  for (const n of byPr) {
    if (secondaryIds.size >= 7) break;
    if (!keyIds.has(n.id)) {
      secondaryIds.add(n.id);
    }
  }

  for (const n of byBt) {
    if (connectorIds.size >= 5) break;
    if (!keyIds.has(n.id) && !secondaryIds.has(n.id)) {
      connectorIds.add(n.id);
    }
  }

  return nodes.map((n) => {
    let tier: NodeTier = 'neutral';
    if (keyIds.has(n.id)) tier = 'key_figure';
    else if (secondaryIds.has(n.id)) tier = 'secondary_figure';
    else if (connectorIds.has(n.id)) tier = 'connector';
    return {
      ...n,
      tier,
      pagerankRank: prRankMap.get(n.id) ?? 999,
      betweennessRank: btRankMap.get(n.id) ?? 999,
    };
  });
}

export const COMMUNITY_HUES: Record<string, string> = {
  C00: '#64748b',
  C01: '#6366f1',
  C02: '#14b8a6',
  C03: '#a855f7',
  C04: '#ec4899',
  C05: '#3b82f6',
  C06: '#10b981',
  C07: '#f97316',
};

export function tierMeta(tier?: NodeTier) {
  switch (tier) {
    case 'key_figure':
      return {
        label: 'Key figure',
        color: '#ff3b5c',
        bgClass: 'bg-[#ff3b5c]/15 text-[#ff3b5c] border-[#ff3b5c]/40',
        dotClass: 'bg-[#ff3b5c] shadow-[0_0_10px_#ff3b5c]',
      };
    case 'secondary_figure':
      return {
        label: 'Secondary figure',
        color: '#ffb020',
        bgClass: 'bg-[#ffb020]/15 text-[#ffb020] border-[#ffb020]/40',
        dotClass: 'bg-[#ffb020] shadow-[0_0_8px_#ffb020]',
      };
    case 'connector':
      return {
        label: 'Connector',
        color: '#22d3ee',
        bgClass: 'bg-[#22d3ee]/15 text-[#22d3ee] border-[#22d3ee]/35',
        dotClass: 'bg-[#22d3ee] shadow-[0_0_8px_#22d3ee]',
      };
    default:
      return {
        label: 'Network member',
        color: '#94a3b8',
        bgClass: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
        dotClass: 'bg-slate-400',
      };
  }
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fallback below
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    return true;
  } catch {
    return false;
  }
}
