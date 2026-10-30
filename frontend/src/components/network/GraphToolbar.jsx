import './GraphToolbar.css';

export default function GraphToolbar({ showLabels, onToggleLabels, onZoomIn, onZoomOut, onReset, onExport }) {
  return (
    <div className="graph-toolbar" role="toolbar" aria-label="Graph view controls">
      <button type="button" className="gt-btn" onClick={onZoomIn} aria-label="Zoom in">
        +
      </button>
      <button type="button" className="gt-btn" onClick={onZoomOut} aria-label="Zoom out">
        −
      </button>
      <button type="button" className="gt-btn gt-btn--wide" onClick={onReset}>
        Reset view
      </button>
      <button
        type="button"
        className={'gt-btn gt-btn--wide' + (showLabels ? ' gt-btn--active' : '')}
        onClick={onToggleLabels}
        aria-pressed={showLabels}
      >
        Labels
      </button>
      <button type="button" className="gt-btn gt-btn--wide" onClick={onExport}>
        Export PNG
      </button>
    </div>
  );
}
