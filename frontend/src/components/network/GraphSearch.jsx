import { useMemo, useRef, useState } from 'react';
import './GraphSearch.css';

export default function GraphSearch({ nodes, onSelect }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const inputRef = useRef(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return nodes
      .filter((n) => n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q))
      .slice(0, 8);
  }, [query, nodes]);

  const choose = (id) => {
    onSelect(id);
    setQuery('');
    setOpen(false);
    inputRef.current?.blur();
  };

  return (
    <div className="graph-search">
      <label className="sr-only" htmlFor="graph-search-input">
        Search entities by name or ID
      </label>
      <input
        id="graph-search-input"
        ref={inputRef}
        type="text"
        className="graph-search-input"
        placeholder="Search by name or entity ID…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setQuery('');
            setOpen(false);
          } else if (event.key === 'Enter' && results.length) {
            choose(results[0].id);
          }
        }}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls="graph-search-results"
        autoComplete="off"
      />
      {open && results.length > 0 && (
        <ul id="graph-search-results" className="graph-search-results" role="listbox">
          {results.map((n) => (
            <li key={n.id} role="option" aria-selected="false">
              <button type="button" className="graph-search-result" onMouseDown={() => choose(n.id)}>
                <span className="graph-search-result-name">
                  {n.name}
                  {n.flag && <span className={'flag flag--' + n.flag}>{n.flag}</span>}
                </span>
                <span className="mono dim">{n.id}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
