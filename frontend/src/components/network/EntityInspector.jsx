import './EntityInspector.css';

function ConnectionRow({ conn, byId, onFocus }) {
  const target = byId.get(conn.id);
  if (!target) return null;
  return (
    <li className="insp-conn">
      <button type="button" className="insp-conn-btn" onClick={() => onFocus(conn.id)}>
        <span className="insp-conn-name">{target.name}</span>
        <span className="mono insp-conn-id dim">{conn.id}</span>
      </button>
      <span className="mono insp-conn-strength">{conn.strength.toFixed(2)}</span>
    </li>
  );
}

export default function EntityInspector({ node, connections, byId, communityLabel, onFocusEntity }) {
  if (!node) {
    return (
      <div className="insp-empty">
        <p>No entity selected.</p>
        <p className="faint">
          Click a node in the graph, or use the search bar above, to inspect an entity's profile,
          connections, and case references.
        </p>
      </div>
    );
  }

  const sorted = [...connections].sort((a, b) => b.strength - a.strength);

  return (
    <div className="insp">
      <div className="insp-head">
        <h3 className="insp-name">{node.name}</h3>
        {node.flag && <span className={'flag flag--' + node.flag}>{node.flag}</span>}
      </div>
      <div className="mono insp-id">{node.id}</div>

      <dl className="insp-stats">
        <div className="insp-stat">
          <dt className="section-label">Risk score</dt>
          <dd className={'metric insp-stat-value' + (node.flag ? ' insp-stat-value--flag' : '')}>
            {node.risk.toFixed(2)}
          </dd>
        </div>
        <div className="insp-stat">
          <dt className="section-label">Connections</dt>
          <dd className="metric insp-stat-value">{node.degree}</dd>
        </div>
      </dl>

      <div className="insp-row">
        <span className="section-label">Community</span>
        <span className="insp-row-value">{communityLabel || '—'}</span>
      </div>

      <div className="insp-row">
        <span className="section-label">Case references</span>
        <span className="insp-row-value">
          {node.caseRefs.length
            ? node.caseRefs.map((c) => (
                <span key={c} className="mono insp-case">{c}</span>
              ))
            : <span className="faint">None on file</span>}
        </span>
      </div>

      <div className="insp-section-label section-label">
        Known connections <span className="mono">({sorted.length})</span>
      </div>
      <ul className="insp-conn-list">
        {sorted.map((c) => (
          <ConnectionRow key={c.id} conn={c} byId={byId} onFocus={onFocusEntity} />
        ))}
      </ul>
    </div>
  );
}
