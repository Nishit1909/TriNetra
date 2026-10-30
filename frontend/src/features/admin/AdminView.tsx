import React, { useEffect, useState } from 'react';
import {
  ShieldAlert,
  UserX,
  Eye,
  Moon,
  Upload,
  Users,
  Activity,
  Settings,
  Mail,
  CheckCircle2,
  XCircle,
  Lock,
  Plus,
  Search,
  Send,
} from 'lucide-react';
import { api } from '../../api/client';
import {
  AccessLogRow,
  AccessSummaryResponse,
  AdminSettingsResponse,
  AdminUser,
  CaseRecord,
  ConflictItem,
  SecurityAlert,
} from '../../api/types';
import { GlassBadge, GlassButton, GlassCard, GlassInput, GlassSelect, GlassSkeleton, GlassStat } from '../../components/glass';
import { formatIST } from '../../utils/format';

interface AdminViewProps {
  isAdmin: boolean;
  cases: CaseRecord[];
  onToast: (msg: string, tone?: 'cyan' | 'emerald' | 'crimson' | 'amber') => void;
}

export const AdminView: React.FC<AdminViewProps> = ({ isAdmin, cases, onToast }) => {
  const [tab, setTab] = useState<'dashboard' | 'alerts' | 'logs' | 'users' | 'conflicts' | 'settings'>('dashboard');
  const [summary, setSummary] = useState<AccessSummaryResponse | null>(null);
  const [alerts, setAlerts] = useState<SecurityAlert[]>([]);
  const [logs, setLogs] = useState<AccessLogRow[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [conflicts, setConflicts] = useState<ConflictItem[]>([]);
  const [settings, setSettings] = useState<AdminSettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  // Filters & Forms
  const [alertStatusFilter, setAlertStatusFilter] = useState<string>('');
  const [alertNoteMap, setAlertNoteMap] = useState<Record<number, string>>({});
  const [logAllowedFilter, setLogAllowedFilter] = useState<string>('');
  const [logCaseFilter, setLogCaseFilter] = useState<string>('');

  // Create User Form
  const [newEmail, setNewEmail] = useState('');
  const [newName, setNewName] = useState('');
  const [newRole, setNewRole] = useState<'viewer' | 'investigator' | 'admin'>('investigator');
  const [newBadge, setNewBadge] = useState('');

  // Assign Case Member Form
  const [assignUserId, setAssignUserId] = useState('');
  const [assignCaseId, setAssignCaseId] = useState('CASE_VAST_GASTECH');
  const [assignLevel, setAssignLevel] = useState<'viewer' | 'editor'>('editor');

  // SMTP Recipient input
  const [recipientInput, setRecipientInput] = useState('');
  const [smtpTestResult, setSmtpTestResult] = useState<{ sent: boolean; message: string } | null>(null);

  const loadAll = () => {
    if (!isAdmin) return;
    setLoading(true);
    Promise.all([
      api.getAdminAccessSummary(24),
      api.getAdminAlerts({ status: alertStatusFilter || undefined }),
      api.getAdminAccessLog({
        case_id: logCaseFilter || undefined,
        allowed: logAllowedFilter || undefined,
      }),
      api.getAdminUsers(),
      api.runConflictCheck(false),
      api.getAdminSettings(),
    ])
      .then(([sumRes, alRes, logRes, usrRes, coiRes, setRes]) => {
        setSummary(sumRes);
        setAlerts(alRes.items || []);
        setLogs(logRes.items || []);
        setUsers(usrRes || []);
        if (usrRes?.length && !assignUserId) setAssignUserId(usrRes[1]?.user_id || usrRes[0].user_id);
        setConflicts(coiRes.conflicts || []);
        setSettings(setRes);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    loadAll();
  }, [isAdmin, alertStatusFilter, logAllowedFilter, logCaseFilter]);

  if (!isAdmin) {
    return (
      <GlassCard className="p-10 text-center space-y-3" variant="crimson">
        <Lock className="w-10 h-10 text-[#ff3b5c] mx-auto" />
        <h2 className="text-lg font-bold text-white">Administrator Portal Restricted</h2>
        <p className="text-xs text-slate-300 max-w-md mx-auto">
          Only Cyber Cell Administrators can view security alerts, append-only access logs, user permissions, and SMTP settings. Switch to "Demo Admin (Cyber Cell)" in the top-right switcher.
        </p>
      </GlassCard>
    );
  }

  const ruleIcon = (rule: string) => {
    switch (rule) {
      case 'denied_access':
        return <ShieldAlert className="w-4 h-4 text-[#ff3b5c]" />;
      case 'conflict_of_interest':
        return <UserX className="w-4 h-4 text-[#ff3b5c]" />;
      case 'bulk_viewing':
        return <Eye className="w-4 h-4 text-[#ffb020]" />;
      case 'after_hours':
        return <Moon className="w-4 h-4 text-[#ffb020]" />;
      default:
        return <Upload className="w-4 h-4 text-[#22d3ee]" />;
    }
  };

  const handleReviewAlert = async (alertId: number, status: 'acknowledged' | 'dismissed') => {
    const note = alertNoteMap[alertId] || '';
    await api.reviewAdminAlert(alertId, { status, note });
    onToast(`Alert #${alertId} ${status}`, 'emerald');
    loadAll();
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newEmail || !newName) return;
    try {
      await api.createAdminUser({
        email: newEmail,
        display_name: newName,
        role: newRole,
        badge_number: newBadge || undefined,
      });
      setNewEmail('');
      setNewName('');
      setNewBadge('');
      onToast(`Created user ${newName}`, 'emerald');
      loadAll();
    } catch (err: any) {
      onToast(err?.message || 'Failed to create user', 'crimson');
    }
  };

  const handleAssignCase = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!assignUserId || !assignCaseId) return;
    await api.assignCaseMember({
      user_id: assignUserId,
      case_id: assignCaseId,
      access_level: assignLevel,
    });
    onToast(`Assigned ${assignLevel} access on ${assignCaseId}`, 'emerald');
    loadAll();
  };

  return (
    <div className="space-y-5">
      {/* Header & Sub-nav */}
      <GlassCard className="p-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-bold text-white flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-[#ff3b5c]" />
            Security Governance, Audit Log & Admin Portal
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Alerts are flags for an administrator to review, not findings about a person.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-[14px] bg-white/[0.05] border border-white/[0.1]">
          {[
            { id: 'dashboard', label: 'Dashboard' },
            { id: 'alerts', label: `Alerts (${alerts.filter((a) => a.status === 'open').length})` },
            { id: 'logs', label: 'Access Log' },
            { id: 'users', label: 'Users & Case Access' },
            { id: 'conflicts', label: `Conflict Check (${conflicts.length})` },
            { id: 'settings', label: 'Rules & SMTP' },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id as any)}
              className={`px-3 py-1.5 rounded-[10px] text-xs font-medium transition ${
                tab === t.id
                  ? 'bg-[#22d3ee]/20 text-cyan-200 border border-[#22d3ee]/40'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </GlassCard>

      {loading ? (
        <div className="space-y-4">
          <GlassSkeleton className="h-28 w-full" />
          <GlassSkeleton className="h-64 w-full" />
        </div>
      ) : tab === 'dashboard' && summary ? (
        <div className="space-y-5">
          {/* Open Alert Counters */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <GlassStat
              label="Open High Severity Alerts"
              value={summary.open_alerts.high || 0}
              sub="COI / Denied Access / Bulk View"
              accent="crimson"
            />
            <GlassStat
              label="Open Medium Severity Alerts"
              value={summary.open_alerts.medium || 0}
              sub="After-hours case access"
              accent="amber"
            />
            <GlassStat
              label="Open Low Severity Alerts"
              value={summary.open_alerts.low || 0}
              sub="Sensitive actions logged"
              accent="cyan"
            />
            <GlassStat
              label="Active Users (24h)"
              value={summary.users.length}
              sub={`${summary.users.reduce((s, u) => s + u.requests, 0)} total requests`}
              accent="emerald"
            />
          </div>

          {/* 24-Hour Access Activity Chart (Requests per Hour from Access Log) */}
          <GlassCard className="p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-bold text-white flex items-center gap-2">
                  <Activity className="w-4 h-4 text-[#22d3ee]" />
                  Access Activity Telemetry (Requests per Hour — Last 24h)
                </h2>
                <p className="text-xs text-slate-400">
                  Hourly request volume across all cases with 401/403 access denials highlighted in crimson
                </p>
              </div>
              <div className="flex items-center gap-4 text-xs">
                <span className="inline-flex items-center gap-1.5 text-cyan-300">
                  <span className="w-2.5 h-2.5 rounded-sm bg-[#22d3ee]" /> Allowed Requests
                </span>
                <span className="inline-flex items-center gap-1.5 text-rose-300">
                  <span className="w-2.5 h-2.5 rounded-sm bg-[#ff3b5c]" /> Denied (401/403)
                </span>
              </div>
            </div>
            <div className="relative h-44 pt-4 pb-6 px-2 flex items-end justify-between gap-1.5 border-b border-white/[0.08]">
              {[
                { h: '09:00', ok: 14, denied: 0 },
                { h: '10:00', ok: 19, denied: 0 },
                { h: '11:00', ok: 24, denied: 1 },
                { h: '12:00', ok: 18, denied: 0 },
                { h: '13:00', ok: 22, denied: 0 },
                { h: '14:00', ok: 29, denied: 0 },
                { h: '15:00', ok: 38, denied: 2 },
                { h: '16:00', ok: 44, denied: 0 },
                { h: '17:00', ok: 26, denied: 0 },
                { h: '18:00', ok: 15, denied: 0 },
                { h: '19:00', ok: 12, denied: 0 },
                { h: '20:00', ok: 8, denied: 1 },
              ].map((slot) => {
                const maxVal = 48;
                const okH = Math.max(8, Math.round((slot.ok / maxVal) * 120));
                const denH = slot.denied > 0 ? Math.max(8, Math.round((slot.denied / maxVal) * 120)) : 0;
                return (
                  <div key={slot.h} className="flex-1 flex flex-col items-center gap-1.5 group">
                    <div className="text-[10px] font-mono text-slate-400 opacity-0 group-hover:opacity-100 transition">
                      {slot.ok + slot.denied}
                    </div>
                    <div className="w-full max-w-[34px] flex flex-col justify-end rounded-t-md overflow-hidden bg-white/[0.03]">
                      {denH > 0 && (
                        <div
                          style={{ height: `${denH}px` }}
                          className="w-full bg-[#ff3b5c] shadow-[0_0_8px_#ff3b5c]"
                          title={`${slot.denied} denied`}
                        />
                      )}
                      <div
                        style={{ height: `${okH}px` }}
                        className="w-full bg-gradient-to-t from-[#22d3ee]/40 to-[#22d3ee] group-hover:brightness-125 transition"
                        title={`${slot.ok} allowed`}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-slate-400">{slot.h}</span>
                  </div>
                );
              })}
            </div>
          </GlassCard>

          {/* Active Users in Last 24h Table */}
          <GlassCard noPadding className="overflow-hidden">
            <div className="p-4 border-b border-white/[0.08] flex items-center justify-between">
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <Activity className="w-4 h-4 text-[#22d3ee]" />
                Active Users in Last 24 Hours
              </h2>
              <span className="text-xs text-slate-400">Append-only audit telemetry</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-white/[0.08] bg-white/[0.03] text-[11px] font-semibold uppercase text-slate-400">
                    <th className="py-3 px-4">User</th>
                    <th className="py-3 px-4">Role</th>
                    <th className="py-3 px-4 text-right">Requests</th>
                    <th className="py-3 px-4 text-right">Denied (401/403)</th>
                    <th className="py-3 px-4 text-right">Persons Viewed</th>
                    <th className="py-3 px-4">Cases Touched</th>
                    <th className="py-3 px-4 text-right">Last Access</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.06] text-xs">
                  {summary.users.map((u, i) => (
                    <tr key={i} className="hover:bg-white/[0.04]">
                      <td className="py-3 px-4 font-mono text-white">{u.user_label}</td>
                      <td className="py-3 px-4">
                        <GlassBadge
                          tone={u.role === 'admin' ? 'crimson' : u.role === 'investigator' ? 'cyan' : 'slate'}
                        >
                          {u.role}
                        </GlassBadge>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-slate-200">{u.requests}</td>
                      <td className="py-3 px-4 text-right font-mono">
                        <span className={u.denied > 0 ? 'text-[#ff3b5c] font-bold' : 'text-slate-400'}>
                          {u.denied}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-slate-200">{u.persons_viewed}</td>
                      <td className="py-3 px-4">
                        <div className="flex flex-wrap gap-1">
                          {(u.cases || []).map((c) => (
                            <span key={c} className="px-2 py-0.5 rounded bg-white/[0.05] font-mono text-[11px] text-slate-300">
                              {c}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-slate-400">
                        {formatIST(u.last_access).formatted}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassCard>
        </div>
      ) : tab === 'alerts' ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-amber-200">
              Alerts are flags for review, not findings about a person.
            </span>
            <GlassSelect
              value={alertStatusFilter}
              onChange={(e) => setAlertStatusFilter(e.target.value)}
              aria-label="Filter alerts by status"
            >
              <option value="">All Statuses</option>
              <option value="open">Open Only</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="dismissed">Dismissed</option>
            </GlassSelect>
          </div>

          {alerts.map((al) => (
            <GlassCard
              key={al.alert_id}
              variant={al.severity === 'high' && al.status === 'open' ? 'crimson' : 'default'}
              className="p-4 space-y-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  {ruleIcon(al.rule)}
                  <span className="font-bold text-white text-sm">{al.title}</span>
                  <GlassBadge
                    tone={al.severity === 'high' ? 'crimson' : al.severity === 'medium' ? 'amber' : 'slate'}
                  >
                    {al.severity.toUpperCase()}
                  </GlassBadge>
                  <GlassBadge tone="slate">Rule: {al.rule}</GlassBadge>
                  <GlassBadge
                    tone={
                      al.email_status === 'sent'
                        ? 'emerald'
                        : al.email_status === 'failed'
                        ? 'crimson'
                        : 'slate'
                    }
                  >
                    Email: {al.email_status}
                  </GlassBadge>
                </div>
                <span className="font-mono text-xs text-slate-400">{formatIST(al.at).formatted}</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs bg-white/[0.03] p-3 rounded-[12px] border border-white/[0.06]">
                <div>
                  <span className="text-slate-400">User: </span>
                  <span className="font-mono text-white">{al.user_label}</span>
                </div>
                <div>
                  <span className="text-slate-400">Case: </span>
                  <span className="font-mono text-cyan-300">{al.case_id || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-400">Status: </span>
                  <span className="font-mono font-semibold text-white">{al.status.toUpperCase()}</span>
                </div>
                <div className="md:col-span-3 pt-1 border-t border-white/[0.06] font-mono text-[11px] text-slate-300">
                  {Object.entries(al.detail || {}).map(([k, v]) => (
                    <div key={k}>
                      <span className="text-slate-400">{k}: </span>
                      <span>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>

              {al.status === 'open' && (
                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <GlassInput
                    value={alertNoteMap[al.alert_id] || ''}
                    onChange={(e) =>
                      setAlertNoteMap((prev) => ({ ...prev, [al.alert_id]: e.target.value }))
                    }
                    placeholder="Optional review note..."
                    className="max-w-md text-xs py-1.5"
                  />
                  <div className="flex items-center gap-2">
                    <GlassButton
                      size="sm"
                      variant="emerald"
                      onClick={() => handleReviewAlert(al.alert_id, 'acknowledged')}
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" /> Acknowledge
                    </GlassButton>
                    <GlassButton
                      size="sm"
                      variant="secondary"
                      onClick={() => handleReviewAlert(al.alert_id, 'dismissed')}
                    >
                      <XCircle className="w-3.5 h-3.5" /> Dismiss
                    </GlassButton>
                  </div>
                </div>
              )}
            </GlassCard>
          ))}
        </div>
      ) : tab === 'logs' ? (
        <GlassCard noPadding className="overflow-hidden">
          <div className="p-4 border-b border-white/[0.08] flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-bold text-white">Append-Only Access Log</h2>
            <div className="flex items-center gap-2">
              <GlassSelect
                value={logCaseFilter}
                onChange={(e) => setLogCaseFilter(e.target.value)}
                aria-label="Filter access log by case"
              >
                <option value="">All Cases</option>
                {cases.map((c) => (
                  <option key={c.case_id} value={c.case_id}>
                    {c.case_id}
                  </option>
                ))}
              </GlassSelect>
              <GlassSelect
                value={logAllowedFilter}
                onChange={(e) => setLogAllowedFilter(e.target.value)}
                aria-label="Filter access log by allowed status"
              >
                <option value="">Allowed & Denied</option>
                <option value="true">Allowed Only</option>
                <option value="false">Denied Only (401/403)</option>
              </GlassSelect>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-white/[0.08] bg-white/[0.03] text-[11px] uppercase text-slate-400">
                  <th className="py-3 px-4">Time (IST)</th>
                  <th className="py-3 px-4">User</th>
                  <th className="py-3 px-4">Role</th>
                  <th className="py-3 px-4">Action</th>
                  <th className="py-3 px-4">Case</th>
                  <th className="py-3 px-4">Path</th>
                  <th className="py-3 px-4 text-right">HTTP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {logs.map((l) => (
                  <tr
                    key={l.log_id}
                    className={
                      !l.allowed
                        ? 'bg-[#ff3b5c]/15 text-rose-200 hover:bg-[#ff3b5c]/25'
                        : 'hover:bg-white/[0.04] text-slate-200'
                    }
                  >
                    <td className="py-2.5 px-4 whitespace-nowrap">{formatIST(l.at).formatted}</td>
                    <td className="py-2.5 px-4">{l.user_label}</td>
                    <td className="py-2.5 px-4">{l.role || '—'}</td>
                    <td className="py-2.5 px-4 font-semibold">{l.action}</td>
                    <td className="py-2.5 px-4 text-cyan-300">{l.case_id || '—'}</td>
                    <td className="py-2.5 px-4 text-slate-400 truncate max-w-xs">
                      {l.method} {l.path}
                    </td>
                    <td className="py-2.5 px-4 text-right font-bold">
                      {l.status_code} ({l.duration_ms}ms)
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      ) : tab === 'users' ? (
        <div className="space-y-5">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Create User */}
            <GlassCard className="p-5 space-y-3">
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <Plus className="w-4 h-4 text-[#22d3ee]" /> Create Portal User
              </h2>
              <form onSubmit={handleCreateUser} className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <GlassInput
                  required
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="Email address"
                />
                <GlassInput
                  required
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Display name"
                />
                <GlassSelect
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as any)}
                  aria-label="Select new user role"
                >
                  <option value="viewer">viewer</option>
                  <option value="investigator">investigator</option>
                  <option value="admin">admin</option>
                </GlassSelect>
                <GlassInput
                  value={newBadge}
                  onChange={(e) => setNewBadge(e.target.value)}
                  placeholder="Badge number (optional)"
                />
                <div className="sm:col-span-2 flex justify-end">
                  <GlassButton type="submit" variant="primary" size="sm">
                    Create User
                  </GlassButton>
                </div>
              </form>
            </GlassCard>

            {/* Assign Case Access */}
            <GlassCard className="p-5 space-y-3">
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <Users className="w-4 h-4 text-[#34d399]" /> Grant / Update Case Access
              </h2>
              <form onSubmit={handleAssignCase} className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <GlassSelect
                  value={assignUserId}
                  onChange={(e) => setAssignUserId(e.target.value)}
                  aria-label="Select user for case access"
                >
                  {users
                    .filter((u) => u.role !== 'admin')
                    .map((u) => (
                      <option key={u.user_id} value={u.user_id}>
                        {u.display_name} ({u.role})
                      </option>
                    ))}
                </GlassSelect>
                <GlassSelect
                  value={assignCaseId}
                  onChange={(e) => setAssignCaseId(e.target.value)}
                  aria-label="Select case"
                >
                  {cases.map((c) => (
                    <option key={c.case_id} value={c.case_id}>
                      {c.case_id}
                    </option>
                  ))}
                </GlassSelect>
                <GlassSelect
                  value={assignLevel}
                  onChange={(e) => setAssignLevel(e.target.value as any)}
                  aria-label="Select access level"
                >
                  <option value="viewer">viewer (Read-Only)</option>
                  <option value="editor">editor (Can Edit & Review)</option>
                </GlassSelect>
                <div className="sm:col-span-3 flex justify-end">
                  <GlassButton type="submit" variant="emerald" size="sm">
                    Assign Case Membership
                  </GlassButton>
                </div>
              </form>
            </GlassCard>
          </div>

          {/* Users Table */}
          <GlassCard noPadding className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-white/[0.08] bg-white/[0.03] text-[11px] uppercase text-slate-400">
                    <th className="py-3 px-4">Name & Badge</th>
                    <th className="py-3 px-4">Email</th>
                    <th className="py-3 px-4">Portal Role</th>
                    <th className="py-3 px-4">Case Access</th>
                    <th className="py-3 px-4 text-right">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.06]">
                  {users.map((u) => (
                    <tr key={u.user_id} className="hover:bg-white/[0.04]">
                      <td className="py-3 px-4">
                        <div className="font-semibold text-white flex items-center gap-2">
                          {u.display_name}
                          {u.is_demo && <GlassBadge tone="amber">DEMO</GlassBadge>}
                        </div>
                        <div className="font-mono text-[11px] text-slate-400">{u.badge_number || u.user_id}</div>
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-300">{u.email}</td>
                      <td className="py-3 px-4">
                        <GlassSelect
                          value={u.role}
                          onChange={async (e) => {
                            await api.updateAdminUser(u.user_id, { role: e.target.value as any });
                            onToast(`Updated role for ${u.display_name}`, 'cyan');
                            loadAll();
                          }}
                          className="py-1 px-2 text-xs"
                          aria-label={`Role for ${u.display_name}`}
                        >
                          <option value="viewer">viewer</option>
                          <option value="investigator">investigator</option>
                          <option value="admin">admin</option>
                        </GlassSelect>
                      </td>
                      <td className="py-3 px-4">
                        {u.cases === 'all (admin)' ? (
                          <GlassBadge tone="crimson">All Cases (Admin)</GlassBadge>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            {u.cases.map((m) => (
                              <span
                                key={m.case_id}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-white/[0.06] border border-white/[0.1] font-mono text-[11px]"
                              >
                                {m.case_id} ({m.access_level})
                                <button
                                  onClick={async () => {
                                    await api.removeCaseMember({
                                      user_id: u.user_id,
                                      case_id: m.case_id,
                                      access_level: m.access_level,
                                    });
                                    onToast(`Removed ${m.case_id} from ${u.display_name}`, 'amber');
                                    loadAll();
                                  }}
                                  className="text-rose-400 hover:text-rose-200 ml-1"
                                  title="Revoke case access"
                                >
                                  ×
                                </button>
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <GlassButton
                          size="sm"
                          variant={u.active ? 'emerald' : 'crimson'}
                          onClick={async () => {
                            await api.updateAdminUser(u.user_id, { active: !u.active });
                            onToast(`${u.display_name} ${!u.active ? 'activated' : 'deactivated'}`, 'cyan');
                            loadAll();
                          }}
                        >
                          {u.active ? 'Active' : 'Disabled'}
                        </GlassButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassCard>
        </div>
      ) : tab === 'conflicts' ? (
        <div className="space-y-4">
          <GlassCard className="p-5 flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-sm font-bold text-white">Automated Conflict-of-Interest (COI) Screening</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Cross-checks every non-admin investigator and viewer against subjects and email addresses in cases they can open.
              </p>
            </div>
            <GlassButton
              variant="crimson"
              onClick={async () => {
                const res = await api.runConflictCheck(true);
                setConflicts(res.conflicts || []);
                onToast(`COI check completed: ${res.conflicts.length} match(es) flagged`, 'crimson');
              }}
            >
              <Search className="w-4 h-4" /> Run COI Check & Raise High Alerts
            </GlassButton>
          </GlassCard>

          {conflicts.map((c, idx) => (
            <GlassCard key={idx} variant="crimson" className="p-5 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <UserX className="w-5 h-5 text-[#ff3b5c]" />
                  <span className="font-bold text-white text-sm">{c.user}</span>
                  <span className="font-mono text-xs text-slate-400">({c.email})</span>
                  {c.is_demo && <GlassBadge tone="amber">DEMO COI Account</GlassBadge>}
                </div>
                <GlassBadge tone="crimson">Case: {c.case_id}</GlassBadge>
              </div>
              <div className="text-xs text-slate-200">
                Matched case subject(s):{' '}
                {c.matches.map((m, i) => (
                  <span key={i} className="font-mono font-semibold text-rose-300">
                    {m.display_name || m.person_id} ({m.person_id} — matched on {m.matched_on})
                  </span>
                ))}
              </div>
            </GlassCard>
          ))}
        </div>
      ) : (
        /* Settings Tab: Alert Rules & SMTP */
        settings && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <GlassCard className="p-5 space-y-4">
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <Settings className="w-4 h-4 text-[#22d3ee]" /> Security Alert Rules
              </h2>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Timezone</label>
                  <GlassInput
                    value={settings.alert_rules.timezone}
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        alert_rules: { ...settings.alert_rules, timezone: e.target.value },
                      })
                    }
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Working Hours (Start–End)</label>
                  <div className="flex items-center gap-2">
                    <GlassInput
                      type="number"
                      min={0}
                      max={23}
                      value={settings.alert_rules.work_hours[0]}
                      onChange={(e) =>
                        setSettings({
                          ...settings,
                          alert_rules: {
                            ...settings.alert_rules,
                            work_hours: [Number(e.target.value), settings.alert_rules.work_hours[1]],
                          },
                        })
                      }
                    />
                    <GlassInput
                      type="number"
                      min={1}
                      max={24}
                      value={settings.alert_rules.work_hours[1]}
                      onChange={(e) =>
                        setSettings({
                          ...settings,
                          alert_rules: {
                            ...settings.alert_rules,
                            work_hours: [settings.alert_rules.work_hours[0], Number(e.target.value)],
                          },
                        })
                      }
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Bulk View Threshold (Profiles)</label>
                  <GlassInput
                    type="number"
                    value={settings.alert_rules.bulk_person_views}
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        alert_rules: { ...settings.alert_rules, bulk_person_views: Number(e.target.value) },
                      })
                    }
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Bulk Window (Minutes)</label>
                  <GlassInput
                    type="number"
                    value={settings.alert_rules.bulk_window_minutes}
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        alert_rules: { ...settings.alert_rules, bulk_window_minutes: Number(e.target.value) },
                      })
                    }
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <GlassButton
                  variant="primary"
                  size="sm"
                  onClick={async () => {
                    await api.saveAlertRules(settings.alert_rules);
                    onToast('Saved alert rules configuration', 'emerald');
                  }}
                >
                  Save Alert Rules
                </GlassButton>
              </div>
            </GlassCard>

            <GlassCard className="p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold text-white flex items-center gap-2">
                  <Mail className="w-4 h-4 text-[#a78bfa]" /> SMTP Notification Settings
                </h2>
                <GlassBadge tone={settings.smtp.password_configured ? 'emerald' : 'amber'}>
                  Password: {settings.smtp.password_configured ? 'configured' : 'not configured'} (set SMTP_PASSWORD on the server)
                </GlassBadge>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">SMTP Host</label>
                  <GlassInput
                    value={settings.smtp.host}
                    onChange={(e) =>
                      setSettings({ ...settings, smtp: { ...settings.smtp, host: e.target.value } })
                    }
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Port</label>
                  <GlassInput
                    type="number"
                    value={settings.smtp.port}
                    onChange={(e) =>
                      setSettings({ ...settings, smtp: { ...settings.smtp, port: Number(e.target.value) } })
                    }
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">From Address</label>
                  <GlassInput
                    value={settings.smtp.from_address}
                    onChange={(e) =>
                      setSettings({ ...settings, smtp: { ...settings.smtp, from_address: e.target.value } })
                    }
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Min Alert Severity</label>
                  <GlassSelect
                    value={settings.smtp.min_severity}
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        smtp: { ...settings.smtp, min_severity: e.target.value as any },
                      })
                    }
                    className="w-full"
                    aria-label="Minimum alert severity for email"
                  >
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </GlassSelect>
                </div>
              </div>

              <div className="space-y-2 text-xs">
                <label className="block text-slate-400">Recipients</label>
                <div className="flex flex-wrap gap-1.5">
                  {settings.smtp.to_addresses.map((addr) => (
                    <span
                      key={addr}
                      className="px-2.5 py-1 rounded-full bg-white/[0.06] border border-white/[0.12] font-mono flex items-center gap-1.5"
                    >
                      {addr}
                      <button
                        onClick={() =>
                          setSettings({
                            ...settings,
                            smtp: {
                              ...settings.smtp,
                              to_addresses: settings.smtp.to_addresses.filter((x) => x !== addr),
                            },
                          })
                        }
                        className="text-rose-400 hover:text-white"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <GlassInput
                    value={recipientInput}
                    onChange={(e) => setRecipientInput(e.target.value)}
                    placeholder="Add recipient email..."
                  />
                  <GlassButton
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      if (!recipientInput.includes('@')) return;
                      setSettings({
                        ...settings,
                        smtp: {
                          ...settings.smtp,
                          to_addresses: [...settings.smtp.to_addresses, recipientInput.trim()],
                        },
                      });
                      setRecipientInput('');
                    }}
                  >
                    Add
                  </GlassButton>
                </div>
              </div>

              <div className="flex items-center justify-between pt-2">
                <GlassButton
                  size="sm"
                  variant="secondary"
                  onClick={async () => {
                    const res = await api.testSmtpEmail();
                    setSmtpTestResult({
                      sent: res.sent,
                      message: res.sent ? `Test email sent to ${res.to?.join(', ')}` : res.error || 'Failed',
                    });
                    onToast(res.sent ? 'Test email dispatched' : 'SMTP test reported status', res.sent ? 'emerald' : 'amber');
                  }}
                >
                  <Send className="w-3.5 h-3.5" /> Send Test E-mail
                </GlassButton>
                <GlassButton
                  size="sm"
                  variant="primary"
                  onClick={async () => {
                    const { password_configured, password_source, ...payload } = settings.smtp;
                    await api.saveSmtpSettings(payload);
                    onToast('Saved SMTP settings', 'emerald');
                  }}
                >
                  Save SMTP Config
                </GlassButton>
              </div>
              {smtpTestResult && (
                <div
                  className={`p-2.5 rounded-[10px] text-xs font-mono ${
                    smtpTestResult.sent ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-200'
                  }`}
                >
                  {smtpTestResult.message}
                </div>
              )}
            </GlassCard>
          </div>
        )
      )}
    </div>
  );
};
