import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Panel from '../components/Panel';
import Sparkline from '../components/Sparkline';
import './Dashboard.css';
import {
  caseStats,
  caseTrends,
  riskFeed,
  activityLog,
  caseLoad,
  communitySnapshot,
  ingestSources,
} from '../data/mock';

const NEW_EVENTS = [
  { event: 'Risk score recalculated', actorPool: ['model'] },
  { event: 'Communication record ingested', actorPool: ['ingest'] },
  { event: 'Entity resolution merged 2 identities', actorPool: ['auto'] },
  { event: 'Case note added', actorPool: ['A. Reyes', 'D. Farah', 'K. Osei'] },
];

// Advances the log's own in-story clock rather than the viewer's real wall time,
// so simulated updates stay chronologically consistent with the seeded mock timeline.
function advanceClock(hhmmss, deltaSeconds) {
  const [h, m, s] = hhmmss.split(':').map(Number);
  const total = (h * 3600 + m * 60 + s + deltaSeconds) % 86400;
  const nh = Math.floor(total / 3600);
  const nm = Math.floor((total % 3600) / 60);
  const ns = total % 60;
  return [nh, nm, ns].map((n) => String(n).padStart(2, '0')).join(':');
}

function fmtDelta(v, decimals = 2) {
  const sign = v > 0 ? '+' : '';
  return sign + v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function Delta({ v, decimals = 2 }) {
  const cls = v > 0 ? 'delta-up' : 'delta-flat';
  return <span className={'mono ' + cls}>{fmtDelta(v, decimals)}</span>;
}

function Flag({ type }) {
  if (!type) return null;
  return <span className={'flag flag--' + type}>{type}</span>;
}

function Kpi({ label, value, trend, tone, decimals = 0 }) {
  const delta = trend ? trend[trend.length - 1] - trend[0] : null;
  return (
    <div className={'kpi' + (tone === 'flag' ? ' kpi--flag' : '')}>
      <div className="kpi-top">
        <span className="kpi-label">{label}</span>
        {trend && (
          <Sparkline
            data={trend}
            tone={tone === 'flag' ? 'red' : 'signal'}
            label={label + ', trailing 24 hours'}
          />
        )}
      </div>
      <span className={'metric kpi-value' + (tone === 'flag' ? ' kpi-value--red' : '')}>
        {value}
      </span>
      {delta !== null && (
        <div className="kpi-delta">
          <Delta v={delta} decimals={decimals} />
          <span className="kpi-delta-label">Δ 24h</span>
        </div>
      )}
    </div>
  );
}

function TableSkeleton({ rows = 5, cols = 4 }) {
  return (
    <table className="dtable" aria-hidden="true">
      <tbody>
        {Array.from({ length: rows }).map((_, r) => (
          <tr key={r}>
            {Array.from({ length: cols }).map((_, c) => (
              <td key={c}>
                <span className="skeleton-block skeleton-cell" />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ListSkeleton({ rows = 4 }) {
  return (
    <div className="skeleton-list" aria-hidden="true">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="skeleton-listrow">
          <span className="skeleton-block skeleton-line skeleton-line--wide" />
          <span className="skeleton-block skeleton-line skeleton-line--narrow" />
        </div>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState(riskFeed);
  const [log, setLog] = useState(activityLog);
  const [pulseId, setPulseId] = useState(null);
  const [logPulse, setLogPulse] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setLoading(false), 620);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (loading) return undefined;
    const interval = setInterval(() => {
      setRows((prev) => {
        const idx = Math.floor(Math.random() * prev.length);
        const row = prev[idx];
        const delta = Math.round((Math.random() * 0.08 - 0.03) * 100) / 100;
        const risk = Math.min(0.99, Math.max(0.35, Math.round((row.risk + delta) * 100) / 100));
        const next = [...prev];
        next[idx] = { ...row, risk, delta };
        setPulseId(row.id);
        return next;
      });

      if (Math.random() > 0.45) {
        const tpl = NEW_EVENTS[Math.floor(Math.random() * NEW_EVENTS.length)];
        const actor = tpl.actorPool[Math.floor(Math.random() * tpl.actorPool.length)];
        setLog((prev) => [
          {
            t: advanceClock(prev[0].t, 30 + Math.floor(Math.random() * 150)),
            event: tpl.event,
            ref: rows[Math.floor(Math.random() * rows.length)]?.id ?? '—',
            actor,
          },
          ...prev,
        ].slice(0, 8));
        setLogPulse(true);
      }
    }, 7000);
    return () => clearInterval(interval);
  }, [loading, rows]);

  useEffect(() => {
    if (!pulseId) return undefined;
    const t = setTimeout(() => setPulseId(null), 900);
    return () => clearTimeout(t);
  }, [pulseId]);

  useEffect(() => {
    if (!logPulse) return undefined;
    const t = setTimeout(() => setLogPulse(false), 900);
    return () => clearTimeout(t);
  }, [logPulse]);

  return (
    <div className="dash">
      <h1 className="sr-only">Command center overview</h1>

      <div className="kpi-row">
        <Kpi label="active cases" value={caseStats.activeCases} trend={caseTrends.activeCases} />
        <Kpi label="open leads" value={caseStats.openLeads} trend={caseTrends.openLeads} />
        <Kpi
          label="flagged entities"
          value={caseStats.flaggedEntities}
          trend={caseTrends.flaggedEntities}
          tone="flag"
        />
        <Kpi
          label="records ingested, 24h"
          value={caseStats.newIngest24h.toLocaleString()}
          trend={caseTrends.newIngest24h}
        />
      </div>

      <div className="dash-grid">
        <Panel
          label="risk feed"
          meta="sorted by score, desc"
          className="span-risk"
          loading={loading}
          skeleton={<TableSkeleton rows={7} cols={5} />}
        >
          <table className="dtable">
            <thead>
              <tr>
                <th scope="col">entity</th>
                <th scope="col">id</th>
                <th scope="col" className="num">risk</th>
                <th scope="col" className="num">Δ 24h</th>
                <th scope="col">case</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.id === pulseId ? 'row-pulse' : ''}>
                  <td>
                    <Link className="row-link" to={`/people?entity=${r.id}`}>
                      {r.name}
                    </Link>
                    <Flag type={r.flag} />
                  </td>
                  <td className="mono dim">{r.id}</td>
                  <td className="num mono risk-cell">{r.risk.toFixed(2)}</td>
                  <td className="num"><Delta v={r.delta} /></td>
                  <td className="mono dim">
                    <Link className="row-link" to={`/cases?case=${r.case}`}>
                      {r.case}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel
          label="activity log"
          live
          className="span-activity"
          loading={loading}
          skeleton={<ListSkeleton rows={6} />}
        >
          <ul className="loglist" aria-live="polite">
            {log.map((a, i) => (
              <li key={a.t + a.ref} className={'logrow' + (i === 0 && logPulse ? ' logrow-pulse' : '')}>
                <span className="mono logtime">{a.t}</span>
                <span className="logevent">{a.event}</span>
                <span className="mono logref">{a.ref}</span>
                <span className="mono logactor">{a.actor}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          label="case load"
          meta={caseLoad.length + ' active'}
          className="span-cases"
          loading={loading}
          skeleton={<TableSkeleton rows={5} cols={5} />}
        >
          <table className="dtable">
            <thead>
              <tr>
                <th scope="col">case</th>
                <th scope="col">analyst</th>
                <th scope="col" className="num">entities</th>
                <th scope="col">priority</th>
                <th scope="col" className="num">updated</th>
              </tr>
            </thead>
            <tbody>
              {caseLoad.map((c) => (
                <tr key={c.case}>
                  <td className="mono">
                    <Link className="row-link" to={`/cases?case=${c.case}`}>
                      {c.case}
                    </Link>
                  </td>
                  <td>{c.analyst}</td>
                  <td className="num mono">{c.entities}</td>
                  <td>
                    <span className={'priority priority--' + c.priority}>{c.priority}</span>
                  </td>
                  <td className="num mono dim">{c.updated}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel
          label="pipeline & data health"
          meta={ingestSources.length + ' sources'}
          className="span-pipeline"
          loading={loading}
          skeleton={<TableSkeleton rows={4} cols={4} />}
        >
          <table className="dtable">
            <thead>
              <tr>
                <th scope="col">source</th>
                <th scope="col" className="num">records, 24h</th>
                <th scope="col">last sync</th>
                <th scope="col">status</th>
              </tr>
            </thead>
            <tbody>
              {ingestSources.map((s) => (
                <tr key={s.source}>
                  <td>{s.source}</td>
                  <td className="num mono">{s.records24h.toLocaleString()}</td>
                  <td className="mono dim">{s.lastSync}</td>
                  <td>
                    <span className={'pipe-status' + (s.nominal ? '' : ' pipe-status--attn')}>
                      <span className="pipe-dot" aria-hidden="true" />
                      {s.nominal ? 'nominal' : 'delayed'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel
          label="community snapshot"
          meta="louvain"
          className="span-community"
          loading={loading}
          skeleton={<ListSkeleton rows={3} />}
        >
          <ul className="commlist">
            {communitySnapshot.map((c) => (
              <li key={c.id} className="commrow">
                <div className="commrow-top">
                  <Link className="row-link mono commid" to={`/communities?id=${c.id}`}>
                    {c.id}
                  </Link>
                  <span className="commlabel">{c.label}</span>
                </div>
                <div className="commrow-bars">
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: (c.density * 100) + '%' }} />
                  </div>
                  <span className="mono bar-num">{c.density.toFixed(2)}</span>
                </div>
                <div className="commrow-foot">
                  <span className="mono dim">{c.members} members</span>
                  {c.flagged > 0 && (
                    <span className="mono flagged-count">{c.flagged} flagged</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
