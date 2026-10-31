import React, { useEffect, useState } from 'react';
import {
  Users,
  Mail,
  Share2,
  Car,
  MapPin,
  FileText,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ArrowRight,
  Sparkles,
  ShieldAlert,
  Activity,
  Eye,
} from 'lucide-react';
import { api } from '../../api/client';
import {
  AnalysisDetailResponse,
  AnalysisMode,
  CaseSummaryResponse,
  GraphNode,
  PersonRecord,
  PredictedLink,
} from '../../api/types';
import { GlassBadge, GlassButton, GlassCard, GlassSkeleton } from '../../components/glass';
import { computeNodeTiers, formatIST, formatNumber, methodLabel, tierMeta } from '../../utils/format';

interface OverviewViewProps {
  caseId: string;
  mode: AnalysisMode;
  canEditCase?: boolean;
  onSelectPerson: (personId: string) => void;
  onOpenPairEvidence?: (personA: string, personB: string, link?: PredictedLink) => void;
  onNavigate: (screen: 'network' | 'leads' | 'compare' | 'people') => void;
  onToast?: (msg: string, tone?: 'cyan' | 'emerald' | 'crimson' | 'amber') => void;
}

const AnimatedStatCard: React.FC<{
  label: string;
  target: number;
  sub?: string;
  icon: React.ReactNode;
  accentClass: string;
}> = ({ label, target, sub, icon, accentClass }) => {
  const [val, setVal] = useState(0);

  useEffect(() => {
    let frame = 0;
    const totalFrames = 22;
    const timer = setInterval(() => {
      frame++;
      const progress = frame / totalFrames;
      const eased = 1 - Math.pow(1 - progress, 3);
      setVal(Math.round(target * eased));
      if (frame >= totalFrames) {
        setVal(target);
        clearInterval(timer);
      }
    }, 18);
    return () => clearInterval(timer);
  }, [target]);

  return (
    <GlassCard className="p-4 flex flex-col justify-between">
      <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
        <span className="font-medium tracking-wide uppercase">{label}</span>
        <span className={accentClass}>{icon}</span>
      </div>
      <div className="font-mono text-2xl font-semibold text-white tabular-nums tracking-tight">
        {formatNumber(val)}
      </div>
      {sub && <div className="text-[11px] text-slate-400 mt-1">{sub}</div>}
    </GlassCard>
  );
};

export const OverviewView: React.FC<OverviewViewProps> = ({
  caseId,
  mode,
  canEditCase = false,
  onSelectPerson,
  onOpenPairEvidence,
  onNavigate,
  onToast,
}) => {
  const [summary, setSummary] = useState<CaseSummaryResponse | null>(null);
  const [topFigures, setTopFigures] = useState<GraphNode[]>([]);
  const [topLeads, setTopLeads] = useState<PredictedLink[]>([]);
  const [personsMap, setPersonsMap] = useState<Map<string, PersonRecord>>(new Map());
  const [runDetail, setRunDetail] = useState<AnalysisDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);

  // Document & Place Inspector state
  const [selectedDocId, setSelectedDocId] = useState<string>('MC1DOC_e38026415b10');
  const [docData, setDocData] = useState<any | null>(null);
  const [placeData, setPlaceData] = useState<any | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.getCaseSummary(caseId),
      api.getPersons(caseId, { limit: 100 }),
      api.getGraph(caseId, { mode, limit: 60, edge_limit: 200 }).catch(() => null),
      api.listAnalysisRuns(caseId).catch(() => []),
      Promise.resolve(null),   // document inspector removed from the Overview
    ]).then(async ([sumRes, pRes, gRes, runs, docRes]) => {
      if (cancelled) return;
      setSummary(sumRes);
      setDocData(docRes);
      const pMap = new Map<string, PersonRecord>();
      (pRes.items || []).forEach((p) => pMap.set(p.person_id, p));
      setPersonsMap(pMap);

      if (gRes?.nodes) {
        const tiered = computeNodeTiers(gRes.nodes);
        tiered.sort((a, b) => (a.pagerankRank || 999) - (b.pagerankRank || 999));
        setTopFigures(tiered.slice(0, 5));
      }

      const targetRun = runs.find((r) => r.mode === mode) || runs[0];
      if (targetRun) {
        const det = await api.getAnalysisDetail(caseId, targetRun.analysis_run_id).catch(() => null);
        if (!cancelled && det) {
          setRunDetail(det);
          const evLeads = det.predicted_links.filter((l) => l.method === 'tie_without_recorded_communication');
          setTopLeads((evLeads.length > 0 ? evLeads : det.predicted_links).slice(0, 5));
        }
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [caseId, mode, selectedDocId]);

  if (loading || !summary) {
    return (
      <div className="space-y-5">
        <GlassSkeleton className="h-36 w-full" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <GlassSkeleton className="h-24 w-full" />
          <GlassSkeleton className="h-24 w-full" />
          <GlassSkeleton className="h-24 w-full" />
          <GlassSkeleton className="h-24 w-full" />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <GlassSkeleton className="h-64 w-full" />
          <GlassSkeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  const latestRun = runDetail?.run || summary.latest_analysis;
  const runTime = formatIST(latestRun?.completed_at || latestRun?.started_at);

  const handleReviewMention = async (mentionId: number, status: 'confirmed' | 'rejected') => {
    try {
      await api.reviewDocumentMention(caseId, mentionId, {
        status,
        reason: `Analyst ${status} entity mention in ${selectedDocId}`,
      });
    } catch (err: any) {
      onToast?.(err?.message || 'Could not save the review', 'crimson');
      return;
    }
    if (docData?.mentions) {
      setDocData({
        ...docData,
        mentions: docData.mentions.map((m: any) =>
          m.mention_id === mentionId ? { ...m, review_status: status } : m
        ),
      });
    }
    onToast?.(`Document mention #${mentionId} ${status}`, status === 'confirmed' ? 'emerald' : 'amber');
  };

  return (
    <div className="space-y-5">
      {/* Hero Case Card */}
      <GlassCard className="p-6">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <GlassBadge
                tone={
                  summary.case.role === 'investigation'
                    ? 'cyan'
                    : summary.case.role === 'benchmark'
                    ? 'violet'
                    : 'amber'
                }
              >
                Role: {summary.case.role}
              </GlassBadge>
              {summary.case.is_synthetic && <GlassBadge tone="slate">Synthetic Dataset</GlassBadge>}
              <span className="font-mono text-xs text-slate-400">{summary.case.case_id}</span>
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">{summary.case.name}</h1>
            <p className="text-sm text-slate-300 max-w-3xl">{summary.case.description}</p>
            <div className="text-xs text-slate-400">
              Provenance / Source: <span className="font-mono text-slate-300">{summary.case.source}</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5 shrink-0">
            <GlassButton variant="primary" size="lg" onClick={() => onNavigate('network')}>
              Explore Network Graph
              <ArrowRight className="w-4 h-4" />
            </GlassButton>
            <GlassButton variant="secondary" size="lg" onClick={() => onNavigate('leads')}>
              Review Evidence Leads
            </GlassButton>
          </div>
        </div>
      </GlassCard>

      {/* Animated Count-Up Metrics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3.5">
        <AnimatedStatCard
          label="Persons"
          target={summary.counts.persons}
          icon={<Users className="w-4 h-4" />}
          accentClass="text-[#22d3ee]"
        />
        <AnimatedStatCard
          label="Communications"
          target={summary.counts.communication_events}
          icon={<Mail className="w-4 h-4" />}
          accentClass="text-[#22d3ee]"
        />
        <AnimatedStatCard
          label="Observed Ties"
          target={summary.counts.relationships}
          icon={<Share2 className="w-4 h-4" />}
          accentClass="text-[#34d399]"
        />
        <AnimatedStatCard
          label="Inferred Ties"
          target={summary.counts.inferred_relationships}
          sub="from location evidence"
          icon={<Car className="w-4 h-4" />}
          accentClass="text-[#a78bfa]"
        />
        <AnimatedStatCard
          label="Co-locations"
          target={summary.counts.colocation_events}
          icon={<Car className="w-4 h-4" />}
          accentClass="text-[#a78bfa]"
        />
        <AnimatedStatCard
          label="Places"
          target={summary.counts.places}
          icon={<MapPin className="w-4 h-4" />}
          accentClass="text-[#ffb020]"
        />
        <AnimatedStatCard
          label="Documents"
          target={summary.counts.documents}
          icon={<FileText className="w-4 h-4" />}
          accentClass="text-slate-300"
        />
      </div>

      {/* Prominent Uncertainty Card + Latest Analysis Run Card */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <GlassCard className="lg:col-span-5 p-5 space-y-3" variant="amber">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-amber-200 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-[#ffb020]" />
              Explicit Attribution & Evidence Uncertainty
            </h2>
            <GlassBadge tone="amber">Mandatory Disclosure</GlassBadge>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">
            Derived relationships and location stops are never silently treated as ground-truth identity records:
          </p>
          <div className="space-y-2 text-xs">
            <div className="p-2.5 rounded-[12px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-between">
              <span className="text-slate-300">Location → Person</span>
              <span className="font-mono font-semibold text-amber-300">
                {summary.uncertainty.vehicle_person_attribution.replace(/_/g, ' ')}
              </span>
            </div>
            <div className="p-2.5 rounded-[12px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-between">
              <span className="text-slate-300">Payment / Loyalty Card Ownership</span>
              <span className="font-mono font-semibold text-amber-300">{summary.uncertainty.card_ownership}</span>
            </div>
            <div className="p-2.5 rounded-[12px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-between">
              <span className="text-slate-300">Source Archive Timezone</span>
              <span className="font-mono font-semibold text-slate-300">{summary.uncertainty.source_timezone}</span>
            </div>
          </div>
        </GlassCard>

        <GlassCard className="lg:col-span-7 p-5 space-y-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              <Activity className="w-4 h-4 text-[#34d399]" />
              Latest Versioned Analysis Run
            </h2>
            {latestRun && (
              <div className="flex items-center gap-2">
                <GlassBadge
                  tone={
                    latestRun.status === 'completed'
                      ? 'emerald'
                      : latestRun.status === 'partial'
                      ? 'amber'
                      : 'crimson'
                  }
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  {latestRun.status.toUpperCase()}
                </GlassBadge>
                <span className="font-mono text-xs text-slate-400">Weights {latestRun.weights_version}</span>
              </div>
            )}
          </div>

          {latestRun ? (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs">
                <div className="p-2.5 rounded-[12px] bg-white/[0.04] border border-white/[0.08]">
                  <span className="text-slate-400 block">Mode</span>
                  <span className="font-mono font-semibold text-cyan-300">{latestRun.mode}</span>
                </div>
                <div className="p-2.5 rounded-[12px] bg-white/[0.04] border border-white/[0.08]">
                  <span className="text-slate-400 block">Completed</span>
                  <span className="font-mono text-white" title={runTime.relative}>
                    {runTime.formatted}
                  </span>
                </div>
                <div className="p-2.5 rounded-[12px] bg-white/[0.04] border border-white/[0.08]">
                  <span className="text-slate-400 block">Run ID</span>
                  <span className="font-mono text-slate-300 truncate block">{latestRun.analysis_run_id}</span>
                </div>
              </div>

              {latestRun.parameters?.stages && (
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(latestRun.parameters.stages).map(([stageName, st]) => (
                    <span
                      key={stageName}
                      className={`px-2.5 py-1 rounded-[10px] text-[11px] font-mono border ${
                        st.status === 'ok'
                          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                          : st.status === 'failed'
                          ? 'bg-rose-500/15 text-rose-300 border-rose-500/40'
                          : 'bg-white/[0.04] text-slate-400 border-white/[0.1]'
                      }`}
                    >
                      {stageName}: {st.status} {st.rows !== null ? `(${st.rows})` : ''}
                    </span>
                  ))}
                </div>
              )}

              {latestRun.parameters?.warnings && latestRun.parameters.warnings.length > 0 && (
                <div className="p-2.5 rounded-[12px] bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200">
                  {latestRun.parameters.warnings[0]}
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-slate-400">No analysis run recorded yet. Click "Run analysis" in the top bar.</p>
          )}
        </GlassCard>
      </div>

      {/* Top 5 Figures + Top 5 Evidence Leads */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <GlassCard className="p-5 space-y-3.5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-[#ff3b5c]" />
                Top 5 Figures by Network Influence (PageRank)
              </h2>
              <p className="text-[11px] text-slate-400">Position in the recorded network, not evidence of guilt</p>
            </div>
            <GlassButton size="sm" variant="ghost" onClick={() => onNavigate('people')}>
              All People <ArrowRight className="w-3.5 h-3.5" />
            </GlassButton>
          </div>
          <div className="space-y-2">
            {topFigures.map((node, idx) => {
              const tMeta = tierMeta(node.tier);
              return (
                <div
                  key={node.id}
                  onClick={() => onSelectPerson(node.id)}
                  className="p-3 rounded-[14px] bg-white/[0.04] hover:bg-white/[0.09] border border-white/[0.08] flex items-center justify-between gap-3 cursor-pointer transition"
                >
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs font-bold text-slate-400 w-6">#{idx + 1}</span>
                    <span className={`w-2.5 h-2.5 rounded-full ${tMeta.dotClass}`} />
                    <div>
                      <div className="text-sm font-semibold text-white">{node.label}</div>
                      <div className="text-[11px] text-slate-400">
                        <span className="font-mono">{node.id}</span>
                        {node.department ? ` • ${node.department}` : ''}
                        {node.community_id ? ` • Cluster ${node.community_id}` : ''}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {node.hub_flag && <GlassBadge tone="amber">Verify Hub</GlassBadge>}
                    <span className={`px-2.5 py-0.5 rounded-full text-xs border ${tMeta.bgClass}`}>
                      {tMeta.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </GlassCard>

        <GlassCard className="p-5 space-y-3.5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-[#22d3ee]" />
                Top 5 Investigative Leads & Suggestions
              </h2>
              <p className="text-[11px] text-slate-400">Click any lead to inspect pair evidence & innocent explanations</p>
            </div>
            <GlassButton size="sm" variant="ghost" onClick={() => onNavigate('leads')}>
              All Leads <ArrowRight className="w-3.5 h-3.5" />
            </GlassButton>
          </div>
          <div className="space-y-2">
            {topLeads.map((lead, idx) => {
              const nameA = personsMap.get(lead.person_a)?.display_name || lead.person_a;
              const nameB = personsMap.get(lead.person_b)?.display_name || lead.person_b;
              return (
                <div
                  key={`${lead.method}-${lead.person_a}-${lead.person_b}-${idx}`}
                  onClick={() => {
                    if (onOpenPairEvidence) {
                      onOpenPairEvidence(lead.person_a, lead.person_b, lead);
                    } else {
                      onNavigate('leads');
                    }
                  }}
                  className="p-3 rounded-[14px] bg-white/[0.04] hover:bg-white/[0.09] border border-white/[0.08] flex items-center justify-between gap-3 cursor-pointer transition"
                >
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <GlassBadge tone={lead.basis === 'evidence' ? 'crimson' : 'cyan'}>
                        Rank #{lead.rank_in_method}
                      </GlassBadge>
                      <span className="text-sm font-semibold text-white truncate">
                        {nameA} ↔ {nameB}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400 truncate">
                      {methodLabel(lead.method)} •{' '}
                      {Object.entries(lead.factor_breakdown || {})
                        .slice(0, 2)
                        .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.length : v}`)
                        .join(', ')}
                    </div>
                  </div>
                  <span className="inline-flex items-center gap-1 text-xs text-cyan-300 shrink-0">
                    <Eye className="w-3.5 h-3.5" /> Pair
                  </span>
                </div>
              );
            })}
          </div>
        </GlassCard>
      </div>

      {/* Document Mentions & Place Evidence Inspector (for cases with documents/places) */}
      {docData && (
        <GlassCard className="p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <FileText className="w-4 h-4 text-amber-400" />
                Source Document & Character-Offset Mention Verification
              </h2>
              <p className="text-xs text-slate-400">
                Inspect extracted text and verify entity mentions ({docData.source_file})
              </p>
            </div>
            <div className="flex items-center gap-2">
              {['MC1DOC_e38026415b10', 'MC1DOC_05c5b487aa84'].map((did) => (
                <button
                  key={did}
                  onClick={() => setSelectedDocId(did)}
                  className={`px-3 py-1 rounded-[10px] font-mono text-xs border transition ${
                    selectedDocId === did
                      ? 'bg-[#22d3ee]/20 text-cyan-200 border-[#22d3ee]/45'
                      : 'bg-white/[0.04] text-slate-400 border-white/[0.08] hover:text-white'
                  }`}
                >
                  {did}
                </button>
              ))}
            </div>
          </div>

          <div className="p-3.5 rounded-[14px] bg-white/[0.03] border border-white/[0.08] text-xs text-slate-200 leading-relaxed font-mono">
            {docData.body}
          </div>

          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-300">
              Extracted Entity Mentions ({docData.mentions?.length || 0})
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {(docData.mentions || []).map((m: any) => (
                <div
                  key={m.mention_id}
                  className="p-3 rounded-[12px] bg-white/[0.04] border border-white/[0.08] flex flex-col justify-between gap-2 text-xs"
                >
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-white">"{m.matched_text}"</span>
                      <GlassBadge
                        tone={
                          m.review_status === 'confirmed'
                            ? 'emerald'
                            : m.review_status === 'rejected'
                            ? 'crimson'
                            : 'amber'
                        }
                      >
                        {m.review_status}
                      </GlassBadge>
                    </div>
                    <div className="font-mono text-[11px] text-slate-400 mt-1">
                      {m.entity_type}: {m.entity_id} • chars {m.start_char}..{m.end_char}
                    </div>
                  </div>
                  <div className="flex items-center justify-end gap-1.5 pt-2 border-t border-white/[0.06]">
                    <GlassButton
                      size="sm"
                      variant="emerald"
                      disabled={!canEditCase}
                      onClick={() => handleReviewMention(m.mention_id, 'confirmed')}
                    >
                      <CheckCircle2 className="w-3 h-3" /> Confirm
                    </GlassButton>
                    <GlassButton
                      size="sm"
                      variant="crimson"
                      disabled={!canEditCase}
                      onClick={() => handleReviewMention(m.mention_id, 'rejected')}
                    >
                      <XCircle className="w-3 h-3" /> Reject
                    </GlassButton>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </GlassCard>
      )}
    </div>
  );
};
