import './Panel.css';

export default function Panel({
  label,
  value,
  meta,
  live,
  loading,
  skeleton,
  className = '',
  children,
  style,
}) {
  return (
    <section className={'panel ' + className} style={style} aria-busy={loading || undefined}>
      {(label || value) && (
        <header className="panel-head">
          <h2 className="panel-label">{label}</h2>
          {value && <span className="mono panel-value">{value}</span>}
          {meta && <span className="mono panel-meta">{meta}</span>}
          {live && (
            <span className="panel-live">
              <span className="panel-live-dot" aria-hidden="true" />
              live
            </span>
          )}
        </header>
      )}
      <div className="panel-body">{loading ? skeleton : children}</div>
    </section>
  );
}
