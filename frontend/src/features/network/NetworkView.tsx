import { Component, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import {
  ArrowUpRight,
  Box,
  Crosshair,
  Download,
  Expand,
  Focus,
  Layers3,
  List,
  Network as NetworkIcon,
  RotateCcw,
  Search,
  Tag,
  Users,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { api } from '../../api/client';
import type { AnalysisMode, GraphEdge, GraphNode, GraphResponse, PersonRecord } from '../../api/types';
import { GlassBadge, GlassButton, GlassCard, GlassSkeleton } from '../../components/glass';
import { formatNumber, methodLabel, tierMeta } from '../../utils/format';
import { displayColor, EDGE_COLORS, edgeColor, endpoint, filterGraph, nodeRadius, pulse } from './graph-utils';
import type { GraphCommand } from './SpatialGraph';
import { forceX, forceY } from 'd3-force-3d';

const SpatialGraph = lazy(() => import('./SpatialGraph'));

type Kind = 'observed' | 'inferred' | 'predicted';
type View = '3d' | '2d' | 'list';

interface NetworkViewProps {
  caseId: string;
  mode: AnalysisMode;
  selectedPersonId: string | null;
  onSelectPerson: (personId: string | null) => void;
  onOpenPairEvidence: (personA: string, personB: string) => void;
  onToast: (msg: string, tone?: 'cyan' | 'emerald' | 'crimson' | 'amber') => void;
  reducedMotion?: boolean;
  /** Bumped by the shell after an analysis run so the graph reloads the new results. */
  analysisVersion?: number;
}

/** If the 3D renderer throws (no WebGL), show the 2D view instead of a broken panel. */
class GraphBoundary extends Component<{ children: ReactNode; onFail: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onFail();
  }
  render() {
    return this.state.failed ? <CenterNote title="Switching to 2D…" /> : this.props.children;
  }
}

function CenterNote({ title, description }: { title: string; description?: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-6">
      <NetworkIcon className="w-10 h-10 text-slate-600 mb-3" strokeWidth={1.2} />
      <p className="text-sm font-semibold text-slate-200">{title}</p>
      {description && <p className="text-xs text-slate-400 mt-1 max-w-sm">{description}</p>}
    </div>
  );
}

const KIND_META: Record<Kind, { label: string; swatch: string }> = {
  observed: { label: 'Observed', swatch: EDGE_COLORS.observed },
  inferred: { label: 'Inferred', swatch: EDGE_COLORS.inferred },
  predicted: { label: 'Predicted', swatch: EDGE_COLORS.predictedEvidence },
};

export const NetworkView: React.FC<NetworkViewProps> = ({
  caseId,
  mode,
  selectedPersonId,
  onSelectPerson,
  onOpenPairEvidence,
  onToast,
  reducedMotion = false,
  analysisVersion = 0,
}) => {
  const [kinds, setKinds] = useState<Kind[]>(['observed', 'inferred', 'predicted']);
  const [focus, setFocus] = useState('');
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const [matches, setMatches] = useState<PersonRecord[]>([]);
  const [department, setDepartment] = useState('');
  const [community, setCommunity] = useState('');
  const [limit, setLimit] = useState(60);
  const [labels, setLabels] = useState(true);
  const [view, setView] = useState<View>('3d');
  const [webglFailed, setWebglFailed] = useState(false);
  const [command, setCommand] = useState<GraphCommand>({ type: 'fit', id: 0 });
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [data, setData] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const box = useRef<HTMLDivElement>(null);
  const graph2d = useRef<ForceGraphMethods<GraphNode, GraphEdge>>();
  const fitOnce = useRef(false);

  const activeKinds = mode === 'observed_only' ? kinds.filter((k) => k !== 'inferred') : kinds;
  const includeKey = activeKinds.join(',');

  // Reset view state when the case changes.
  useEffect(() => {
    setFocus('');
    setSelected('');
    setDepartment('');
    setCommunity('');
  }, [caseId]);

  useEffect(() => {
    if (!caseId || !includeKey) {
      setData(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getGraph(caseId, { mode, include: includeKey, limit, edge_limit: Math.min(limit * 3, 300), focus: focus || undefined })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setData(null);
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [caseId, mode, includeKey, limit, focus, reloadKey, analysisVersion]);

  // Debounced server-side person search (covers people outside the current view).
  useEffect(() => {
    const q = search.trim();
    if (!q) {
      setMatches([]);
      return;
    }
    const timer = setTimeout(() => {
      api
        .getPersons(caseId, { q, limit: 7 })
        .then((res) => setMatches(res.items || []))
        .catch(() => setMatches([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [search, caseId]);

  const gd = useMemo(() => filterGraph(data, department, community), [data, department, community]);
  const ranking = useMemo(() => [...gd.nodes].sort((a, b) => (b.pagerank || 0) - (a.pagerank || 0)), [gd]);
  const byId = useMemo(() => new Map(gd.nodes.map((n) => [n.id, n])), [gd]);
  const chosen = byId.get(selected);
  const selectedLinks = gd.links.filter((e) => endpoint(e.source) === selected || endpoint(e.target) === selected);
  const tierCounts = useMemo(() => {
    const c = { key_figure: 0, secondary_figure: 0, connector: 0 };
    for (const n of gd.nodes) if (n.tier && n.tier !== 'neutral') c[n.tier] += 1;
    return c;
  }, [gd]);
  const departments = useMemo(() => [...new Set((data?.nodes || []).map((n) => n.department).filter(Boolean))] as string[], [data]);
  const communities = useMemo(
    () => [...new Set((data?.nodes || []).map((n) => n.community_id).filter((c) => c != null))].sort() as string[],
    [data],
  );

  useEffect(() => {
    fitOnce.current = false;
  }, [gd, view]);

  // Gentle pull towards the centre keeps disconnected groups on screen; extra spacing keeps labels readable.
  useEffect(() => {
    const g = graph2d.current;
    if (!g || view !== '2d') return;
    g.d3Force('x', forceX(0).strength(0.06));
    g.d3Force('y', forceY(0).strength(0.06));
    g.d3Force('charge')?.strength(-90).distanceMax(320);
    g.d3Force('link')?.distance(42);
    g.d3ReheatSimulation();
  }, [gd, view]);

  useEffect(() => {
    if (!box.current) return;
    const ob = new ResizeObserver(([e]) =>
      setSize({ width: Math.max(1, e.contentRect.width), height: Math.max(1, e.contentRect.height) }),
    );
    ob.observe(box.current);
    return () => ob.disconnect();
  }, []);

  const fail3d = useCallback(() => {
    setWebglFailed(true);
    setView('2d');
  }, []);

  function select(n: GraphNode) {
    setSelected(n.id);
    if (view === '2d') graph2d.current?.centerAt(n.x || 0, n.y || 0, reducedMotion ? 0 : 350);
    if (view === '3d') setCommand((c) => ({ type: 'focus', id: c.id + 1, nodeId: n.id }));
  }

  function inspect(e: GraphEdge) {
    onOpenPairEvidence(endpoint(e.source), endpoint(e.target));
  }

  function run(type: GraphCommand['type']) {
    if (view === '3d') {
      setCommand((c) => ({ type, id: c.id + 1 }));
      return;
    }
    const g = graph2d.current;
    if (type === 'fit') g?.zoomToFit(reducedMotion ? 0 : 400, 55);
    if (type === 'in' || type === 'out') g?.zoom((g.zoom() || 1) * (type === 'in' ? 1.3 : 0.75), reducedMotion ? 0 : 250);
    if (type === 'export') {
      const canvas = box.current?.querySelector('canvas');
      if (canvas) {
        const a = document.createElement('a');
        a.download = `${caseId}-network.png`;
        a.href = canvas.toDataURL('image/png');
        a.click();
        onToast('Graph exported as PNG', 'emerald');
      }
    }
  }

  const otherName = (e: GraphEdge) => {
    const other = endpoint(e.source) === selected ? endpoint(e.target) : endpoint(e.source);
    return byId.get(other)?.label || other;
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold tracking-[0.22em] text-cyan-300/80">INVESTIGATION · NETWORK EXPLORER</p>
          <h1 className="text-2xl font-semibold text-white mt-1">Every connection has a story.</h1>
          <p className="text-sm text-slate-400 mt-1">Start with a signal. Follow the relationships. Find the evidence.</p>
        </div>
        <div className="flex items-center gap-2">
          <GlassBadge tone="slate">Source: {data?.graph_source?.replace(/_/g, ' ') || '—'}</GlassBadge>
          <GlassBadge tone={mode === 'observed_only' ? 'slate' : 'violet'}>
            {mode === 'observed_only' ? 'Observed only' : 'Observed + inferred'}
          </GlassBadge>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { icon: <Users className="w-4 h-4" />, value: data?.counts.total_nodes, label: 'People in network' },
          { icon: <NetworkIcon className="w-4 h-4" />, value: data?.counts.total_edges, label: 'Available connections' },
          { icon: <Focus className="w-4 h-4" />, value: gd.nodes.length, label: `People in this view (max ${limit})` },
        ].map((m) => (
          <GlassCard key={m.label} className="!py-3">
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              {m.icon}
              {m.label}
            </div>
            <div className="text-2xl font-semibold text-white font-mono mt-1">{m.value ?? '—'}</div>
          </GlassCard>
        ))}
        <GlassCard className="!py-3">
          <div className="text-xs text-slate-400">Highlighted in this view</div>
          <div className="flex items-center gap-3 mt-2 text-xs">
            <span className="flex items-center gap-1.5 text-[#ff8a9d]">
              <span className="w-2.5 h-2.5 rounded-full bg-[#ff3b5c] shadow-[0_0_10px_#ff3b5c] animate-pulse" />
              {tierCounts.key_figure} key
            </span>
            <span className="flex items-center gap-1.5 text-[#ffc861]">
              <span className="w-2.5 h-2.5 rounded-full bg-[#ffb020]" />
              {tierCounts.secondary_figure} secondary
            </span>
            <span className="flex items-center gap-1.5 text-cyan-300">
              <span className="w-2.5 h-2.5 rounded-full border-2 border-[#22d3ee]" />
              {tierCounts.connector} connectors
            </span>
          </div>
        </GlassCard>
      </div>

      {data && !data.run_id && !loading && (
        <div className="rounded-[14px] border border-amber-400/30 bg-amber-400/[0.07] px-4 py-3 text-sm text-amber-200">
          No analysis has been run for this case in <strong>{mode === 'observed_only' ? 'Observed only' : 'Observed + inferred'}</strong> mode yet, so
          nobody is highlighted and there are no suggested links. Use <strong>Run analysis</strong> at the top.
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] gap-5">
        {/* Graph panel */}
        <GlassCard noPadding className="overflow-hidden flex flex-col">
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4 pb-3 border-b border-white/[0.08]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex items-center gap-1.5 text-xs text-slate-400 mr-1">
                <Layers3 className="w-3.5 h-3.5" /> Layers
              </span>
              {(Object.keys(KIND_META) as Kind[]).map((k) => {
                const on = activeKinds.includes(k);
                const disabled = k === 'inferred' && mode === 'observed_only';
                return (
                  <button
                    key={k}
                    aria-pressed={on}
                    disabled={disabled}
                    title={disabled ? 'Switch to Observed + inferred to show inferred links' : undefined}
                    onClick={() => setKinds((x) => (x.includes(k) ? x.filter((v) => v !== k) : [...x, k]))}
                    className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs border transition disabled:opacity-40 disabled:cursor-not-allowed ${
                      on ? 'bg-white/10 border-white/25 text-white' : 'bg-transparent border-white/10 text-slate-500'
                    }`}
                  >
                    <span
                      className="w-4 h-0.5"
                      style={{
                        background: k === 'observed' ? KIND_META[k].swatch : 'transparent',
                        borderTop: k === 'observed' ? undefined : `2px ${k === 'inferred' ? 'dashed' : 'dotted'} ${KIND_META[k].swatch}`,
                      }}
                    />
                    {KIND_META[k].label}
                    {data?.shown_by_kind && <span className="font-mono text-slate-500">{data.shown_by_kind[k] ?? 0}</span>}
                  </button>
                );
              })}
              <label className="flex items-center gap-2 text-xs text-slate-400 ml-2">
                People
                <select
                  aria-label="Number of people shown"
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  className="bg-white/[0.06] border border-white/[0.14] rounded-lg px-2 py-1 text-slate-200"
                >
                  {[25, 60, 100].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="flex items-center p-1 rounded-[12px] bg-white/[0.05] border border-white/[0.1]" role="group" aria-label="View">
              {(['3d', '2d', 'list'] as View[]).map((v) => (
                <button
                  key={v}
                  aria-pressed={view === v}
                  disabled={v === '3d' && webglFailed}
                  onClick={() => setView(v)}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-[9px] text-xs transition disabled:opacity-40 ${
                    view === v ? 'bg-[#22d3ee]/20 text-cyan-100 border border-[#22d3ee]/40' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {v === '3d' ? <Box className="w-3.5 h-3.5" /> : v === '2d' ? <NetworkIcon className="w-3.5 h-3.5" /> : <List className="w-3.5 h-3.5" />}
                  {v === 'list' ? 'List' : v.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div ref={box} className="relative h-[620px] bg-[#070b14]" aria-label="Interactive relationship network">
            {view !== 'list' && (
              <>
                <div className="absolute top-4 left-4 z-10 w-72">
                  <div className="flex items-center gap-2 px-3 py-2 rounded-[12px] bg-[#0a1220]/90 backdrop-blur border border-white/[0.14]">
                    <Search className="w-4 h-4 text-slate-400" />
                    <input
                      aria-label="Search people in this case"
                      placeholder="Find a person in this case…"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      className="bg-transparent outline-none text-sm text-white placeholder:text-slate-500 flex-1"
                    />
                  </div>
                  {search && (
                    <div className="mt-1 rounded-[12px] bg-[#0d1626]/95 border border-white/[0.14] p-1 shadow-glass">
                      {matches.map((p) => (
                        <button
                          key={p.person_id}
                          onClick={() => {
                            setFocus(p.person_id);
                            setSelected(p.person_id);
                            setDepartment('');
                            setCommunity('');
                            setSearch('');
                          }}
                          className="w-full flex items-center justify-between px-3 py-2 rounded-lg text-left text-sm text-slate-200 hover:bg-white/[0.08]"
                        >
                          {p.display_name}
                          <span className="font-mono text-[10px] text-slate-500">{p.person_id}</span>
                        </button>
                      ))}
                      {!matches.length && <p className="px-3 py-2 text-xs text-slate-500">No matching people</p>}
                    </div>
                  )}
                </div>
                <div className="absolute top-4 right-4 z-10 flex gap-1.5">
                  {(
                    [
                      ['in', ZoomIn, 'Zoom in'],
                      ['out', ZoomOut, 'Zoom out'],
                      ['fit', Expand, 'Fit graph'],
                      ['export', Download, 'Export PNG'],
                    ] as const
                  ).map(([type, Icon, title]) => (
                    <button
                      key={type}
                      aria-label={title}
                      title={title}
                      disabled={!gd.nodes.length}
                      onClick={() => run(type)}
                      className="w-9 h-9 grid place-items-center rounded-[10px] bg-[#0a1220]/90 border border-white/[0.14] text-slate-300 hover:text-white hover:border-white/30 disabled:opacity-40"
                    >
                      <Icon className="w-4 h-4" />
                    </button>
                  ))}
                  <button
                    aria-label="Toggle labels"
                    title="Toggle labels"
                    aria-pressed={labels}
                    onClick={() => setLabels(!labels)}
                    className={`w-9 h-9 grid place-items-center rounded-[10px] border ${
                      labels ? 'bg-[#22d3ee]/20 border-[#22d3ee]/45 text-cyan-100' : 'bg-[#0a1220]/90 border-white/[0.14] text-slate-300'
                    }`}
                  >
                    <Tag className="w-4 h-4" />
                  </button>
                </div>
              </>
            )}

            {!activeKinds.length ? (
              <CenterNote title="Choose a relationship layer" description="Use the layer buttons above to explore the network." />
            ) : loading ? (
              <div className="absolute inset-0 p-8 space-y-3">
                <GlassSkeleton className="h-full w-full" />
              </div>
            ) : error ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center px-6" role="alert">
                <p className="text-sm font-semibold text-[#ff8a9d]">Could not load the network</p>
                <p className="text-xs text-slate-400 max-w-sm">{error}</p>
                <GlassButton onClick={() => setReloadKey((k) => k + 1)}>
                  <RotateCcw className="w-4 h-4" /> Retry
                </GlassButton>
              </div>
            ) : !gd.nodes.length ? (
              <CenterNote title="No people match this view" description="Clear the department or community filter, or select another layer." />
            ) : view === 'list' ? (
              <div className="absolute inset-0 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-[#0a1220] text-xs text-slate-400">
                    <tr>
                      <th className="text-left font-medium px-5 py-3">Person</th>
                      <th className="text-left font-medium px-3 py-3">Position</th>
                      <th className="text-left font-medium px-3 py-3">Community</th>
                      <th className="text-right font-medium px-3 py-3">Influence (PageRank)</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {ranking.map((n) => (
                      <tr key={n.id} className="border-t border-white/[0.06] hover:bg-white/[0.03]">
                        <td className="px-5 py-2.5">
                          <button className="flex items-center gap-2.5 text-slate-100 hover:text-white" onClick={() => setSelected(n.id)}>
                            <span className="w-2.5 h-2.5 rounded-full" style={{ background: displayColor(n) }} />
                            {n.label}
                          </button>
                        </td>
                        <td className="px-3 py-2.5">
                          {n.tier !== 'neutral' && <span className={`text-[11px] px-2 py-0.5 rounded-full border ${tierMeta(n.tier).bgClass}`}>{tierMeta(n.tier).label}</span>}
                        </td>
                        <td className="px-3 py-2.5 font-mono text-xs text-slate-400">{n.community_id ?? '—'}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-xs text-slate-300">{formatNumber(n.pagerank)}</td>
                        <td className="px-3 py-2.5 text-right">
                          <button
                            aria-label={`Open ${n.label}`}
                            onClick={() => onSelectPerson(n.id)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.08]"
                          >
                            <ArrowUpRight className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : view === '3d' ? (
              <GraphBoundary onFail={fail3d}>
                <Suspense fallback={<div className="absolute inset-0 p-8"><GlassSkeleton className="h-full w-full" /></div>}>
                  <SpatialGraph
                    data={gd}
                    width={size.width}
                    height={size.height}
                    labels={labels}
                    selected={selected}
                    reduced={reducedMotion}
                    onSelect={select}
                    onEdge={inspect}
                    onFailure={fail3d}
                    command={command}
                    caseId={caseId}
                  />
                </Suspense>
              </GraphBoundary>
            ) : (
              <ForceGraph2D
                ref={graph2d}
                width={size.width}
                height={size.height}
                graphData={gd}
                backgroundColor="#070b14"
                autoPauseRedraw={reducedMotion}
                nodeLabel={() => ''}
                linkLabel={() => ''}
                warmupTicks={70}
                cooldownTicks={reducedMotion ? 0 : 90}
                d3VelocityDecay={0.35}
                onEngineStop={() => {
                  if (!fitOnce.current) {
                    graph2d.current?.zoomToFit(reducedMotion ? 0 : 400, 60);
                    fitOnce.current = true;
                  }
                }}
                onNodeClick={select}
                onLinkClick={inspect}
                linkColor={edgeColor}
                linkWidth={(e) => (e.kind === 'observed' ? 0.8 : 1.4)}
                linkLineDash={(e) => (e.kind === 'observed' ? null : e.kind === 'inferred' ? [5, 4] : [2, 4])}
                linkCurvature={(e) => (e.kind === 'predicted' ? 0.14 : e.kind === 'inferred' ? -0.1 : 0)}
                linkDirectionalParticles={(e) => (!reducedMotion && e.kind === 'predicted' ? 2 : 0)}
                linkDirectionalParticleWidth={2}
                linkDirectionalParticleColor={edgeColor}
                nodeCanvasObject={(n, ctx, scale) => {
                  const r = nodeRadius(n);
                  const x = n.x || 0;
                  const y = n.y || 0;
                  const color = displayColor(n);
                  const t = performance.now();
                  // Blinking halo: key figures pulse fast and wide, secondary figures breathe slowly.
                  if (!reducedMotion && (n.tier === 'key_figure' || n.tier === 'secondary_figure')) {
                    const key = n.tier === 'key_figure';
                    const p = pulse(t + (n.id.length * 137) % 1600, key ? 1600 : 3200);
                    ctx.beginPath();
                    ctx.arc(x, y, r + (key ? 3 + p * 9 : 2 + p * 3), 0, Math.PI * 2);
                    ctx.fillStyle = key ? `rgba(255,59,92,${0.45 * (1 - p) + 0.05})` : `rgba(255,176,32,${0.12 + 0.12 * p})`;
                    ctx.fill();
                  }
                  ctx.beginPath();
                  ctx.arc(x, y, r, 0, Math.PI * 2);
                  ctx.fillStyle = color;
                  ctx.shadowColor = n.tier === 'neutral' ? 'transparent' : color;
                  ctx.shadowBlur = n.tier === 'neutral' ? 0 : 12;
                  ctx.fill();
                  ctx.shadowBlur = 0;
                  if (n.tier === 'connector') {
                    ctx.beginPath();
                    ctx.arc(x, y, r + 2.5, 0, Math.PI * 2);
                    ctx.strokeStyle = '#22d3ee';
                    ctx.lineWidth = 1.6;
                    ctx.stroke();
                  }
                  if (n.id === selected) {
                    ctx.beginPath();
                    ctx.arc(x, y, r + 5, 0, Math.PI * 2);
                    ctx.strokeStyle = '#ffffff';
                    ctx.lineWidth = 1.5 / scale;
                    ctx.stroke();
                  }
                  if (labels && (scale > 1.2 || n.tier !== 'neutral')) {
                    const fs = 11 / scale;
                    ctx.font = `${n.tier === 'neutral' ? 400 : 600} ${fs}px Inter, system-ui, sans-serif`;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'top';
                    ctx.fillStyle = n.tier === 'neutral' ? '#cbd5e1' : color;
                    ctx.fillText(n.label, x, y + r + 3 / scale);
                  }
                }}
                nodePointerAreaPaint={(n, color, ctx) => {
                  ctx.beginPath();
                  ctx.arc(n.x || 0, n.y || 0, nodeRadius(n) + 6, 0, Math.PI * 2);
                  ctx.fillStyle = color;
                  ctx.fill();
                }}
              />
            )}

            {focus && (
              <button
                onClick={() => {
                  setFocus('');
                  setSelected('');
                }}
                className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#22d3ee]/15 border border-[#22d3ee]/40 text-xs text-cyan-100"
              >
                <Crosshair className="w-3.5 h-3.5" /> Focused on {byId.get(focus)?.label || focus}
                <X className="w-3.5 h-3.5" />
              </button>
            )}
            {view !== 'list' && gd.nodes.length > 0 && !loading && !error && (
              <div className="absolute bottom-4 right-4 z-10 text-right text-[11px] text-slate-500 leading-relaxed">
                {view === '3d' ? 'Drag to orbit · scroll to zoom' : 'Drag to pan · scroll to zoom'}
                <br />
                <span className="text-slate-400">Click a person or a link to investigate</span>
              </div>
            )}
          </div>

          {/* Legend */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-t border-white/[0.08] text-xs">
            <div className="flex flex-wrap items-center gap-4 text-slate-300">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-[#ff3b5c] shadow-[0_0_8px_#ff3b5c] animate-pulse" /> Key figure
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-[#ffb020]" /> Secondary
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full border-2 border-[#22d3ee]" /> Connector
              </span>
              <span className="text-slate-600">|</span>
              <span className="flex items-center gap-1.5">
                <span className="w-5 h-0.5" style={{ background: EDGE_COLORS.observed }} /> Observed
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-5 border-t-2 border-dashed" style={{ borderColor: EDGE_COLORS.inferred }} /> Inferred
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-5 border-t-2 border-dotted" style={{ borderColor: EDGE_COLORS.predictedEvidence }} /> Predicted · evidence
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-5 border-t-2 border-dotted" style={{ borderColor: EDGE_COLORS.predictedPattern }} /> Predicted · pattern
              </span>
            </div>
            <span className="font-mono text-slate-500">
              {gd.nodes.length} people · {gd.links.length} links shown
              {data?.truncated ? ` of ${formatNumber(data.counts.total_edges)}` : ''}
            </span>
          </div>
        </GlassCard>

        {/* Inspector */}
        <aside className="space-y-4">
          <GlassCard>
            <p className="text-[11px] font-semibold tracking-[0.2em] text-slate-400">{chosen ? 'SELECTED PERSON' : 'INVESTIGATION LENS'}</p>
            {chosen ? (
              <div className="mt-3 space-y-4">
                <div className="flex items-center gap-3">
                  <div
                    className="w-12 h-12 rounded-full grid place-items-center text-sm font-semibold border"
                    style={{ color: displayColor(chosen), borderColor: displayColor(chosen), background: `${displayColor(chosen)}1f` }}
                  >
                    {chosen.label.split(' ').slice(0, 2).map((s) => s[0]).join('')}
                  </div>
                  <div className="min-w-0">
                    <h2 className="text-base font-semibold text-white truncate">{chosen.label}</h2>
                    <p className="text-xs text-slate-400">{chosen.department || 'Department not recorded'}</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {chosen.tier !== 'neutral' && (
                    <span className={`text-[11px] px-2 py-0.5 rounded-full border ${tierMeta(chosen.tier).bgClass}`}>{tierMeta(chosen.tier).label}</span>
                  )}
                  {chosen.hub_flag && <GlassBadge tone="amber">Hub · verify</GlassBadge>}
                  <GlassBadge>Community {chosen.community_id ?? '—'}</GlassBadge>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  {[
                    [chosen.pagerankRank, 'Influence rank'],
                    [chosen.betweennessRank, 'Bridging rank'],
                    [chosen.degree, 'Connections'],
                  ].map(([v, l]) => (
                    <div key={String(l)} className="rounded-[12px] bg-white/[0.04] border border-white/[0.08] py-2">
                      <div className="font-mono text-lg text-white">{v ?? '—'}</div>
                      <div className="text-[10px] text-slate-400">{l}</div>
                    </div>
                  ))}
                </div>
                <div className="grid gap-2">
                  <GlassButton variant="primary" onClick={() => onSelectPerson(chosen.id)}>
                    Open evidence profile <ArrowUpRight className="w-4 h-4" />
                  </GlassButton>
                  <GlassButton onClick={() => setFocus(chosen.id)}>
                    <Crosshair className="w-4 h-4" /> Focus on this neighbourhood
                  </GlassButton>
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-slate-300 mb-2">Connections in this view</h3>
                  <div className="space-y-1 max-h-64 overflow-auto pr-1">
                    {selectedLinks.slice(0, 12).map((e) => (
                      <button
                        key={e.id}
                        onClick={() => inspect(e)}
                        className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-[10px] text-left hover:bg-white/[0.06]"
                      >
                        <span
                          className="w-4 flex-none"
                          style={{
                            borderTop: `2px ${e.kind === 'observed' ? 'solid' : e.kind === 'inferred' ? 'dashed' : 'dotted'} ${edgeColor(e)}`,
                          }}
                        />
                        <span className="flex-1 min-w-0">
                          <span className="block text-sm text-slate-100 truncate">{otherName(e)}</span>
                          <span className="block text-[11px] text-slate-500">
                            {e.kind === 'predicted' ? methodLabel(e.method || e.type) : `${e.kind} · ${e.type.replace(/_/g, ' ').toLowerCase()}`}
                          </span>
                        </span>
                        <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />
                      </button>
                    ))}
                    {!selectedLinks.length && <p className="text-xs text-slate-500">No connections in the current filters.</p>}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-3 space-y-3">
                <h2 className="text-base font-semibold text-white">Follow a connection.</h2>
                <p className="text-xs text-slate-400">
                  Select a person to see their network position, or a link to open the underlying evidence.
                </p>
                <h3 className="text-xs font-semibold text-slate-300 pt-2">Most influential in this view</h3>
                {ranking.slice(0, 5).map((n, i) => (
                  <button
                    key={n.id}
                    onClick={() => select(n)}
                    className="w-full flex items-center gap-3 px-2.5 py-2 rounded-[10px] text-left hover:bg-white/[0.06]"
                  >
                    <span className="font-mono text-xs text-slate-500">0{i + 1}</span>
                    <span
                      className={`w-2.5 h-2.5 rounded-full ${n.tier === 'key_figure' && !reducedMotion ? 'animate-pulse' : ''}`}
                      style={{ background: displayColor(n), boxShadow: n.tier === 'neutral' ? undefined : `0 0 8px ${displayColor(n)}` }}
                    />
                    <span className="flex-1 text-sm text-slate-100 truncate">{n.label}</span>
                    <span className="text-[10px] text-slate-500">{tierMeta(n.tier).label}</span>
                  </button>
                ))}
              </div>
            )}
          </GlassCard>

          <GlassCard>
            <p className="text-[11px] font-semibold tracking-[0.2em] text-slate-400 mb-3">FILTER THIS VIEW</p>
            <label className="block text-xs text-slate-400 mb-3">
              Department
              <select
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="mt-1 w-full bg-white/[0.06] border border-white/[0.14] rounded-[10px] px-3 py-2 text-sm text-slate-200"
              >
                <option value="">All departments</option>
                {departments.map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-slate-400 mb-3">
              Community
              <select
                value={community}
                onChange={(e) => setCommunity(e.target.value)}
                className="mt-1 w-full bg-white/[0.06] border border-white/[0.14] rounded-[10px] px-3 py-2 text-sm text-slate-200"
              >
                <option value="">All communities</option>
                {communities.map((c) => (
                  <option key={c} value={c}>
                    Community {c}
                  </option>
                ))}
              </select>
            </label>
            {(department || community) && (
              <GlassButton
                onClick={() => {
                  setDepartment('');
                  setCommunity('');
                }}
              >
                Clear filters
              </GlassButton>
            )}
            <p className="text-[11px] text-slate-500 mt-3">Filters change what is drawn. Analysis always uses the full case.</p>
          </GlassCard>
        </aside>
      </div>

      {webglFailed && (
        <p className="text-xs text-amber-300">3D rendering is unavailable on this device, so the 2D graph is shown. It contains the same evidence.</p>
      )}
      {!!data?.warnings?.length && (
        <details className="rounded-[14px] border border-amber-400/25 bg-amber-400/[0.06] px-4 py-3 text-xs text-amber-200">
          <summary className="cursor-pointer font-medium">Data provenance & run notes ({data.warnings.length})</summary>
          <ul className="mt-2 space-y-1 list-disc pl-5 text-amber-100/80">
            {data.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-[11px] text-slate-500">
        Key figure, secondary and connector describe position in the recorded network (influence and bridging), not guilt. Observed records,
        inferred overlaps and predicted links stay distinct.
      </p>
    </div>
  );
};
