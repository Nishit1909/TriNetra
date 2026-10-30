import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import './Shell.css';
import { systemStatus } from '../data/mock';

const NAV = [
  { to: '/', label: 'Dashboard', glyph: 'DB' },
  { to: '/network', label: 'Network', glyph: 'NT' },
  { to: '/people', label: 'People', glyph: 'PP' },
  { to: '/cases', label: 'Cases', glyph: 'CS' },
  { to: '/communities', label: 'Communities', glyph: 'CM' },
  { to: '/predictions', label: 'Predictions', glyph: 'PR' },
  { to: '/ingestion', label: 'Ingestion', glyph: 'IN' },
];

function Clock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  return <span className="mono">{hh}:{mm}:{ss}</span>;
}

export default function Shell({ children }) {
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to workspace</a>
      <header className="topbar">
        <div className="topbar-brand">
          <span className="topbar-mark">SIH26189</span>
          <span className="topbar-sub">Intelligence Workspace</span>
        </div>
        <div className="topbar-status">
          <div className="status-item">
            <span className="status-label">ingest queue</span>
            <span className="mono status-value">{systemStatus.ingestQueue}</span>
          </div>
          <div className="status-item">
            <span className="status-label">model</span>
            <span className="mono status-value">{systemStatus.modelVersion}</span>
          </div>
          <div className="status-item">
            <span className="status-label">last sync</span>
            <span className="mono status-value">{systemStatus.lastSync}</span>
          </div>
          <div className="status-item">
            <span className="status-label">local time</span>
            <Clock />
          </div>
          <div className="status-live">
            <span className="live-dot" />
            <span className="mono">LIVE</span>
          </div>
        </div>
      </header>
      <div className="shell-body">
        <nav className="rail" aria-label="Primary">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => 'rail-item' + (isActive ? ' rail-item--active' : '')}
            >
              <span className="rail-glyph mono">{item.glyph}</span>
              <span className="rail-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <main className="workspace" id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
