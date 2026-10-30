import React, { useEffect, useMemo, useState } from 'react';
import { Search, Users, Copy, Check, AlertTriangle, ChevronRight } from 'lucide-react';
import { api } from '../../api/client';
import { AnalysisMode, GraphNode, PersonRecord } from '../../api/types';
import { GlassBadge, GlassButton, GlassCard, GlassInput, GlassSelect, GlassSkeleton } from '../../components/glass';
import { computeNodeTiers, copyToClipboard, tierMeta } from '../../utils/format';

interface PeopleViewProps {
  caseId: string;
  mode: AnalysisMode;
  onSelectPerson: (personId: string) => void;
  onToast: (msg: string, tone?: 'cyan' | 'emerald' | 'crimson' | 'amber') => void;
}

export const PeopleView: React.FC<PeopleViewProps> = ({ caseId, mode, onSelectPerson, onToast }) => {
  const [persons, setPersons] = useState<PersonRecord[]>([]);
  const [tieredNodes, setTieredNodes] = useState<Map<string, GraphNode>>(new Map());
  const [q, setQ] = useState('');
  const [department, setDepartment] = useState('');
  const [loading, setLoading] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.getPersons(caseId, { limit: 100, offset: 0 }),
      api.getGraph(caseId, { mode, limit: 100, edge_limit: 200 }).catch(() => null),
    ]).then(([pRes, gRes]) => {
      if (cancelled) return;
      setPersons(pRes.items || []);
      if (gRes?.nodes) {
        const withTiers = computeNodeTiers(gRes.nodes);
        const m = new Map<string, GraphNode>();
        withTiers.forEach((n) => m.set(n.id, n));
        setTieredNodes(m);
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [caseId, mode]);

  const departments = useMemo(() => {
    const s = new Set<string>();
    persons.forEach((p) => {
      if (p.department) s.add(p.department);
    });
    return [...s].sort();
  }, [persons]);

  const filtered = useMemo(() => {
    return persons.filter((p) => {
      if (department && (p.department || '') !== department) return false;
      if (q) {
        const query = q.toLowerCase();
        if (!p.display_name.toLowerCase().includes(query) && !p.person_id.toLowerCase().includes(query)) {
          return false;
        }
      }
      return true;
    });
  }, [persons, department, q]);

  const handleCopy = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (await copyToClipboard(id)) {
      setCopiedId(id);
      onToast(`Copied ID ${id}`, 'cyan');
      setTimeout(() => setCopiedId(null), 1400);
    }
  };

  return (
    <div className="space-y-5">
      <GlassCard className="p-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-bold text-white flex items-center gap-2">
            <Users className="w-5 h-5 text-[#22d3ee]" />
            Case Subjects & Network Position Directory
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Click any person to inspect their centrality ranks, group cluster, vehicle attribution, and timeline.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-64">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <GlassInput
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name or ID..."
              className="pl-9"
              aria-label="Search people by name or ID"
            />
          </div>
          {departments.length > 0 && (
            <GlassSelect
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              aria-label="Filter by department"
            >
              <option value="">All Departments ({persons.length})</option>
              {departments.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </GlassSelect>
          )}
        </div>
      </GlassCard>

      {loading ? (
        <div className="space-y-3">
          <GlassSkeleton className="h-14 w-full" />
          <GlassSkeleton className="h-14 w-full" />
          <GlassSkeleton className="h-14 w-full" />
        </div>
      ) : (
        <GlassCard noPadding className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/[0.1] bg-white/[0.04] text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  <th className="py-3.5 px-4">Person</th>
                  <th className="py-3.5 px-4">Subject ID</th>
                  <th className="py-3.5 px-4">Department / Role</th>
                  <th className="py-3.5 px-4">Network Position Tier</th>
                  <th className="py-3.5 px-4 text-right">Influence Rank</th>
                  <th className="py-3.5 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06] text-sm">
                {filtered.map((p) => {
                  const gNode = tieredNodes.get(p.person_id);
                  const tMeta = tierMeta(gNode?.tier);
                  return (
                    <tr
                      key={p.person_id}
                      onClick={() => onSelectPerson(p.person_id)}
                      className="hover:bg-white/[0.06] transition cursor-pointer group"
                    >
                      <td className="py-3 px-4 font-medium text-white flex items-center gap-2.5">
                        <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${tMeta.dotClass}`} />
                        <span>{p.display_name}</span>
                      </td>
                      <td className="py-3 px-4 font-mono text-xs text-slate-300">
                        <button
                          onClick={(e) => handleCopy(e, p.person_id)}
                          className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-white/[0.05] hover:bg-white/[0.12] border border-white/[0.08]"
                        >
                          {p.person_id}
                          {copiedId === p.person_id ? (
                            <Check className="w-3 h-3 text-emerald-400" />
                          ) : (
                            <Copy className="w-3 h-3 text-slate-400" />
                          )}
                        </button>
                      </td>
                      <td className="py-3 px-4 text-xs text-slate-300">
                        <div>{p.department || '—'}</div>
                        {p.job_title && <div className="text-slate-400 text-[11px]">{p.job_title}</div>}
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs border ${tMeta.bgClass}`}>
                            {tMeta.label}
                          </span>
                          {gNode?.hub_flag && (
                            <GlassBadge tone="amber">
                              <AlertTriangle className="w-3 h-3" />
                              Verify Hub
                            </GlassBadge>
                          )}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-xs text-slate-200 tabular-nums">
                        {gNode?.pagerankRank ? `#${gNode.pagerankRank} of ${persons.length}` : '—'}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <GlassButton size="sm" variant="ghost">
                          Profile <ChevronRight className="w-3.5 h-3.5" />
                        </GlassButton>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-3 border-t border-white/[0.08] bg-white/[0.02] flex items-center justify-between text-xs text-slate-400">
            <span>
              Showing <strong className="font-mono text-white">{filtered.length}</strong> of{' '}
              <strong className="font-mono text-white">{persons.length}</strong> subjects
            </span>
            <span>Key figure / Secondary / Connector reflect network position, not guilt.</span>
          </div>
        </GlassCard>
      )}
    </div>
  );
};
