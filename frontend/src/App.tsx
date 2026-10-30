import React, { useEffect, useRef, useState } from 'react';
import {
  LayoutDashboard,
  Share2,
  Users,
  Sparkles,
  GitCompare,
  Upload,
  ShieldAlert,
  Play,
  Command,
  ChevronLeft,
  ChevronRight,
  UserCheck,
  Search,
  X,
} from 'lucide-react';
import { api, ApiError, getDemoUserId, setDemoUserId } from './api/client';
import { LoginPage } from './features/auth/LoginPage';
import { DEMO_USERS } from './api/demoUsers';
import { AnalysisMode, AuthMeResponse, CaseRecord, PersonRecord } from './api/types';
import { GlassBadge, GlassButton, GlassCard, GlassInput, GlassSelect } from './components/glass';
import { OverviewView } from './features/overview/OverviewView';
import { NetworkView } from './features/network/NetworkView';
import { PeopleView } from './features/people/PeopleView';
import { PersonDrawer } from './features/people/PersonDrawer';
import { LeadsView } from './features/leads/LeadsView';
import { PairEvidenceModal } from './features/leads/PairEvidenceModal';
import { CompareView } from './features/compare/CompareView';
import { UploadView } from './features/upload/UploadView';
import { AdminView } from './features/admin/AdminView';

type ScreenId = 'overview' | 'network' | 'people' | 'leads' | 'compare' | 'upload' | 'admin';

interface ToastItem {
  id: number;
  message: string;
  tone: 'cyan' | 'emerald' | 'crimson' | 'amber';
}

export default function App() {
  const [screen, setScreen] = useState<ScreenId>('network');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const [authMe, setAuthMe] = useState<AuthMeResponse | null>(null);
  const [allCases, setAllCases] = useState<CaseRecord[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string>('CASE_VAST_GASTECH');
  const [mode, setMode] = useState<AnalysisMode>('observed_plus_inferred');
  const [runningAnalysis, setRunningAnalysis] = useState(false);

  const [selectedPersonId, setSelectedPersonId] = useState<string | null>(null);
  const [globalPairModal, setGlobalPairModal] = useState<{ a: string; b: string; link?: any } | null>(null);
  const [personsMap, setPersonsMap] = useState<Map<string, PersonRecord>>(new Map());

  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const [cmdQuery, setCmdQuery] = useState('');
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [sessionChecked, setSessionChecked] = useState(false);
  const hadSession = useRef(false);
  const [loginNotice, setLoginNotice] = useState<string | null>(null);
  const [analysisVersion, setAnalysisVersion] = useState(0);

  const addToast = (message: string, tone: ToastItem['tone'] = 'cyan') => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev.slice(-3), { id, message, tone }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  };

  const loadSession = async () => {
    try {
      const me = await api.getMe();          // establishes the session first; unauthenticated users stop here
      const casesRes = await api.getCases();
      setAuthMe(me);
      setAllCases(casesRes);
      setSessionError(null);
      hadSession.current = true;
      if (me.cases.length > 0 && !me.cases.some((c) => c.case_id === activeCaseId)) {
        setActiveCaseId(me.cases[0].case_id);
      }
      if (screen === 'admin' && !me.is_admin) {
        setScreen('network');
      }
    } catch (err: any) {
      setAuthMe(null);
      setAllCases([]);
      if (err instanceof ApiError && err.status === 401) {
        setNeedLogin(true);
        setSessionError(null);
      } else {
        setSessionError(err?.message || 'The backend could not be reached.');
      }
    } finally {
      setSessionChecked(true);
    }
  };

  useEffect(() => {
    const onUnauthorized = () => {
      // Only call it an ended session if someone was actually signed in; a first visit just shows the form.
      if (hadSession.current) setLoginNotice('Your session has ended. Please sign in again.');
      hadSession.current = false;
      setNeedLogin(true);
    };
    window.addEventListener('trace:unauthorized', onUnauthorized);
    return () => window.removeEventListener('trace:unauthorized', onUnauthorized);
  }, []);

  const handleSignedIn = async () => {
    setNeedLogin(false);
    setLoginNotice(null);
    setSelectedPersonId(null);
    await loadSession();
  };

  const handleSignOut = async () => {
    try {
      await api.logout();
    } catch {
      // Already signed out or backend down: show the sign-in page anyway.
    }
    hadSession.current = false;
    setShowUserMenu(false);
    setAuthMe(null);
    setAllCases([]);
    setSelectedPersonId(null);
    setLoginNotice('You have been signed out.');
    setNeedLogin(true);
  };

  useEffect(() => {
    loadSession();
  }, []);

  useEffect(() => {
    if (!activeCaseId || !authMe) return;
    api
      .getPersons(activeCaseId, { limit: 100 })
      .then((res) => {
        const m = new Map<string, PersonRecord>();
        (res.items || []).forEach((p) => m.set(p.person_id, p));
        setPersonsMap(m);
      })
      .catch(() => null);
  }, [activeCaseId, authMe]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setShowCommandPalette((v) => !v);
      } else if (e.key === 'Escape') {
        setShowCommandPalette(false);
        setShowUserMenu(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const handleSwitchDemoUser = async (userId: string) => {
    setDemoUserId(userId);
    setShowUserMenu(false);
    setSelectedPersonId(null);
    await loadSession();
    const u = DEMO_USERS.find((x) => x.user_id === userId);
    addToast(`Switched demo view to ${u?.display_name || userId} (${u?.role || 'admin'})`, 'cyan');
  };

  const handleRunAnalysis = async () => {
    setRunningAnalysis(true);
    try {
      const res = await api.runAnalysis(activeCaseId, mode);
      setAnalysisVersion((v) => v + 1);
      if (res.run.status === 'completed') {
        addToast(`Analysis completed (${res.run.mode} • ${res.predicted_links.length} lead suggestions)`, 'emerald');
      } else {
        addToast(`Analysis ${res.run.status}: ${res.run.error || 'see run details'}`, res.run.status === 'partial' ? 'amber' : 'crimson');
      }
    } catch (err: any) {
      addToast(err?.message || 'Failed to run analysis', 'crimson');
    } finally {
      setRunningAnalysis(false);
    }
  };

  const currentCaseAccess = !authMe
    ? '…'
    : authMe.cases.find((c) => c.case_id === activeCaseId)?.access_level || (authMe.is_admin ? 'admin' : 'none');
  const canEditCurrentCase =
    Boolean(authMe?.is_admin) || (Boolean(authMe?.can_edit) && currentCaseAccess === 'editor');

  const navItems: { id: ScreenId; label: string; icon: React.ReactNode; hidden?: boolean }[] = [
    { id: 'overview', label: 'Overview', icon: <LayoutDashboard className="w-4 h-4" /> },
    { id: 'network', label: 'Network Graph', icon: <Share2 className="w-4 h-4" /> },
    { id: 'people', label: 'People', icon: <Users className="w-4 h-4" /> },
    { id: 'leads', label: 'Leads & Predictions', icon: <Sparkles className="w-4 h-4" /> },
    { id: 'compare', label: 'Compare Runs', icon: <GitCompare className="w-4 h-4" /> },
    { id: 'upload', label: 'Upload Case', icon: <Upload className="w-4 h-4" />, hidden: !authMe || authMe.role === 'viewer' },
    { id: 'admin', label: 'Admin Portal', icon: <ShieldAlert className="w-4 h-4" />, hidden: !authMe?.is_admin },
  ];

  const activeDemoObj = DEMO_USERS.find((u) => u.user_id === getDemoUserId());
  const identityName = authMe?.login_required
    ? authMe.display_name || authMe.label
    : activeDemoObj?.display_name || (authMe ? (authMe.local ? 'Local developer' : authMe.display_name || authMe.label) : 'Not connected');

  if (needLogin) {
    return <LoginPage onSignedIn={handleSignedIn} notice={loginNotice} />;
  }
  if (!sessionChecked) {
    return (
      <div className="min-h-screen bg-[#05070d] grid place-items-center text-sm text-slate-400" role="status">
        Connecting to the investigation workspace…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#05070d] text-slate-100 flex relative overflow-hidden">
      {/* Drifting Liquid Glass Ambient Background Blobs */}
      {!reducedMotion && (
        <div className="pointer-events-none fixed inset-0 overflow-hidden z-0">
          <div className="absolute -top-32 -left-32 w-[520px] h-[520px] rounded-full bg-indigo-600/12 blur-[130px]" />
          <div className="absolute top-1/3 right-[-120px] w-[460px] h-[460px] rounded-full bg-cyan-500/10 blur-[130px]" />
          <div className="absolute bottom-[-140px] left-1/3 w-[480px] h-[480px] rounded-full bg-rose-600/10 blur-[140px]" />
        </div>
      )}

      {/* Left Glass Sidebar */}
      <aside
        className={`relative z-30 flex flex-col justify-between border-r border-white/[0.12] bg-white/[0.04] backdrop-blur-2xl transition-all duration-200 ${
          sidebarCollapsed ? 'w-20' : 'w-64'
        }`}
      >
        <div className="p-4 space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5 overflow-hidden">
              <div className="w-9 h-9 rounded-[12px] bg-gradient-to-br from-[#22d3ee] to-indigo-600 flex items-center justify-center shadow-glow-cyan shrink-0">
                <Share2 className="w-5 h-5 text-slate-950 stroke-[2.5]" />
              </div>
              {!sidebarCollapsed && (
                <div className="min-w-0">
                  <div className="font-bold text-sm text-white tracking-tight truncate">SIH26189</div>
                  <div className="text-[11px] font-mono text-cyan-300 truncate">Network Intelligence</div>
                </div>
              )}
            </div>
            <button
              onClick={() => setSidebarCollapsed((v) => !v)}
              aria-label="Toggle sidebar"
              className="p-1.5 rounded-[10px] bg-white/[0.05] hover:bg-white/[0.12] text-slate-400 hover:text-white"
            >
              {sidebarCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>
          </div>

          <nav className="space-y-1.5">
            {navItems
              .filter((item) => !item.hidden)
              .map((item) => {
                const active = screen === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => setScreen(item.id)}
                    className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-[14px] text-xs font-medium transition-all ${
                      active
                        ? 'bg-gradient-to-r from-[#22d3ee]/20 to-indigo-500/15 text-white border border-[#22d3ee]/45 shadow-glow-cyan'
                        : 'text-slate-400 hover:text-white hover:bg-white/[0.06] border border-transparent'
                    }`}
                    title={sidebarCollapsed ? item.label : undefined}
                  >
                    <span className={active ? 'text-[#22d3ee]' : ''}>{item.icon}</span>
                    {!sidebarCollapsed && <span>{item.label}</span>}
                  </button>
                );
              })}
          </nav>
        </div>

        {/* Sidebar Footer */}
        <div className="p-4 border-t border-white/[0.08] space-y-2">
          <button
            onClick={() => setShowCommandPalette(true)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-[12px] bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.1] text-xs text-slate-300"
          >
            <span className="flex items-center gap-2">
              <Command className="w-3.5 h-3.5 text-[#22d3ee]" />
              {!sidebarCollapsed && <span>Quick Jump</span>}
            </span>
            {!sidebarCollapsed && <kbd className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white/10">⌘K</kbd>}
          </button>
          {!sidebarCollapsed && (
            <label className="flex items-center justify-between px-2 py-1 text-[11px] text-slate-400 cursor-pointer">
              <span>Reduced motion</span>
              <input
                type="checkbox"
                checked={reducedMotion}
                onChange={(e) => setReducedMotion(e.target.checked)}
                className="rounded border-white/20 bg-white/10 text-[#22d3ee]"
              />
            </label>
          )}
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 relative z-10">
        {/* Top Glass Bar */}
        <header className="sticky top-0 z-30 px-6 py-3.5 border-b border-white/[0.12] bg-[#060913]/80 backdrop-blur-2xl flex flex-wrap items-center justify-between gap-4">
          {/* Left: Case Switcher + Role Badge */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-400">Case:</span>
              <GlassSelect
                value={activeCaseId}
                onChange={(e) => {
                  setActiveCaseId(e.target.value);
                  setSelectedPersonId(null);
                }}
                aria-label="Select investigation case"
                className="font-semibold"
              >
                {(authMe?.cases || []).map((c) => (
                  <option key={c.case_id} value={c.case_id}>
                    {c.name} ({c.case_id})
                  </option>
                ))}
              </GlassSelect>
            </div>
            <GlassBadge
              tone={
                currentCaseAccess === 'admin'
                  ? 'crimson'
                  : currentCaseAccess === 'editor'
                  ? 'emerald'
                  : 'slate'
              }
            >
              Case Access: {currentCaseAccess}
            </GlassBadge>

          </div>

          {/* Right: Analysis Mode Toggle + Run Analysis Button + Demo User Chip */}
          <div className="flex flex-wrap items-center gap-3">
            {/* Analysis Mode Toggle */}
            <div className="flex items-center gap-1 p-1 rounded-[14px] bg-white/[0.05] border border-white/[0.12]">
              <button
                onClick={() => setMode('observed_only')}
                className={`px-3 py-1.5 rounded-[10px] text-xs font-medium transition ${
                  mode === 'observed_only'
                    ? 'bg-white/15 text-white border border-white/25'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Observed only
              </button>
              <button
                onClick={() => setMode('observed_plus_inferred')}
                className={`px-3 py-1.5 rounded-[10px] text-xs font-medium transition ${
                  mode === 'observed_plus_inferred'
                    ? 'bg-[#a78bfa]/25 text-violet-200 border border-[#a78bfa]/50'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Observed + inferred
              </button>
            </div>

            {/* Run Analysis Button (hidden for viewers) */}
            {authMe?.role !== 'viewer' && canEditCurrentCase && (
              <GlassButton
                variant="primary"
                size="md"
                disabled={runningAnalysis}
                onClick={handleRunAnalysis}
              >
                <Play className="w-3.5 h-3.5" />
                {runningAnalysis ? 'Running...' : 'Run analysis'}
              </GlassButton>
            )}

            {/* Demo Role Switcher User Chip */}
            <div className="relative">
              <button
                onClick={() => setShowUserMenu((v) => !v)}
                className="flex items-center gap-2.5 px-3.5 py-1.5 rounded-[14px] bg-white/[0.07] hover:bg-white/[0.12] border border-white/[0.15] text-xs transition"
              >
                <UserCheck className="w-4 h-4 text-[#22d3ee]" />
                <div className="text-left">
                  <div className="font-semibold text-white flex items-center gap-1.5">
                    <span>{identityName}</span>
                    {authMe?.is_demo && (
                      <span className="px-1.5 py-0.2 rounded bg-amber-500/25 text-amber-300 font-mono text-[10px] border border-amber-400/40">
                        DEMO
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] uppercase tracking-wider text-cyan-300 font-mono">
                    Role: {authMe?.role || '—'}
                  </div>
                </div>
              </button>

              {showUserMenu && authMe?.login_required && (
                <div className="absolute right-0 mt-2 w-72 rounded-[18px] bg-[#080d1a]/95 backdrop-blur-2xl border border-white/[0.16] shadow-glass p-4 space-y-3 z-50">
                  <div>
                    <div className="text-sm font-semibold text-white">{authMe.display_name || authMe.label}</div>
                    <div className="text-xs text-slate-400">{authMe.label}</div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <GlassBadge tone={authMe.role === 'admin' ? 'crimson' : authMe.role === 'investigator' ? 'cyan' : 'slate'}>{authMe.role}</GlassBadge>
                    {authMe.is_demo && <GlassBadge tone="amber">demo account</GlassBadge>}
                    <GlassBadge>{authMe.cases.length} case{authMe.cases.length === 1 ? '' : 's'}</GlassBadge>
                  </div>
                  <button
                    onClick={handleSignOut}
                    className="w-full rounded-[12px] border border-white/15 bg-white/[0.06] hover:bg-white/[0.12] py-2 text-sm text-white"
                  >
                    Sign out
                  </button>
                </div>
              )}
              {showUserMenu && !authMe?.login_required && (
                <div className="absolute right-0 mt-2 w-80 rounded-[18px] bg-[#080d1a]/95 backdrop-blur-2xl border border-white/[0.16] shadow-glass p-3 space-y-2 z-50">
                  <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Demo Role Switcher (X-Demo-User Header)
                  </div>
                  {DEMO_USERS.map((u) => {
                    const selected = u.user_id === getDemoUserId();
                    return (
                      <button
                        key={u.user_id}
                        onClick={() => handleSwitchDemoUser(u.user_id)}
                        className={`w-full text-left p-2.5 rounded-[12px] border transition ${
                          selected
                            ? 'bg-[#22d3ee]/15 border-[#22d3ee]/50'
                            : 'bg-white/[0.03] border-white/[0.06] hover:bg-white/[0.08]'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-white">{u.display_name}</span>
                          <GlassBadge
                            tone={
                              u.role === 'admin'
                                ? 'crimson'
                                : u.role === 'investigator'
                                ? 'cyan'
                                : 'slate'
                            }
                          >
                            {u.role}
                          </GlassBadge>
                        </div>
                        <div className="text-[11px] text-slate-400 mt-1">{u.description}</div>
                        <div className="font-mono text-[10px] text-slate-500 mt-0.5">{u.user_id}</div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Active Screen Content */}
        <main className="flex-1 p-6 max-w-[1600px] w-full mx-auto">
          {sessionError && (
            <div role="alert" className="mb-6 rounded-[20px] border border-[#ff3b5c]/40 bg-[#ff3b5c]/10 p-6 flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-[#ff8a9d]">Backend unavailable</div>
                <p className="text-sm text-slate-300 mt-1">
                  {sessionError} No case data is shown until the connection is restored. Check that the API is running, then retry.
                </p>
              </div>
              <button
                onClick={() => loadSession()}
                className="px-4 py-2 rounded-[12px] border border-white/20 bg-white/10 hover:bg-white/15 text-sm text-white"
              >
                Retry connection
              </button>
            </div>
          )}
          {!sessionError && screen === 'overview' && (
            <OverviewView
              caseId={activeCaseId}
              mode={mode}
              canEditCase={canEditCurrentCase}
              onSelectPerson={(pid) => setSelectedPersonId(pid)}
              onOpenPairEvidence={(a, b, link) => setGlobalPairModal({ a, b, link })}
              onNavigate={(s) => setScreen(s)}
              onToast={addToast}
            />
          )}
          {!sessionError && screen === 'network' && (
            <NetworkView
              caseId={activeCaseId}
              mode={mode}
              selectedPersonId={selectedPersonId}
              onSelectPerson={(pid) => setSelectedPersonId(pid)}
              onOpenPairEvidence={(a, b) => setGlobalPairModal({ a, b })}
              onToast={addToast}
              reducedMotion={reducedMotion}
              analysisVersion={analysisVersion}
            />
          )}
          {!sessionError && screen === 'people' && (
            <PeopleView
              caseId={activeCaseId}
              mode={mode}
              onSelectPerson={(pid) => setSelectedPersonId(pid)}
              onToast={addToast}
            />
          )}
          {!sessionError && screen === 'leads' && (
            <LeadsView
              caseId={activeCaseId}
              mode={mode}
              canEditCase={canEditCurrentCase}
              onSelectPerson={(pid) => setSelectedPersonId(pid)}
              onToast={addToast}
            />
          )}
          {!sessionError && screen === 'compare' && (
            <CompareView
              caseId={activeCaseId}
              onSelectPerson={(pid) => setSelectedPersonId(pid)}
            />
          )}
          {!sessionError && screen === 'upload' && (
            <UploadView
              canUpload={authMe?.role !== 'viewer'}
              onCaseCreated={async (newId) => {
                await loadSession();
                setActiveCaseId(newId);
                setScreen('network');
              }}
              onToast={addToast}
            />
          )}
          {!sessionError && screen === 'admin' && (
            <AdminView
              isAdmin={Boolean(authMe?.is_admin)}
              cases={allCases}
              onToast={addToast}
            />
          )}
        </main>
      </div>

      {/* Right-Side Person Drawer */}
      <PersonDrawer
        caseId={activeCaseId}
        personId={selectedPersonId}
        mode={mode}
        onClose={() => setSelectedPersonId(null)}
        onSelectPerson={(pid) => setSelectedPersonId(pid)}
        onOpenPairEvidence={(a, b) => setGlobalPairModal({ a, b })}
        onToast={addToast}
      />

      {/* Global Pair Evidence Modal (triggered from Network Graph or Person Drawer) */}
      <PairEvidenceModal
        caseId={activeCaseId}
        runId={null}
        pair={globalPairModal}
        personsMap={personsMap}
        canEditCase={canEditCurrentCase}
        onClose={() => setGlobalPairModal(null)}
        onSelectPerson={(pid) => setSelectedPersonId(pid)}
        onReviewUpdated={() => {}}
        onToast={addToast}
      />

      {/* Command Palette (Ctrl/Cmd + K) */}
      {showCommandPalette && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 p-4 bg-black/70 backdrop-blur-md">
          <GlassCard className="w-full max-w-xl p-4 space-y-3 bg-[#080d1a]/95">
            <div className="flex items-center gap-2 border-b border-white/[0.1] pb-2">
              <Search className="w-4 h-4 text-[#22d3ee]" />
              <input
                autoFocus
                value={cmdQuery}
                onChange={(e) => setCmdQuery(e.target.value)}
                placeholder="Jump to person, case, or screen..."
                className="w-full bg-transparent text-sm text-white focus:outline-none"
              />
              <button onClick={() => setShowCommandPalette(false)} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="max-h-72 overflow-y-auto space-y-2 text-xs">
              <div className="text-[10px] uppercase tracking-wider text-slate-400 px-2">Screens</div>
              {navItems
                .filter((n) => !n.hidden && n.label.toLowerCase().includes(cmdQuery.toLowerCase()))
                .map((n) => (
                  <button
                    key={n.id}
                    onClick={() => {
                      setScreen(n.id);
                      setShowCommandPalette(false);
                    }}
                    className="w-full text-left px-3 py-2 rounded-[10px] hover:bg-white/[0.08] flex items-center justify-between text-slate-200"
                  >
                    <span>{n.label}</span>
                    <span className="text-slate-500 font-mono">Screen</span>
                  </button>
                ))}
              <div className="text-[10px] uppercase tracking-wider text-slate-400 px-2 pt-2">People in {activeCaseId}</div>
              {[...personsMap.values()]
                .filter(
                  (p) =>
                    p.display_name.toLowerCase().includes(cmdQuery.toLowerCase()) ||
                    p.person_id.toLowerCase().includes(cmdQuery.toLowerCase())
                )
                .slice(0, 8)
                .map((p) => (
                  <button
                    key={p.person_id}
                    onClick={() => {
                      setSelectedPersonId(p.person_id);
                      setShowCommandPalette(false);
                    }}
                    className="w-full text-left px-3 py-2 rounded-[10px] hover:bg-white/[0.08] flex items-center justify-between text-slate-200"
                  >
                    <span>{p.display_name}</span>
                    <span className="font-mono text-cyan-300">{p.person_id}</span>
                  </button>
                ))}
            </div>
          </GlassCard>
        </div>
      )}

      {/* Bottom-Right Glass Toasts */}
      <div className="fixed bottom-4 right-4 z-50 space-y-2 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`px-4 py-2.5 rounded-[14px] backdrop-blur-2xl border shadow-glass text-xs font-medium pointer-events-auto animate-in slide-in-from-bottom-2 ${
              t.tone === 'emerald'
                ? 'bg-emerald-500/20 border-emerald-400/40 text-emerald-100'
                : t.tone === 'crimson'
                ? 'bg-rose-500/20 border-rose-400/40 text-rose-100'
                : t.tone === 'amber'
                ? 'bg-amber-500/20 border-amber-400/40 text-amber-100'
                : 'bg-[#0c1428]/90 border-[#22d3ee]/40 text-cyan-100'
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </div>
  );
}
