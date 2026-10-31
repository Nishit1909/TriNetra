import React, { useEffect, useMemo, useState } from 'react';
import { Sparkles, Eye, CheckCircle2, XCircle, Clock, Car, Info, Scale } from 'lucide-react';
import { api } from '../../api/client';
import {
  AnalysisMode,
  InferredRelationship,
  PersonRecord,
  PredictedLink,
  StrongTie,
} from '../../api/types';
import { GlassBadge, GlassButton, GlassCard, GlassSkeleton } from '../../components/glass';
import { methodLabel } from '../../utils/format';
import { PairEvidenceModal } from './PairEvidenceModal';

interface LeadsViewProps {
  caseId: string;
  mode: AnalysisMode;
  canEditCase: boolean;
  onSelectPerson: (personId: string) => void;
  onToast: (msg: string, tone?: 'cyan' | 'emerald' | 'crimson' | 'amber') => void;
}

export const LeadsView: React.FC<LeadsViewProps> = ({
  caseId,
  mode,
  canEditCase,
  onSelectPerson,
  onToast,
}) => {
  const [activeTab, setActiveTab] = useState<'evidence' | 'structural_pattern' | 'meetings' | 'strongest'>('evidence');
  const [strongTies, setStrongTies] = useState<StrongTie[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [predictedLinks, setPredictedLinks] = useState<PredictedLink[]>([]);
  const [scoreNote, setScoreNote] = useState<string>(
    'Scores rank pairs within one method; they are not probabilities and are not comparable across methods.'
  );
  const [inferredMeetings, setInferredMeetings] = useState<InferredRelationship[]>([]);
  const [personsMap, setPersonsMap] = useState<Map<string, PersonRecord>>(new Map());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runModeNote, setRunModeNote] = useState<string | null>(null);
  const [selectedPair, setSelectedPair] = useState<{ a: string; b: string; link?: PredictedLink } | null>(null);

  const loadData = () => {
    setLoading(true);
    setLoadError(null);
    Promise.all([
      api.getPersons(caseId, { limit: 100 }),
      api.listAnalysisRuns(caseId),
      api.getInferredLeads(caseId, 'strong,medium,weak', 50, 0).catch(() => ({ items: [] })),
    ]).then(async ([pRes, runs, leadsRes]) => {
      const pMap = new Map<string, PersonRecord>();
      (pRes.items || []).forEach((p) => pMap.set(p.person_id, p));
      setPersonsMap(pMap);
      setInferredMeetings(leadsRes.items || []);

      const sameMode = runs.find((r) => r.mode === mode && (r.status === 'completed' || r.status === 'partial'));
      const targetRun = sameMode || runs.find((r) => r.status === 'completed' || r.status === 'partial');
      setRunModeNote(
        targetRun && !sameMode
          ? `No analysis has been run in ${mode === 'observed_only' ? 'Observed only' : 'Observed + inferred'} mode yet, so these are the results of the latest ${targetRun.mode === 'observed_only' ? 'Observed only' : 'Observed + inferred'} run. Use Run analysis for this mode.`
          : null,
      );
      if (targetRun) {
        setRunId(targetRun.analysis_run_id);
        const linksRes = await api.getPredictedLinks(caseId, targetRun.analysis_run_id, { limit: 100 });
        setPredictedLinks(linksRes.items || []);
        api.getStrongestTies(caseId, targetRun.analysis_run_id).then((r) => setStrongTies(r.items || [])).catch(() => setStrongTies([]));
        if (linksRes.score_note) setScoreNote(linksRes.score_note);
      } else {
        setRunId(null);
        setPredictedLinks([]);
        setStrongTies([]);
      }
      setLoading(false);
    }).catch((err) => {
      setLoading(false);
      setLoadError(err?.message || 'Could not load leads.');
    });
  };

  useEffect(() => {
    loadData();
  }, [caseId, mode]);

  const evidenceLeads = useMemo(
    () => predictedLinks.filter((l) => l.basis === 'evidence'),
    [predictedLinks]
  );
  const patternLeads = useMemo(
    () => predictedLinks.filter((l) => l.basis === 'structural_pattern'),
    [predictedLinks]
  );

  const initials = (name: string) =>
    name
      .split(' ')
      .map((s) => s[0])
      .join('')
      .slice(0, 2)
      .toUpperCase();

  return (
    <div className="space-y-5">
      {loadError && (
        <div role="alert" className="rounded-[14px] border border-[#ff3b5c]/35 bg-[#ff3b5c]/10 px-4 py-3 text-sm text-[#ff9aab] flex items-center justify-between gap-3">
          <span>{loadError}</span>
          <button onClick={loadData} className="px-3 py-1 rounded-[10px] border border-white/20 text-white text-xs hover:bg-white/10">Retry</button>
        </div>
      )}
      {runModeNote && (
        <div className="rounded-[14px] border border-amber-400/30 bg-amber-400/[0.07] px-4 py-3 text-sm text-amber-200">{runModeNote}</div>
      )}
      {/* Header & Tabs */}
      <GlassCard className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-bold text-white flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-[#ff3b5c]" />
              Investigative Leads & Unrecorded Link Suggestions
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">{scoreNote}</p>
          </div>
          <div className="flex items-center gap-1.5 p-1 rounded-[14px] bg-white/[0.05] border border-white/[0.1]">
            <button
              onClick={() => setActiveTab('evidence')}
              className={`px-3.5 py-1.5 rounded-[10px] text-xs font-medium transition ${
                activeTab === 'evidence'
                  ? 'bg-[#ff3b5c]/20 text-rose-200 border border-[#ff3b5c]/40'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Evidence Leads ({evidenceLeads.length})
            </button>
            <button
              onClick={() => setActiveTab('structural_pattern')}
              className={`px-3.5 py-1.5 rounded-[10px] text-xs font-medium transition ${
                activeTab === 'structural_pattern'
                  ? 'bg-[#22d3ee]/20 text-cyan-200 border border-[#22d3ee]/40'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Pattern Suggestions ({patternLeads.length})
            </button>
            <button
              onClick={() => setActiveTab('meetings')}
              className={`px-3.5 py-1.5 rounded-[10px] text-xs font-medium transition ${
                activeTab === 'meetings'
                  ? 'bg-[#a78bfa]/20 text-violet-200 border border-[#a78bfa]/40'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Inferred Meetings ({inferredMeetings.length})
            </button>
            <button
              onClick={() => setActiveTab('strongest')}
              className={`px-3.5 py-1.5 rounded-[10px] text-xs font-medium transition ${
                activeTab === 'strongest'
                  ? 'bg-amber-500/20 text-amber-200 border border-amber-400/40'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Strongest Ties ({strongTies.length})
            </button>
          </div>
        </div>
      </GlassCard>

      {loading ? (
        <div className="space-y-3">
          <GlassSkeleton className="h-24 w-full" />
          <GlassSkeleton className="h-24 w-full" />
          <GlassSkeleton className="h-24 w-full" />
        </div>
      ) : activeTab === 'strongest' ? (
        <div className="space-y-3">
          <GlassCard className="p-3 text-xs text-slate-400">
            Pairs linked by the most independent kinds of evidence (communication, money, location, recorded ties), then by
            combined strength. Unlike leads, these pairs may communicate openly. Strong contact is not evidence of wrongdoing.
          </GlassCard>
          {strongTies.length === 0 ? (
            <GlassCard className="p-8 text-center text-sm text-slate-400">Run analysis to see the strongest ties.</GlassCard>
          ) : (
            strongTies.map((t, idx) => (
              <GlassCard key={`${t.person_a}-${t.person_b}`} className="p-4 flex flex-wrap items-center justify-between gap-3">
                <div className="space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-amber-500/20 text-amber-200 border border-amber-400/40">
                      #{idx + 1} · {t.corroboration} evidence type{t.corroboration === 1 ? '' : 's'}
                    </span>
                    <span className="font-semibold text-white text-sm">
                      {t.name_a || t.person_a} <span className="text-slate-500">↔</span> {t.name_b || t.person_b}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {t.sources.map((s) => (
                      <GlassBadge key={s} tone={s === 'location' ? 'violet' : s === 'money' ? 'emerald' : s === 'communication' ? 'cyan' : 'slate'}>
                        {s}
                      </GlassBadge>
                    ))}
                    <span className="text-[11px] font-mono text-slate-400 self-center">
                      strength {t.strength} · {t.types.join(', ')}
                    </span>
                  </div>
                </div>
                <GlassButton onClick={() => setSelectedPair({ a: t.person_a, b: t.person_b })}>
                  Inspect Evidence
                </GlassButton>
              </GlassCard>
            ))
          )}
        </div>
      ) : activeTab === 'meetings' ? (
        /* Inferred Meetings Tab */
        <div className="space-y-3">
          {inferredMeetings.length === 0 ? (
            <GlassCard className="p-8 text-center text-sm text-slate-400">
              No inferred meetings (same place, same time) recorded for this case.
            </GlassCard>
          ) : (
            inferredMeetings.map((m, idx) => {
              const pA = personsMap.get(m.person_a);
              const pB = personsMap.get(m.person_b);
              const nameA = pA?.display_name || m.person_a;
              const nameB = pB?.display_name || m.person_b;
              return (
                <GlassCard
                  key={`${m.person_a}-${m.person_b}-${idx}`}
                  interactive
                  onClick={() => setSelectedPair({ a: m.person_a, b: m.person_b })}
                  className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4"
                >
                  <div className="space-y-2 flex-1">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-[#a78bfa]/20 text-violet-200 border border-[#a78bfa]/40">
                        Rank #{idx + 1} • Inferred Co-location ({m.lead_level})
                      </span>
                      <GlassBadge tone="violet">
                        <Car className="w-3 h-3" />
                        {m.person_attribution === 'uploaded_location_as_given'
                          ? 'Inferred from uploaded locations (presence, not proof of contact)'
                          : 'Inferred from vehicle GPS (assigned driver assumed)'}
                      </GlassBadge>
                      <span className="font-semibold text-white text-sm">
                        {nameA} <span className="text-slate-500">↔</span> {nameB}
                      </span>
                    </div>

                    {/* Signal chips */}
                    <div className="flex flex-wrap gap-1.5">
                      {m.factors?.private_days && Number(m.factors.private_days) > 0 && (
                        <span className="px-2.5 py-0.5 rounded-md bg-white/[0.06] text-xs font-mono text-slate-200">
                          {m.factors.private_days} private days
                        </span>
                      )}
                      {m.factors?.home_visits && Number(m.factors.home_visits) > 0 && (
                        <span className="px-2.5 py-0.5 rounded-md bg-amber-500/15 text-xs font-mono text-amber-200">
                          {m.factors.home_visits} home visits
                        </span>
                      )}
                      {m.factors?.after_hours_private && Number(m.factors.after_hours_private) > 0 && (
                        <span className="px-2.5 py-0.5 rounded-md bg-rose-500/15 text-xs font-mono text-rose-200">
                          {m.factors.after_hours_private} after-hours
                        </span>
                      )}
                      {m.factors?.group_gatherings && Number(m.factors.group_gatherings) > 0 && (
                        <span className="px-2.5 py-0.5 rounded-md bg-white/[0.05] text-xs font-mono text-slate-300">
                          {m.factors.group_gatherings} group gatherings
                        </span>
                      )}
                    </div>

                    {/* Innocent explanation inline */}
                    {m.possible_innocent_explanations && (
                      <div className="text-xs text-emerald-300/90 flex items-center gap-1.5 pt-0.5">
                        <Scale className="w-3.5 h-3.5 shrink-0" />
                        <span>Consider: {m.possible_innocent_explanations}</span>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <GlassButton size="sm" variant="secondary">
                      <Eye className="w-3.5 h-3.5" />
                      Pair Evidence
                    </GlassButton>
                  </div>
                </GlassCard>
              );
            })
          )}
        </div>
      ) : (
        /* Evidence Leads & Pattern Suggestions Tabs */
        <div className="space-y-3">
          {(activeTab === 'evidence' ? evidenceLeads : patternLeads).length === 0 ? (
            <GlassCard className="p-8 text-center text-sm text-slate-400">
              {activeTab === 'evidence' && mode === 'observed_only'
                ? 'Switch analysis mode to "Observed + Inferred" in the top bar to include location-based (co-location) evidence leads.'
                : 'No leads found in this category for the current analysis run.'}
            </GlassCard>
          ) : (
            (activeTab === 'evidence' ? evidenceLeads : patternLeads).map((lead) => {
              const pA = personsMap.get(lead.person_a);
              const pB = personsMap.get(lead.person_b);
              const nameA = pA?.display_name || lead.person_a;
              const nameB = pB?.display_name || lead.person_b;
              return (
                <GlassCard
                  key={`${lead.method}-${lead.person_a}-${lead.person_b}`}
                  interactive
                  onClick={() => setSelectedPair({ a: lead.person_a, b: lead.person_b, link: lead })}
                  className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4"
                >
                  <div className="space-y-2.5 flex-1">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-xs font-mono font-bold border ${
                          lead.basis === 'evidence'
                            ? 'bg-[#ff3b5c]/20 text-[#ff3b5c] border-[#ff3b5c]/45'
                            : 'bg-[#22d3ee]/20 text-[#22d3ee] border-[#22d3ee]/45'
                        }`}
                      >
                        Rank #{lead.rank_in_method}
                      </span>
                      <GlassBadge tone={lead.basis === 'evidence' ? 'crimson' : 'cyan'}>
                        {methodLabel(lead.method)}
                      </GlassBadge>
                      {lead.factor_breakdown?.basis === 'inferred' && (
                        <GlassBadge tone="violet">
                          {caseId.startsWith('CASE_UPLOAD_')
                            ? 'Inferred from uploaded locations (presence, not proof of contact)'
                            : 'Inferred from vehicle GPS (assigned driver assumed)'}
                        </GlassBadge>
                      )}
                      {lead.review_status === 'confirmed' && (
                        <GlassBadge tone="emerald">
                          <CheckCircle2 className="w-3 h-3" /> Confirmed
                        </GlassBadge>
                      )}
                      {lead.review_status === 'dismissed' && (
                        <GlassBadge tone="amber">
                          <XCircle className="w-3 h-3" /> Dismissed
                        </GlassBadge>
                      )}
                    </div>

                    {/* Avatars + Pair Names */}
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="flex items-center gap-2">
                        <span className="w-7 h-7 rounded-full bg-rose-500/20 border border-rose-400/40 flex items-center justify-center font-mono text-xs font-bold text-rose-200">
                          {initials(nameA)}
                        </span>
                        <div>
                          <div className="text-sm font-semibold text-white">{nameA}</div>
                          <div className="text-[11px] font-mono text-slate-400">
                            {lead.person_a} {pA?.department ? `• ${pA.department}` : ''}
                          </div>
                        </div>
                      </div>
                      <span className="text-slate-500 font-mono text-sm">↔</span>
                      <div className="flex items-center gap-2">
                        <span className="w-7 h-7 rounded-full bg-cyan-500/20 border border-cyan-400/40 flex items-center justify-center font-mono text-xs font-bold text-cyan-200">
                          {initials(nameB)}
                        </span>
                        <div>
                          <div className="text-sm font-semibold text-white">{nameB}</div>
                          <div className="text-[11px] font-mono text-slate-400">
                            {lead.person_b} {pB?.department ? `• ${pB.department}` : ''}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Factor Breakdown Signal Chips */}
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(lead.factor_breakdown || {}).map(([k, v]) => {
                        if (k === 'examples' && Array.isArray(v)) {
                          return (
                            <span
                              key={k}
                              className="px-2.5 py-0.5 rounded-md bg-white/[0.04] border border-white/[0.08] text-[11px] font-mono text-slate-300"
                            >
                              examples: {v.slice(0, 3).join(', ')}
                            </span>
                          );
                        }
                        return (
                          <span
                            key={k}
                            className="px-2.5 py-0.5 rounded-md bg-white/[0.06] border border-white/[0.1] text-[11px] font-mono text-slate-200"
                          >
                            {k}: <strong className="text-white">{String(v)}</strong>
                          </span>
                        );
                      })}
                    </div>

                    <div className="text-[11px] text-emerald-300/90 flex items-center gap-1.5">
                      <Info className="w-3.5 h-3.5 shrink-0" />
                      <span>
                        Consider innocent explanations: routine shift overlap, group gatherings, or shared departmental contacts. Click to inspect full pair evidence.
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <GlassButton size="sm" variant="primary">
                      <Eye className="w-3.5 h-3.5" />
                      Inspect Evidence & Review
                    </GlassButton>
                  </div>
                </GlassCard>
              );
            })
          )}
        </div>
      )}

      <PairEvidenceModal
        caseId={caseId}
        runId={runId}
        pair={selectedPair}
        personsMap={personsMap}
        canEditCase={canEditCase}
        onClose={() => setSelectedPair(null)}
        onSelectPerson={onSelectPerson}
        onReviewUpdated={loadData}
        onToast={onToast}
      />
    </div>
  );
};
