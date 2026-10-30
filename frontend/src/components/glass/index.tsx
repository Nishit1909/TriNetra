import React, { useRef, useState } from 'react';

export interface GlassPanelProps extends React.HTMLAttributes<HTMLDivElement> {
  interactive?: boolean;
  noPadding?: boolean;
  variant?: 'default' | 'crimson' | 'amber' | 'cyan' | 'violet' | 'emerald';
}

const variantBorder: Record<NonNullable<GlassPanelProps['variant']>, string> = {
  default: 'border-white/[0.12]',
  crimson: 'border-[#ff3b5c]/40 shadow-[0_0_24px_rgba(255,59,92,0.16)]',
  amber: 'border-[#ffb020]/40 shadow-[0_0_20px_rgba(255,176,32,0.14)]',
  cyan: 'border-[#22d3ee]/40 shadow-[0_0_20px_rgba(34,211,238,0.15)]',
  violet: 'border-[#a78bfa]/40 shadow-[0_0_20px_rgba(167,139,250,0.15)]',
  emerald: 'border-[#34d399]/40 shadow-[0_0_20px_rgba(52,211,153,0.15)]',
};

export const GlassCard: React.FC<GlassPanelProps> = ({
  children,
  className = '',
  interactive = false,
  noPadding = false,
  variant = 'default',
  ...props
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const [spot, setSpot] = useState<{ x: number; y: number; show: boolean }>({ x: 0, y: 0, show: false });

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!interactive || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    setSpot({ x: e.clientX - rect.left, y: e.clientY - rect.top, show: true });
  };

  return (
    <div
      ref={ref}
      onMouseMove={handleMouseMove}
      onMouseLeave={() => setSpot((s) => ({ ...s, show: false }))}
      className={`relative rounded-[20px] bg-white/[0.06] backdrop-blur-2xl border ${variantBorder[variant]} shadow-glass transition-all duration-200 ${
        interactive ? 'hover:-translate-y-0.5 hover:border-white/25 cursor-pointer' : ''
      } ${noPadding ? '' : 'p-5'} ${className}`}
      style={{
        boxShadow: '0 20px 50px rgba(0, 0, 0, 0.52), inset 0 1px 0 rgba(255, 255, 255, 0.15)',
      }}
      {...props}
    >
      {interactive && spot.show && (
        <div
          className="pointer-events-none absolute inset-0 rounded-[20px] opacity-100 transition-opacity duration-300"
          style={{
            background: `radial-gradient(360px circle at ${spot.x}px ${spot.y}px, rgba(255,255,255,0.08), transparent 65%)`,
          }}
        />
      )}
      <div className="relative z-10">{children}</div>
    </div>
  );
};

export const GlassPanel = GlassCard;

export interface GlassButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'crimson' | 'emerald' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
}

export const GlassButton: React.FC<GlassButtonProps> = ({
  children,
  variant = 'secondary',
  size = 'md',
  className = '',
  disabled,
  ...props
}) => {
  const styles = {
    primary:
      'bg-gradient-to-r from-[#22d3ee]/25 via-cyan-500/20 to-indigo-500/25 text-cyan-100 border-[#22d3ee]/45 hover:border-[#22d3ee] hover:shadow-glow-cyan',
    secondary:
      'bg-white/[0.07] text-slate-100 border-white/[0.14] hover:bg-white/[0.12] hover:border-white/25',
    crimson:
      'bg-[#ff3b5c]/20 text-[#ff3b5c] border-[#ff3b5c]/45 hover:bg-[#ff3b5c]/30 hover:shadow-glow-crimson',
    emerald:
      'bg-[#34d399]/20 text-[#34d399] border-[#34d399]/45 hover:bg-[#34d399]/30',
    ghost: 'bg-transparent text-slate-300 border-transparent hover:bg-white/[0.06] hover:text-white',
  }[variant];

  const sizes = {
    sm: 'px-3 py-1.5 text-xs rounded-[12px]',
    md: 'px-4 py-2 text-sm rounded-[14px]',
    lg: 'px-5 py-2.5 text-sm font-semibold rounded-[14px]',
  }[size];

  return (
    <button
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 font-medium border backdrop-blur-xl transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[#22d3ee]/60 ${styles} ${sizes} ${
        disabled ? 'opacity-45 cursor-not-allowed pointer-events-none' : 'active:scale-[0.98]'
      } ${className}`}
      style={{ boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.15)' }}
      {...props}
    >
      {children}
    </button>
  );
};

export const GlassBadge: React.FC<{
  children: React.ReactNode;
  tone?: 'crimson' | 'amber' | 'cyan' | 'violet' | 'emerald' | 'slate';
  className?: string;
}> = ({ children, tone = 'slate', className = '' }) => {
  const tones = {
    crimson: 'bg-[#ff3b5c]/15 text-[#ff3b5c] border-[#ff3b5c]/35',
    amber: 'bg-[#ffb020]/15 text-[#ffb020] border-[#ffb020]/35',
    cyan: 'bg-[#22d3ee]/15 text-[#22d3ee] border-[#22d3ee]/35',
    violet: 'bg-[#a78bfa]/15 text-[#a78bfa] border-[#a78bfa]/35',
    emerald: 'bg-[#34d399]/15 text-[#34d399] border-[#34d399]/35',
    slate: 'bg-white/[0.07] text-slate-300 border-white/[0.14]',
  }[tone];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${tones} ${className}`}
    >
      {children}
    </span>
  );
};

export const GlassPill = GlassBadge;

export const GlassInput: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({ className = '', ...props }) => (
  <input
    className={`w-full rounded-[14px] bg-white/[0.05] border border-white/[0.12] px-3.5 py-2 text-sm text-slate-100 placeholder-slate-400 backdrop-blur-xl focus:outline-none focus:border-[#22d3ee] focus:ring-2 focus:ring-[#22d3ee]/30 transition-all ${className}`}
    {...props}
  />
);

export const GlassSelect: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({
  className = '',
  children,
  ...props
}) => (
  <select
    className={`rounded-[14px] bg-[#0c1324]/90 border border-white/[0.14] px-3.5 py-2 text-sm text-slate-100 backdrop-blur-xl focus:outline-none focus:border-[#22d3ee] focus:ring-2 focus:ring-[#22d3ee]/30 transition-all ${className}`}
    {...props}
  >
    {children}
  </select>
);

export const GlassSkeleton: React.FC<{ className?: string }> = ({ className = 'h-16 w-full' }) => (
  <div
    className={`animate-pulse rounded-[16px] bg-gradient-to-r from-white/[0.04] via-white/[0.09] to-white/[0.04] border border-white/[0.06] ${className}`}
  />
);

export const GlassStat: React.FC<{
  label: string;
  value: string | number;
  sub?: string;
  icon?: React.ReactNode;
  accent?: 'crimson' | 'amber' | 'cyan' | 'violet' | 'emerald' | 'slate';
}> = ({ label, value, sub, icon, accent = 'cyan' }) => {
  const accentColor = {
    crimson: 'text-[#ff3b5c]',
    amber: 'text-[#ffb020]',
    cyan: 'text-[#22d3ee]',
    violet: 'text-[#a78bfa]',
    emerald: 'text-[#34d399]',
    slate: 'text-slate-200',
  }[accent];

  return (
    <GlassCard className="p-4 flex flex-col justify-between">
      <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
        <span className="font-medium tracking-wide uppercase">{label}</span>
        {icon && <span className={accentColor}>{icon}</span>}
      </div>
      <div className="font-mono text-2xl font-semibold text-white tabular-nums tracking-tight">{value}</div>
      {sub && <div className="text-[11px] text-slate-400 mt-1">{sub}</div>}
    </GlassCard>
  );
};
