import React, { useEffect, useState } from 'react';
import {
  X,
  Scale,
  Mail,
  Car,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  ShieldCheck,
  History,
} from 'lucide-react';
import { api } from '../../api/client';
import { PairEvidenceResponse, PersonRecord, PredictedLink } from '../../api/types';
import { GlassBadge, GlassButton, GlassCard, GlassSkeleton } from '../../components/glass';
import { formatIST, methodLabel } from '../../utils/format';

interface PairEvidenceModalProps {
  caseId: string;
  runId: string | null;
  pair: { a: string; b: string; link?: PredictedLink } | null;
  personsMap: Map<string, PersonRecord>;
  canEditCase: boolean;
  onClose: () => void;
  onSelectPerson: (personId: string) => void;
  onReviewUpdated: () => void;
  onToast: (msg: string, tone?: 'cyan' | 'emerald' | 'crimson' | 'amber') => void;
}

export const PairEvidenceModal: React.FC<PairEvidenceModalProps> = ({
  caseId,
  runId,
  pair,
  personsMap,
  canEditCase,
  onClose,
  onSelectPerson,
  onReviewUpdated,
  onToast,
}) => {
  const [evidence, setEvidence] = useState<PairEvidenceResponse | null>(null);
  const [reviews, setReviews] = useState<any[]>([]);
  const [resolvedRunId, setResolvedRunId] = useState<string | null>(runId);
  const [resolvedLink, setResolvedLink] = useState<PredictedLink | undefined>(pair?.link);
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!pair) return;
    let cancelled = false;
    setLoading(true);
    setResolvedLink(pair.link);
    (async () => {
      try {
        let activeRun = runId;
        if (!activeRun) {
          const runs = await api.listAnalysisRuns(caseId).catch(() => []);
          activeRun = runs[0]?.analysis_run_id || null;
        }
        if (cancelled) return;
        setResolvedRunId(activeRun);

        const [ev, rev, linksRes] = await Promise.all([
          api.getPairEvidence(caseId, pair.a, pair.b).catch(() => null),
          activeRun ? api.getPredictedLinkReviews(caseId, activeRun, pair.a, pair.b).catch(() => []) : Promise.resolve([]),
          activeRun && !pair.link
            ? api.getPredictedLinks(caseId, activeRun, { person_id: pair.a, limit: 100 }).catch(() => ({ items: [] }))
            : Promise.resolve({ items: [] }),
        ]);
        if (cancelled) return;
        setEvidence(ev);
        setReviews(rev || []);
        if (!pair.link && linksRes?.items?.length) {
          const [a, b] = [pair.a, pair.b].sort();
          const match = linksRes.items.find((l: PredictedLink) => l.person_a === a && l.person_b === b);
          if (match) setResolvedLink(match);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [caseId, runId, pair]);

  if (!pair) return null;

  const pA = personsMap.get(pair.a);
  const pB = personsMap.get(pair.b);

  const handleReview = async (status: 'confirmed' | 'dismissed') => {
    if (!resolvedRunId) {
      onToast('Run analysis for this case first; reviews are attached to an analysis run.', 'amber');
      return;
    }
    if (!reason.trim()) {
      onToast('Write a short reason first; every decision is recorded with its rationale.', 'amber');
      return;
    }
    setSubmitting(true);
    try {
      await api.reviewPredictedLink(caseId, resolvedRunId, pair.a, pair.b, { status, reason });
      const updatedRevs = await api.getPredictedLinkReviews(caseId, resolvedRunId, pair.a, pair.b).catch(() => null);
      if (updatedRevs) setReviews(updatedRevs);
      setReason('');
      onReviewUpdated();
      onToast(`Lead marked as ${status}`, status === 'confirmed' ? 'emerald' : 'amber');
    } catch (err: any) {
      onToast(err?.message || 'Failed to save review', 'crimson');
    } finally {
      setSubmitting(false);
    }
  };

  const innocentExplanations =
    evidence?.inferred_relationships
      ?.map((r) => r.possible_innocent_explanations)
      .filter(Boolean) || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in duration-150">
      <div className="w-full max-w-4xl max-h-[90vh] rounded-[24px] bg-[#080d1a]/95 border border-white/[0.16] shadow-[0_25px_80px_rgba(0,0,0,0.85)] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="p-5 border-b border-white/[0.1] flex items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <GlassBadge tone="cyan">Pair Evidence Inspection</GlassBadge>
              {resolvedLink && (
                <GlassBadge tone={resolvedLink.basis === 'evidence' ? 'crimson' : 'violet'}>
                  Rank #{resolvedLink.rank_in_method} in {methodLabel(resolvedLink.method)}
                </GlassBadge>
              )}
            </div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <button
                onClick={() => {
                  onClose();
                  onSelectPerson(pair.a);
                }}
                className="hover:text-[#22d3ee] underline-offset-4 hover:underline"
              >
                {pA?.display_name || pair.a}
              </button>
              <span className="text-slate-500">↔</span>
              <button
                onClick={() => {
                  onClose();
                  onSelectPerson(pair.b);
                }}
                className="hover:text-[#22d3ee] underline-offset-4 hover:underline"
              >
                {pB?.display_name || pair.b}
              </button>
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close pair evidence modal"
            className="p-2 rounded-[12px] bg-white/[0.06] hover:bg-white/[0.14] text-slate-300"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {loading ? (
            <div className="space-y-4">
              <GlassSkeleton className="h-24 w-full" />
              <GlassSkeleton className="h-36 w-full" />
              <GlassSkeleton className="h-36 w-full" />
            </div>
          ) : (
            <>
              {/* Side-by-side People */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[
                  { id: pair.a, rec: pA },
                  { id: pair.b, rec: pB },
                ].map(({ id, rec }) => (
                  <GlassCard key={id} className="p-4 flex items-center justify-between">
                    <div>
                      <div className="font-semibold text-white">{rec?.display_name || id}</div>
                      <div className="text-xs text-slate-400">
                        {rec?.department || 'Recorded Subject'} {rec?.job_title ? `• ${rec.job_title}` : ''}
                      </div>
                      <div className="font-mono text-[11px] text-cyan-300 mt-1">{id}</div>
                    </div>
                    <GlassButton
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        onClose();
                        onSelectPerson(id);
                      }}
                    >
                      Open Profile
                    </GlassButton>
                  </GlassCard>
                ))}
              </div>

              {/* Prominent Innocent Explanations ("Consider" Card) */}
              <GlassCard className="p-4 border-emerald-400/35 bg-emerald-500/[0.07]">
                <div className="flex items-start gap-3">
                  <Scale className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                  <div className="space-y-1.5">
                    <h3 className="text-sm font-semibold text-emerald-200">
                      Consider — Possible Innocent Explanations & Context
                    </h3>
                    {innocentExplanations.length > 0 ? (
                      <ul className="list-disc list-inside text-xs text-slate-200 space-y-1">
                        {innocentExplanations.map((exp, idx) => (
                          <li key={idx}>{exp}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-slate-200">
                        Shared contacts or structural proximity can arise from routine departmental overlap, shared shift schedules, or common supervisors without direct coordination.
                      </p>
                    )}
                    {evidence?.uncertainty?.note && (
                      <div className="pt-1.5 text-[11px] text-amber-200 flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                        <span>
                          <strong>Uncertainty:</strong> {evidence.uncertainty.note}
                          {evidence.uncertainty.person_attribution &&
                            ` (${evidence.uncertainty.person_attribution})`}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </GlassCard>

              {/* Factor Breakdown */}
              {(resolvedLink?.factor_breakdown || (evidence?.inferred_relationships && evidence.inferred_relationships.length > 0)) && (
                <GlassCard className="p-4 space-y-3">
                  <h3 className="text-sm font-semibold text-white">Signal & Factor Breakdown</h3>
                  <div className="flex flex-wrap gap-2">
                    {resolvedLink?.factor_breakdown &&
                      Object.entries(resolvedLink.factor_breakdown).map(([k, v]) => (
                        <div
                          key={k}
                          className="px-3 py-1.5 rounded-[12px] bg-white/[0.05] border border-white/[0.1] text-xs"
                        >
                          <span className="text-slate-400">{k}: </span>
                          <span className="font-mono font-semibold text-white">
                            {Array.isArray(v) ? v.join(', ') : String(v)}
                          </span>
                        </div>
                      ))}
                    {evidence?.inferred_relationships?.[0]?.factors &&
                      Object.entries(evidence.inferred_relationships[0].factors)
                        .filter(([k]) => k !== 'supporting_colocation_ids')
                        .map(([k, v]) => (
                          <div
                            key={k}
                            className="px-3 py-1.5 rounded-[12px] bg-violet-500/[0.08] border border-violet-400/25 text-xs"
                          >
                            <span className="text-violet-300">{k.replace(/_/g, ' ')}: </span>
                            <span className="font-mono font-semibold text-white">{String(v)}</span>
                          </div>
                        ))}
                  </div>
                </GlassCard>
              )}

              {/* Co-location Events & Emails */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <GlassCard className="p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                      <Car className="w-4 h-4 text-[#a78bfa]" />
                      Inferred Co-location Events ({evidence?.colocation_events?.total ?? 0})
                    </h3>
                    <GlassBadge tone="violet">Assigned driver assumed</GlassBadge>
                  </div>
                  {!evidence?.colocation_events?.items?.length ? (
                    <p className="text-xs text-slate-400">No vehicle GPS co-location events recorded for this pair.</p>
                  ) : (
                    <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                      {evidence.colocation_events.items.map((co: any) => (
                        <div
                          key={co.colocation_id}
                          className="p-2.5 rounded-[12px] bg-white/[0.04] border border-white/[0.08] text-xs space-y-1"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-mono font-semibold text-violet-300">
                              {co.place_id} ({co.place_type})
                            </span>
                            <span className="font-mono text-[11px] text-slate-400">
                              {co.overlap_min} min overlap
                            </span>
                          </div>
                          <div className="text-[11px] text-slate-300 font-mono">
                            {formatIST(co.overlap_start).formatted}
                          </div>
                          <div className="flex flex-wrap gap-1.5 pt-0.5">
                            {co.after_hours && <GlassBadge tone="amber">After hours</GlassBadge>}
                            {co.group_gathering && (
                              <GlassBadge tone="slate">Group ({co.vehicles_present} vehicles)</GlassBadge>
                            )}
                            <span className="text-[10px] font-mono text-slate-400">
                              Cars: {co.vehicle_id_a} & {co.vehicle_id_b}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </GlassCard>

                <GlassCard className="p-4 space-y-3">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Mail className="w-4 h-4 text-[#22d3ee]" />
                    Recorded Emails ({evidence?.emails?.total ?? 0})
                  </h3>
                  {!evidence?.emails?.items?.length ? (
                    <p className="text-xs text-slate-400">
                      No recorded direct email communication between these two people.
                    </p>
                  ) : (
                    <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                      {evidence.emails.items.map((em: any) => (
                        <div
                          key={em.communication_id}
                          className="p-2.5 rounded-[12px] bg-white/[0.04] border border-white/[0.08] text-xs space-y-1"
                        >
                          <div className="font-medium text-white">{em.subject || '(No subject)'}</div>
                          <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                            <span>
                              {em.source_person_id} → {em.target_person_id}
                            </span>
                            <span>{formatIST(em.sent_at).formatted}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </GlassCard>
              </div>

              {/* Analyst Review Box */}
              {resolvedRunId && (
                <GlassCard className="p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                      <ShieldCheck className="w-4 h-4 text-emerald-400" />
                      Analyst Lead Review & Audit Trail
                    </h3>
                    {!canEditCase && (
                      <GlassBadge tone="slate">Viewer access (Read-only)</GlassBadge>
                    )}
                  </div>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    disabled={!canEditCase || submitting}
                    placeholder={
                      canEditCase
                        ? 'Enter investigative rationale for confirming or dismissing this lead...'
                        : 'Viewer role cannot submit lead reviews.'
                    }
                    rows={2}
                    className="w-full rounded-[12px] bg-white/[0.05] border border-white/[0.12] p-3 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-[#22d3ee]"
                  />
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[11px] text-slate-400">
                      Every review decision is recorded in the append-only case audit log.
                    </span>
                    <div className="flex items-center gap-2" title={!canEditCase ? 'Viewer access' : undefined}>
                      <GlassButton
                        size="sm"
                        variant="emerald"
                        disabled={!canEditCase || submitting}
                        onClick={() => handleReview('confirmed')}
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Confirm Lead
                      </GlassButton>
                      <GlassButton
                        size="sm"
                        variant="crimson"
                        disabled={!canEditCase || submitting}
                        onClick={() => handleReview('dismissed')}
                      >
                        <XCircle className="w-3.5 h-3.5" />
                        Dismiss Lead
                      </GlassButton>
                    </div>
                  </div>

                  {reviews.length > 0 && (
                    <div className="pt-3 border-t border-white/[0.08] space-y-1.5">
                      <div className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
                        <History className="w-3.5 h-3.5 text-cyan-400" />
                        Review History ({reviews.length})
                      </div>
                      {reviews.map((rv, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between text-xs bg-white/[0.03] px-3 py-1.5 rounded-[10px]"
                        >
                          <span>
                            <strong className={rv.status === 'confirmed' ? 'text-emerald-400' : 'text-rose-400'}>
                              {rv.status.toUpperCase()}
                            </strong>{' '}
                            by <span className="font-mono text-slate-300">{rv.reviewed_by}</span>
                            {rv.reason ? ` — "${rv.reason}"` : ''}
                          </span>
                          <span className="font-mono text-[11px] text-slate-400">
                            <Clock className="w-3 h-3 inline mr-1" />
                            {formatIST(rv.reviewed_at).formatted}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </GlassCard>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
