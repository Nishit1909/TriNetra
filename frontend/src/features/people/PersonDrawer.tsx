import React, { useEffect, useState } from 'react';
import {
  X,
  AlertTriangle,
  Copy,
  Check,
  Mail,
  Car,
  FileText,
  Sparkles,
  Users,
  Link2,
  Clock,
  ShieldAlert,
  ExternalLink,
} from 'lucide-react';
import { api } from '../../api/client';
import { AnalysisMode, NodeTier, PersonExplainResponse, PersonProfile, TimelineEvent } from '../../api/types';
import { GlassBadge, GlassButton, GlassCard, GlassSkeleton } from '../../components/glass';
import { copyToClipboard, formatIST, methodLabel, tierMeta } from '../../utils/format';

interface PersonDrawerProps {
  caseId: string;
  personId: string | null;
  mode: AnalysisMode;
  tier?: NodeTier;
  onClose: () => void;
  onSelectPerson: (personId: string) => void;
  onOpenPairEvidence: (personA: string, personB: string) => void;
  onToast: (msg: string, tone?: 'cyan' | 'emerald' | 'crimson' | 'amber') => void;
}

const RadialRankGauge: React.FC<{ label: string; rank: number; total: number; color: string }> = ({
  label,
  rank,
  total,
  color,
}) => {
  const pct = total > 0 ? Math.max(0.08, (total - rank + 1) / total) : 0;
  const r = 24;
  const circ = 2 * Math.PI * r;
  const dash = pct * circ;

  return (
    <div className="flex items-center gap-3 p-3 rounded-[16px] bg-white/[0.04] border border-white/[0.08]">
      <div className="relative w-14 h-14 flex items-center justify-center shrink-0">
        <svg className="w-14 h-14 -rotate-90" viewBox="0 0 60 60">
          <circle cx="30" cy="30" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
          <circle
            cx="30"
            cy="30"
            r={r}
            fill="none"
            stroke={color}
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circ}`}
          />
        </svg>
        <span className="absolute font-mono text-xs font-semibold text-white">#{rank}</span>
      </div>
      <div>
        <div className="text-xs text-slate-400">{label}</div>
        <div className="font-mono text-sm font-semibold text-white">
          Rank {rank} <span className="text-slate-400 font-normal">of {total}</span>
        </div>
      </div>
    </div>
  );
};

export const PersonDrawer: React.FC<PersonDrawerProps> = ({
  caseId,
  personId,
  mode,
  tier,
  onClose,
  onSelectPerson,
  onOpenPairEvidence,
  onToast,
}) => {
  const [profile, setProfile] = useState<PersonProfile | null>(null);
  const [explain, setExplain] = useState<PersonExplainResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'explain' | 'timeline'>('explain');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!personId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.getPersonProfile(caseId, personId).catch(() => null),
      api.getPersonExplain(caseId, personId, { mode }).catch(() => null),
      api.getPersonTimeline(caseId, personId, 30, 0).catch(() => ({ items: [] })),
    ]).then(([prof, exp, tl]) => {
      if (cancelled) return;
      setProfile(prof);
      setExplain(exp);
      setTimeline(tl?.items || []);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [caseId, personId, mode]);

  if (!personId) return null;

  const computedTier: NodeTier =
    tier ||
    (explain
      ? explain.ranks.pagerank <= 3 || (explain.ranks.pagerank <= 10 && explain.metrics.hub_flag)
        ? 'key_figure'
        : explain.ranks.pagerank <= 10
        ? 'secondary_figure'
        : explain.ranks.betweenness <= 5
        ? 'connector'
        : 'neutral'
      : 'neutral');
  const tMeta = tierMeta(computedTier);

  const handleCopyId = async () => {
    if (await copyToClipboard(personId)) {
      setCopied(true);
      onToast(`Copied ID ${personId}`, 'cyan');
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-2xl bg-[#070b16]/95 backdrop-blur-2xl border-l border-white/[0.14] shadow-[0_0_80px_rgba(0,0,0,0.85)] flex flex-col animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div className="p-5 border-b border-white/[0.1] flex items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${tMeta.bgClass}`}>
              <span className={`w-2 h-2 rounded-full ${tMeta.dotClass}`} />
              {tMeta.label}
            </span>
            {explain?.metrics?.hub_flag && (
              <GlassBadge tone="amber">
                <AlertTriangle className="w-3.5 h-3.5" />
                Verify Hub (Unusually Many Contacts)
              </GlassBadge>
            )}
            <button
              onClick={handleCopyId}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white/[0.06] hover:bg-white/[0.12] border border-white/[0.1] font-mono text-xs text-slate-300 transition"
              title="Copy person ID"
            >
              {personId}
              {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3 text-slate-400" />}
            </button>
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight">
            {profile?.display_name || explain?.person?.display_name || personId}
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            {profile?.job_title || explain?.person?.job_title || 'Recorded network subject'}
            {(profile?.department || explain?.person?.department) &&
              ` • ${profile?.department || explain?.person?.department}`}
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close person drawer"
          className="p-2 rounded-[12px] bg-white/[0.06] hover:bg-white/[0.14] border border-white/[0.1] text-slate-300 hover:text-white transition"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Quick Counts & Tab Switcher */}
      <div className="px-5 py-3 border-b border-white/[0.08] flex flex-wrap items-center justify-between gap-3 bg-white/[0.02]">
        <div className="flex items-center gap-4 text-xs text-slate-300">
          <span className="inline-flex items-center gap-1.5">
            <Mail className="w-3.5 h-3.5 text-cyan-400" />
            <strong className="font-mono text-white">{profile?.counts?.emails ?? 0}</strong> emails
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Car className="w-3.5 h-3.5 text-violet-400" />
            <strong className="font-mono text-white">{profile?.counts?.colocations ?? 0}</strong> co-locations
          </span>
          <span className="inline-flex items-center gap-1.5">
            <FileText className="w-3.5 h-3.5 text-amber-400" />
            <strong className="font-mono text-white">{profile?.counts?.documents ?? 0}</strong> docs
          </span>
        </div>
        <div className="flex items-center gap-1 p-1 rounded-[12px] bg-white/[0.05] border border-white/[0.08]">
          <button
            onClick={() => setActiveTab('explain')}
            className={`px-3 py-1 rounded-[9px] text-xs font-medium transition ${
              activeTab === 'explain' ? 'bg-[#22d3ee]/20 text-cyan-200 border border-[#22d3ee]/40' : 'text-slate-400 hover:text-white'
            }`}
          >
            Why This Person Stands Out
          </button>
          <button
            onClick={() => setActiveTab('timeline')}
            className={`px-3 py-1 rounded-[9px] text-xs font-medium transition ${
              activeTab === 'timeline' ? 'bg-[#22d3ee]/20 text-cyan-200 border border-[#22d3ee]/40' : 'text-slate-400 hover:text-white'
            }`}
          >
            Evidence Timeline ({timeline.length})
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {loading ? (
          <div className="space-y-4">
            <GlassSkeleton className="h-28 w-full" />
            <GlassSkeleton className="h-40 w-full" />
            <GlassSkeleton className="h-40 w-full" />
          </div>
        ) : activeTab === 'explain' && explain ? (
          <>
            {/* Radial Rank Gauges */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <RadialRankGauge
                label="Influence (PageRank)"
                rank={explain.ranks.pagerank}
                total={explain.people_in_case}
                color="#ff3b5c"
              />
              <RadialRankGauge
                label="Group Bridging"
                rank={explain.ranks.betweenness}
                total={explain.people_in_case}
                color="#22d3ee"
              />
              <RadialRankGauge
                label="Direct Connections"
                rank={explain.ranks.degree}
                total={explain.people_in_case}
                color="#ffb020"
              />
            </div>

            {/* Why this person stands out */}
            <GlassCard className="p-4 space-y-3" variant={computedTier === 'key_figure' ? 'crimson' : 'default'}>
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-[#22d3ee]" />
                  Why This Person Stands Out
                </h3>
                <GlassBadge tone="slate">
                  Run {explain.run.mode === 'observed_plus_inferred' ? 'Observed + Inferred' : 'Observed Only'} ({explain.run.weights_version})
                </GlassBadge>
              </div>
              <ul className="space-y-2 text-xs text-slate-200">
                {explain.reasons.map((r, i) => (
                  <li key={i} className="flex items-start gap-2.5 leading-relaxed">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#22d3ee] mt-1.5 shrink-0" />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </GlassCard>

            {/* Assigned Vehicles (if any) */}
            {profile?.vehicle_assignments && profile.vehicle_assignments.length > 0 && (
              <GlassCard className="p-4 space-y-2.5" variant="violet">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-violet-300 flex items-center gap-1.5">
                    <Car className="w-3.5 h-3.5" />
                    Vehicle Assignment & Attribution Uncertainty
                  </h3>
                  <GlassBadge tone="violet">Assigned driver assumed</GlassBadge>
                </div>
                {profile.vehicle_assignments.map((va, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs text-slate-300 bg-white/[0.03] px-3 py-2 rounded-[12px]">
                    <span>
                      Vehicle <strong className="font-mono text-white">{va.vehicle_id}</strong> (Car #{va.source_car_id}) • {va.relationship}
                    </span>
                    <span className="font-mono text-[11px] text-violet-300">assigned_driver_assumed</span>
                  </div>
                ))}
              </GlassCard>
            )}

            {/* Strongest Ties */}
            <GlassCard className="p-4 space-y-3">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <Link2 className="w-4 h-4 text-amber-400" />
                Strongest Recorded & Inferred Ties ({explain.top_ties.length})
              </h3>
              {explain.top_ties.length === 0 ? (
                <p className="text-xs text-slate-400">No positive-strength ties in this mode.</p>
              ) : (
                <div className="space-y-2">
                  {explain.top_ties.map((tie) => {
                    const maxS = explain.top_ties[0]?.strength || 1;
                    const barW = Math.max(8, Math.round((tie.strength / maxS) * 100));
                    return (
                      <div
                        key={tie.person_id}
                        className="p-2.5 rounded-[12px] bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.07] transition flex items-center justify-between gap-3"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => onSelectPerson(tie.person_id)}
                              className="text-xs font-semibold text-white hover:text-[#22d3ee] truncate"
                            >
                              {tie.display_name || tie.person_id}
                            </button>
                            <span className="font-mono text-[11px] text-slate-400">{tie.person_id}</span>
                            {tie.inferred && <GlassBadge tone="violet">Inferred</GlassBadge>}
                          </div>
                          <div className="flex items-center gap-2 mt-1.5">
                            <div className="h-1.5 w-28 bg-white/[0.07] rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${tie.inferred ? 'bg-[#a78bfa]' : 'bg-[#22d3ee]'}`}
                                style={{ width: `${barW}%` }}
                              />
                            </div>
                            <span className="font-mono text-[11px] text-slate-400">strength {tie.strength.toFixed(2)}</span>
                            <span className="text-[11px] text-slate-400">• {tie.types.join(', ')}</span>
                          </div>
                        </div>
                        <GlassButton
                          size="sm"
                          variant="ghost"
                          onClick={() => onOpenPairEvidence(personId, tie.person_id)}
                        >
                          Pair Evidence
                          <ExternalLink className="w-3 h-3" />
                        </GlassButton>
                      </div>
                    );
                  })}
                </div>
              )}
            </GlassCard>

            {/* Community Group */}
            {explain.community?.community_id && (
              <GlassCard className="p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Users className="w-4 h-4 text-cyan-400" />
                    Detected Cluster {explain.community.community_id} ({explain.community.size} people)
                  </h3>
                  <span className="text-[11px] text-slate-400">Closely interacting cluster, not a verified group</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {explain.community.members.map((m) => (
                    <button
                      key={m.person_id}
                      onClick={() => onSelectPerson(m.person_id)}
                      className={`px-2.5 py-1 rounded-full text-xs border transition ${
                        m.person_id === personId
                          ? 'bg-[#22d3ee]/20 text-cyan-200 border-[#22d3ee]/50 font-semibold'
                          : 'bg-white/[0.05] text-slate-300 border-white/[0.1] hover:bg-white/[0.12]'
                      }`}
                    >
                      {m.display_name || m.person_id}
                    </button>
                  ))}
                </div>
              </GlassCard>
            )}

            {/* Suggested Links Involving This Person */}
            <GlassCard className="p-4 space-y-3">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-[#ff3b5c]" />
                Suggested Links & Evidence Leads ({explain.suggested_links.length})
              </h3>
              {explain.suggested_links.length === 0 ? (
                <p className="text-xs text-slate-400">No unrecorded link suggestions for this person in this run.</p>
              ) : (
                <div className="space-y-2">
                  {explain.suggested_links.slice(0, 6).map((l, idx) => (
                    <div
                      key={`${l.method}-${l.other_person}-${idx}`}
                      className="p-3 rounded-[12px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-between gap-3"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => l.other_person && onSelectPerson(l.other_person)}
                            className="text-xs font-semibold text-white hover:text-[#22d3ee]"
                          >
                            {l.other_name || l.other_person}
                          </button>
                          <GlassBadge tone={l.basis === 'evidence' ? 'crimson' : 'cyan'}>
                            Rank #{l.rank_in_method} • {methodLabel(l.method)}
                          </GlassBadge>
                        </div>
                        <div className="flex flex-wrap gap-1.5 mt-1.5">
                          {Object.entries(l.factor_breakdown || {})
                            .slice(0, 4)
                            .map(([k, v]) => (
                              <span
                                key={k}
                                className="px-2 py-0.5 rounded bg-white/[0.05] text-[11px] font-mono text-slate-300"
                              >
                                {k}: {Array.isArray(v) ? v.length : String(v)}
                              </span>
                            ))}
                        </div>
                      </div>
                      <GlassButton
                        size="sm"
                        variant="secondary"
                        onClick={() => l.other_person && onOpenPairEvidence(personId, l.other_person)}
                      >
                        Inspect Pair
                      </GlassButton>
                    </div>
                  ))}
                </div>
              )}
            </GlassCard>

            {/* Honesty Footer Note */}
            <div className="p-3.5 rounded-[14px] bg-white/[0.03] border border-white/[0.08] text-xs text-slate-400 leading-relaxed">
              <strong className="text-slate-200">Methodological Note:</strong> {explain.note}
            </div>
          </>
        ) : (
          /* Timeline View */
          <div className="space-y-3">
            {timeline.length === 0 ? (
              <GlassCard className="p-8 text-center text-slate-400 text-sm">
                No timestamped email or vehicle GPS events recorded for this person in this case.
              </GlassCard>
            ) : (
              <div className="relative pl-5 border-l border-white/[0.14] space-y-4">
                {timeline.map((ev, i) => {
                  const isVeh = ev.event_type === 'vehicle_stop';
                  const timeObj = formatIST(ev.event_time);
                  return (
                    <div key={`${ev.event_id}-${i}`} className="relative">
                      <span
                        className={`absolute -left-[25px] top-1.5 w-3 h-3 rounded-full border-2 border-[#05070d] ${
                          isVeh ? 'bg-[#a78bfa]' : 'bg-[#22d3ee]'
                        }`}
                      />
                      <GlassCard className="p-3.5" variant={isVeh ? 'violet' : 'default'}>
                        <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
                          <div className="flex items-center gap-2">
                            {isVeh ? (
                              <GlassBadge tone="violet">
                                <Car className="w-3 h-3" />
                                Vehicle evidence — assigned driver assumed
                              </GlassBadge>
                            ) : (
                              <GlassBadge tone="cyan">
                                <Mail className="w-3 h-3" />
                                Recorded Email
                              </GlassBadge>
                            )}
                            <span className="font-mono text-[11px] text-slate-400">{ev.event_id}</span>
                          </div>
                          <span className="font-mono text-xs text-slate-300" title={timeObj.relative}>
                            <Clock className="w-3 h-3 inline mr-1 text-slate-400" />
                            {timeObj.formatted}
                          </span>
                        </div>
                        {isVeh ? (
                          <div className="text-xs text-slate-200 mt-1">
                            Vehicle <span className="font-mono text-white">{ev.evidence?.vehicle_id}</span> stopped at place{' '}
                            <span className="font-mono text-violet-300">{ev.evidence?.place_id || 'GPS coordinate'}</span> for{' '}
                            <span className="font-mono text-white">{ev.evidence?.duration_min ?? '—'} min</span>.
                          </div>
                        ) : (
                          <div className="text-xs text-slate-200 mt-1">
                            <div className="font-medium text-white">{ev.evidence?.subject || '(No subject)'}</div>
                            <div className="text-slate-400 mt-0.5 font-mono text-[11px]">
                              {ev.evidence?.source_person_id} → {ev.evidence?.target_person_id}
                              {ev.evidence?.is_broadcast ? ' (Broadcast ≥10 recipients)' : ' (Direct)'}
                            </div>
                          </div>
                        )}
                      </GlassCard>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
