import './GraphLegend.css';

export default function GraphLegend() {
  return (
    <div className="graph-legend" aria-label="Graph legend">
      <div className="gl-title section-label">Legend</div>
      <ul className="gl-list">
        <li className="gl-row">
          <span className="gl-swatch gl-swatch--node" />
          Entity
        </li>
        <li className="gl-row">
          <span className="gl-swatch gl-swatch--kingpin" />
          Flagged — kingpin
        </li>
        <li className="gl-row">
          <span className="gl-swatch gl-swatch--boss" />
          Flagged — boss
        </li>
      </ul>
      <div className="gl-note faint">Node size — connection count</div>
      <div className="gl-note faint">Edge opacity — relationship strength</div>
    </div>
  );
}
