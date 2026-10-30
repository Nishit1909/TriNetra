import React, { useState } from 'react';
import { Eye, EyeOff, Lock, LogIn, Mail, ShieldCheck } from 'lucide-react';
import { api, ApiError } from '../../api/client';

/** Demo accounts seeded by db/seed_demo_security.py. Shown only so judges and teammates can sign in quickly. */
const DEMO_ACCOUNTS = [
  { role: 'Admin', email: 'demo.admin@trinetra.demo', password: 'Admin@Trace2026', note: 'All cases, admin portal, alerts, access log', tone: 'crimson' },
  { role: 'Investigator', email: 'demo.investigator1@trinetra.demo', password: 'Investigator@2026', note: 'Runs analysis, reviews leads, uploads cases', tone: 'cyan' },
  { role: 'Viewer', email: 'demo.viewer@trinetra.demo', password: 'Viewer@Trace2026', note: 'Read-only on assigned cases', tone: 'slate' },
] as const;

const toneClass = {
  crimson: 'border-[#ff3b5c]/35 bg-[#ff3b5c]/10 text-[#ff8a9d]',
  cyan: 'border-[#22d3ee]/35 bg-[#22d3ee]/10 text-cyan-200',
  slate: 'border-white/15 bg-white/[0.05] text-slate-300',
};

interface Props {
  onSignedIn: () => void;
  notice?: string | null;
}

export const LoginPage: React.FC<Props> = ({ onSignedIn, notice }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e?: React.FormEvent, creds?: { email: string; password: string }) => {
    e?.preventDefault();
    const em = creds?.email ?? email;
    const pw = creds?.password ?? password;
    if (!em || !pw) {
      setError('Enter your email and password.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.login(em.trim(), pw);
      setPassword('');
      onSignedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sign-in failed. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#05070d] text-slate-100 relative overflow-hidden flex items-center justify-center p-6">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-40 -left-32 w-[520px] h-[520px] rounded-full bg-indigo-600/20 blur-[120px]" />
        <div className="absolute bottom-[-180px] right-[-120px] w-[560px] h-[560px] rounded-full bg-cyan-500/15 blur-[130px]" />
        <div className="absolute top-1/3 right-1/4 w-[260px] h-[260px] rounded-full bg-rose-600/10 blur-[110px]" />
      </div>

      <div className="relative z-10 w-full max-w-[980px] grid md:grid-cols-[1.05fr_1fr] gap-6 items-stretch">
        {/* Brand side */}
        <div className="hidden md:flex flex-col justify-between rounded-[24px] border border-white/[0.1] bg-white/[0.03] backdrop-blur-xl p-8">
          <div>
            <img src="/trinetra-logo.jpg" alt="TriNetra: see the hidden network" className="w-full max-w-[340px] rounded-[18px] shadow-[0_0_40px_rgba(239,68,68,0.18)]" />
            <h1 className="text-3xl font-semibold leading-tight mt-10">
              Follow the evidence.
              <br />
              <span className="text-slate-400">Not the noise.</span>
            </h1>
            <p className="text-sm text-slate-400 mt-4 max-w-sm">
              Case-scoped network analysis for investigators: who matters, how they connect, and the records behind every lead.
            </p>
          </div>
          <ul className="space-y-3 text-sm text-slate-300">
            {[
              'Every request is logged and attributed to a signed-in officer',
              'Role-based access: viewers read, investigators act, admins govern',
              'Network position is shown as a lead, never as proof of guilt',
            ].map((t) => (
              <li key={t} className="flex items-start gap-2.5">
                <ShieldCheck className="w-4 h-4 mt-0.5 text-emerald-300 flex-none" />
                {t}
              </li>
            ))}
          </ul>
        </div>

        {/* Form side */}
        <div className="rounded-[24px] border border-white/[0.14] bg-[#0a1020]/80 backdrop-blur-2xl p-8 shadow-[0_30px_80px_rgba(0,0,0,0.45)]">
          <h2 className="text-xl font-semibold">Sign in</h2>
          <p className="text-sm text-slate-400 mt-1">Use your investigation workspace account.</p>

          {notice && (
            <div className="mt-5 rounded-[12px] border border-amber-400/30 bg-amber-400/10 px-3.5 py-2.5 text-xs text-amber-200">{notice}</div>
          )}

          <form className="mt-6 space-y-4" onSubmit={submit} noValidate>
            <label className="block">
              <span className="text-xs text-slate-400">Email</span>
              <div className="mt-1.5 flex items-center gap-2.5 rounded-[12px] border border-white/[0.14] bg-white/[0.04] px-3.5 focus-within:border-cyan-400/60 focus-within:shadow-[0_0_0_3px_rgba(34,211,238,0.12)]">
                <Mail className="w-4 h-4 text-slate-500" />
                <input
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-transparent py-2.5 text-sm outline-none placeholder:text-slate-600"
                  placeholder="name@agency.gov.in"
                  autoFocus
                />
              </div>
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">Password</span>
              <div className="mt-1.5 flex items-center gap-2.5 rounded-[12px] border border-white/[0.14] bg-white/[0.04] px-3.5 focus-within:border-cyan-400/60 focus-within:shadow-[0_0_0_3px_rgba(34,211,238,0.12)]">
                <Lock className="w-4 h-4 text-slate-500" />
                <input
                  type={show ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-transparent py-2.5 text-sm outline-none placeholder:text-slate-600"
                  placeholder="••••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShow((v) => !v)}
                  aria-label={show ? 'Hide password' : 'Show password'}
                  className="text-slate-500 hover:text-slate-200"
                >
                  {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </label>

            {error && (
              <div role="alert" className="rounded-[12px] border border-[#ff3b5c]/35 bg-[#ff3b5c]/10 px-3.5 py-2.5 text-xs text-[#ff9aab]">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full flex items-center justify-center gap-2 rounded-[12px] bg-gradient-to-r from-cyan-500 to-indigo-500 py-2.5 text-sm font-semibold text-white shadow-[0_10px_30px_rgba(34,211,238,0.25)] hover:brightness-110 disabled:opacity-60"
            >
              <LogIn className="w-4 h-4" />
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <div className="mt-7">
            <div className="flex items-center gap-3 text-[11px] uppercase tracking-[0.18em] text-slate-500">
              <span className="h-px flex-1 bg-white/10" />
              Demo accounts
              <span className="h-px flex-1 bg-white/10" />
            </div>
            <div className="mt-3 space-y-2">
              {DEMO_ACCOUNTS.map((a) => (
                <button
                  key={a.email}
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setEmail(a.email);
                    setPassword(a.password);
                    submit(undefined, { email: a.email, password: a.password });
                  }}
                  className="w-full flex items-center justify-between gap-3 rounded-[12px] border border-white/[0.08] bg-white/[0.03] px-3.5 py-2.5 text-left hover:bg-white/[0.07] disabled:opacity-60"
                >
                  <div className="min-w-0">
                    <div className="text-sm text-white">{a.email}</div>
                    <div className="text-[11px] text-slate-500 truncate">{a.note}</div>
                  </div>
                  <span className={`flex-none text-[11px] px-2 py-0.5 rounded-full border ${toneClass[a.tone]}`}>{a.role}</span>
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-500 mt-3">Demo passwords: Admin@Trace2026 · Investigator@2026 · Viewer@Trace2026</p>
          </div>
        </div>
      </div>
    </div>
  );
};
