import React, { useEffect, useState } from 'react';
import { GitCompare, ArrowUpRight, ArrowDownRight, Sparkles, Info, AlertTriangle } from 'lucide-react';
import { api } from '../../api/client';
import { AnalysisRun, CompareRunsResponse } from '../../api/types';
import { GlassBadge, GlassCard, GlassSelect, GlassSkeleton, GlassStat } from '../../components/glass';
import { methodLabel } from '../../utils/format';

interface CompareViewProps {
  caseId: string;
  onSelectPerson: (personId: string) => void;
}

export const CompareView: React.FC<CompareViewProps> = ({ caseId, onSelectPerson }) => {
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [runA, setRunA] = useState<string>('');
  const [runB, setRunB] = useState<string>('');
  const [comparison, setComparison] = useState<CompareRunsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.listAnalysisRuns(caseId).then((list) => {
      if (cancelled) return;
      setRuns(list);
      const obsRun = list.find((r) => r.mode === 'observed_only') || list[1] || list[0];
      const infRun = list.find((r) => r.mode === 'observed_plus_inferred') || list[0];
      if (obsRun && infRun) {
        setRunA(obsRun.analysis_run_id);
        setRunB(infRun.analysis_run_id);
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [caseId]);

  useEffect(() => {
    if (!runA || !runB) return;
    let cancelled = false;
    setLoading(true);
    api
      .compareRuns(caseId, runA, runB, 12)
      .then((res) => {
        if (!cancelled) {
          setComparison(res);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [caseId, runA, runB]);

  return (
    <div className="space-y-5">
      <GlassCard className="p-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-bold text-white flex items-center gap-2">
            <GitCompare className="w-5 h-5 text-[#22d3ee]" />
            Compare Analysis Runs — What Inferred Evidence Adds
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Compare baseline observed-only centrality against observed + GPS-inferred co-location evidence.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-400 mb-1">Baseline (Run A)</label>
            <GlassSelect value={runA} onChange={(e) => setRunA(e.target.value)} aria-label="Select Run A">
              {runs.map((r) => (
                <option key={r.analysis_run_id} value={r.analysis_run_id}>
                  {r.mode} ({r.weights_version}) — {r.analysis_run_id.slice(0, 8)}
                </option>
              ))}
            </GlassSelect>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-400 mb-1">Comparison (Run B)</label>
            <GlassSelect value={runB} onChange={(e) => setRunB(e.target.value)} aria-label="Select Run B">
              {runs.map((r) => (
                <option key={r.analysis_run_id} value={r.analysis_run_id}>
                  {r.mode} ({r.weights_version}) — {r.analysis_run_id.slice(0, 8)}
                </option>
              ))}
            </GlassSelect>
          </div>
        </div>
      </GlassCard>

      {loading || !comparison ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <GlassSkeleton className="h-24 w-full" />
            <GlassSkeleton className="h-24 w-full" />
            <GlassSkeleton className="h-24 w-full" />
            <GlassSkeleton className="h-24 w-full" />
          </div>
          <GlassSkeleton className="h-64 w-full" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <GlassStat
              label="New Suggested Links in Run B"
              value={comparison.links_only_in_b.length}
              sub={`${comparison.links_only_in_b.length} new + ${comparison.links_in_both} retained = ${comparison.predicted_in_b ?? '—'} suggestions in Run B`}
              accent="violet"
            />
            <GlassStat
              label="Suggestions in Both Runs"
              value={comparison.links_in_both}
              sub="Same pair and method in A and B"
              accent="cyan"
            />
            <GlassStat
              label="Biggest Rank Movers"
              value={comparison.biggest_rank_changes.length}
              sub="Influence rank shifts"
              accent="amber"
            />
            <GlassStat
              label="Cluster Regroupings"
              value={comparison.community_changes}
              sub={`${comparison.hub_changes.length} hub flag change(s)`}
              accent="emerald"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Biggest Rank Movers */}
            <GlassCard className="p-5 space-y-3.5">
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-[#ffb020]" />
                Biggest Influence (PageRank) Rank Shifts
              </h2>
              {comparison.biggest_rank_changes.length === 0 ? (
                <div className="space-y-2">
                  <p className="text-xs text-slate-400">
                    No influence-rank changes: the added links did not change anyone's rank order. Largest influence-score changes:
                  </p>
                  {(comparison.score_changes || []).map((sc) => (
                    <div key={sc.person_id} onClick={() => onSelectPerson(sc.person_id)}
                      className="p-2.5 rounded-[12px] bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] flex items-center justify-between text-xs cursor-pointer">
                      <span className="text-white font-medium">{sc.display_name || sc.person_id}</span>
                      <span className="font-mono text-slate-400">
                        {sc.pagerank_a.toFixed(4)} → <strong className="text-white">{sc.pagerank_b.toFixed(4)}</strong>{' '}
                        <span className={sc.change >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
                          ({sc.change >= 0 ? '+' : ''}{sc.change.toFixed(4)})
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-2">
                  {comparison.biggest_rank_changes.map((m) => {
                    const up = m.rank_change > 0;
                    return (
                      <div
                        key={m.person_id}
                        onClick={() => onSelectPerson(m.person_id)}
                        className="p-3 rounded-[14px] bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] flex items-center justify-between gap-3 cursor-pointer transition"
                      >
                        <div>
                          <div className="text-sm font-semibold text-white">{m.display_name || m.person_id}</div>
                          <div className="text-[11px] font-mono text-slate-400">
                            {m.person_id}{m.community_moved ? ` • moved cluster (${m.community_a} → ${m.community_b})` : ""}
                          </div>
                        </div>
                        <div className="flex items-center gap-3 font-mono text-xs">
                          <span className="text-slate-400">
                            #{m.pagerank_rank_a} → <strong className="text-white">#{m.pagerank_rank_b}</strong>
                          </span>
                          {m.rank_change !== 0 && (
                            <span
                              className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-bold ${
                                up
                                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                                  : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                              }`}
                            >
                              {up ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
                              {up ? `+${m.rank_change}` : m.rank_change}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </GlassCard>

            {/* Links Added Only in Run B */}
            <GlassCard className="p-5 space-y-3.5" variant="violet">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold text-white flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-[#a78bfa]" />
                  Leads Surfaced Only in Run B ({comparison.links_only_in_b.length})
                </h2>
                <GlassBadge tone="violet">Added by Inferred Evidence</GlassBadge>
              </div>
              {comparison.links_only_in_b.length === 0 ? (
                <p className="text-xs text-slate-400">
                  No new links added in Run B compared to Run A.
                </p>
              ) : (
                <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
                  {comparison.links_only_in_b.map((l, idx) => (
                    <div
                      key={`${l.person_a}-${l.person_b}-${idx}`}
                      className="p-3 rounded-[14px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-between gap-3"
                    >
                      <div>
                        <div className="text-sm font-semibold text-white">
                          {l.names[0] || l.person_a} <span className="text-slate-500">↔</span> {l.names[1] || l.person_b}
                        </div>
                        <div className="text-[11px] text-violet-300">{methodLabel(l.method)}</div>
                      </div>
                      <GlassBadge tone="violet">New in Run B</GlassBadge>
                    </div>
                  ))}
                </div>
              )}
            </GlassCard>
          </div>

          <div className="p-3.5 rounded-[14px] bg-white/[0.03] border border-white/[0.08] text-xs text-slate-400 flex items-center gap-2">
            <Info className="w-4 h-4 text-[#22d3ee] shrink-0" />
            <span>{comparison.note}</span>
          </div>
        </>
      )}
    </div>
  );
};
