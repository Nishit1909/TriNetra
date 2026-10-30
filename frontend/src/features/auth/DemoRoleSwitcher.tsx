import React from 'react';
import { UserCheck } from 'lucide-react';
import { DEMO_USERS } from '../../api/demoUsers';
import { AuthMeResponse } from '../../api/types';
import { GlassBadge } from '../../components/glass';

interface DemoRoleSwitcherProps {
  authMe: AuthMeResponse | null;
  activeUserId: string;
  open: boolean;
  onToggle: () => void;
  onSelectUser: (userId: string) => void;
}

export const DemoRoleSwitcher: React.FC<DemoRoleSwitcherProps> = ({
  authMe,
  activeUserId,
  open,
  onToggle,
  onSelectUser,
}) => {
  const activeDemoObj = DEMO_USERS.find((u) => u.user_id === activeUserId) || DEMO_USERS[0];

  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className="flex items-center gap-2.5 px-3.5 py-1.5 rounded-[14px] bg-white/[0.07] hover:bg-white/[0.12] border border-white/[0.15] text-xs transition"
      >
        <UserCheck className="w-4 h-4 text-[#22d3ee]" />
        <div className="text-left">
          <div className="font-semibold text-white flex items-center gap-1.5">
            <span>{activeDemoObj.display_name}</span>
            {authMe?.is_demo && (
              <span className="px-1.5 py-0.2 rounded bg-amber-500/25 text-amber-300 font-mono text-[10px] border border-amber-400/40">
                DEMO
              </span>
            )}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-cyan-300 font-mono">
            Role: {authMe?.role || activeDemoObj.role}
          </div>
        </div>
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 rounded-[18px] bg-[#080d1a]/95 backdrop-blur-2xl border border-white/[0.16] shadow-glass p-3 space-y-2 z-50">
          <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Demo Role Switcher (X-Demo-User Header)
          </div>
          {DEMO_USERS.map((u) => {
            const selected = u.user_id === activeUserId;
            return (
              <button
                key={u.user_id}
                onClick={() => onSelectUser(u.user_id)}
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
  );
};
