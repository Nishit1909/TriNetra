import './Sparkline.css';

// Minimal trend instrument — no axes, no gradient fill, no decoration.
// Encodes one thing: is this metric rising, falling, or flat over the window.
export default function Sparkline({ data, width = 72, height = 22, label, tone = 'signal' }) {
  if (!data || data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);

  const points = data.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / range) * height;
    return [x, y];
  });

  const path = points.map(([x, y], i) => (i === 0 ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1)).join(' ');
  const [lastX, lastY] = points[points.length - 1];
  const rising = data[data.length - 1] >= data[0];

  return (
    <svg
      className={'sparkline sparkline--' + tone}
      width={width}
      height={height}
      viewBox={'0 0 ' + width + ' ' + height}
      role="img"
      aria-label={label || (rising ? 'trending up over 24 hours' : 'trending down over 24 hours')}
    >
      <path className="sparkline-path" d={path} />
      <circle className="sparkline-dot" cx={lastX} cy={lastY} r="1.6" />
    </svg>
  );
}
