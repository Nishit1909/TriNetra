import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { forceSimulation, forceManyBody, forceLink, forceCenter, forceCollide, forceX, forceY } from 'd3-force';
import { select } from 'd3-selection';
import { zoom as d3zoom, zoomIdentity } from 'd3-zoom';
import { drag as d3drag } from 'd3-drag';
import './NetworkGraph.css';

const SIM_WIDTH = 1280;
const SIM_HEIGHT = 860;
const RADIUS_MIN = 4;
const RADIUS_MAX = 20;
const GRID_STEP = 48;
const SIGNAL_PULSE_CAP = 16;

function radiusFor(degree) {
  return Math.min(RADIUS_MAX, RADIUS_MIN + Math.sqrt(degree) * 3.1);
}

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

const EXPORT_STYLE = `
  text { font-family: 'DM Sans', sans-serif; fill: #dde3ec; font-size: 10px; }
  .node-id { font-family: 'IBM Plex Mono', monospace; }
  line { stroke: #2a3543; }
  circle.node-fill { stroke-width: 1.2px; }
`;

const NetworkGraph = forwardRef(function NetworkGraph(
  { nodes, edges, connections, selectedId, focusedId, onSelectNode, onNodeFocus, showLabels },
  ref,
) {
  const containerRef = useRef(null);
  const svgRef = useRef(null);
  const zoomLayerRef = useRef(null);
  const nodeElsRef = useRef(new Map());
  const edgeElsRef = useRef([]);
  const simRef = useRef(null);
  const transformRef = useRef(zoomIdentity);
  const zoomBehaviorRef = useRef(null);
  const prevSelectedRef = useRef(null);

  const [hoveredId, setHoveredId] = useState(null);
  const [pulses, setPulses] = useState([]);

  // Stable working copies — d3-force mutates edge.source/target into node object refs,
  // and node objects gain x/y/vx/vy. Keep these separate from the props the rest of
  // React reasons about with plain ids.
  const simNodes = useMemo(() => nodes.map((n) => ({ ...n })), [nodes]);
  const simEdges = useMemo(() => edges.map((e) => ({ ...e })), [edges]);

  const nodesById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  // Which end of each edge (if either) is a flagged entity — drives the thicker,
  // slow dash-creep "tracking a signal back to source" treatment.
  const edgeFlagInfo = useMemo(
    () =>
      edges.map((e) => {
        const s = nodesById.get(e.source);
        const t = nodesById.get(e.target);
        if (s && s.flag) return { flagged: true, toward: 'source' };
        if (t && t.flag) return { flagged: true, toward: 'target' };
        return { flagged: false, toward: null };
      }),
    [edges, nodesById],
  );

  const connectedSet = useMemo(() => {
    if (!selectedId) return null;
    const set = new Set([selectedId]);
    (connections.get(selectedId) || []).forEach((c) => set.add(c.id));
    return set;
  }, [selectedId, connections]);

  // --- simulation lifecycle: set up once, drive positions via direct DOM writes ---
  useEffect(() => {
    const simulation = forceSimulation(simNodes)
      .force(
        'link',
        forceLink(simEdges)
          .id((d) => d.id)
          .distance((d) => 90 - d.strength * 40)
          .strength((d) => d.strength * 0.5),
      )
      .force('charge', forceManyBody().strength(-160).distanceMax(460))
      .force('center', forceCenter(SIM_WIDTH / 2, SIM_HEIGHT / 2))
      .force('collide', forceCollide((d) => radiusFor(d.degree) + 7))
      .force('x', forceX(SIM_WIDTH / 2).strength(0.025))
      .force('y', forceY(SIM_HEIGHT / 2).strength(0.025))
      .alphaDecay(0.025);

    function ticked() {
      simNodes.forEach((n) => {
        const el = nodeElsRef.current.get(n.id);
        if (el) el.setAttribute('transform', 'translate(' + n.x.toFixed(1) + ',' + n.y.toFixed(1) + ')');
      });
      simEdges.forEach((e, i) => {
        const el = edgeElsRef.current[i];
        if (el && e.source && e.target) {
          el.setAttribute('x1', e.source.x.toFixed(1));
          el.setAttribute('y1', e.source.y.toFixed(1));
          el.setAttribute('x2', e.target.x.toFixed(1));
          el.setAttribute('y2', e.target.y.toFixed(1));
        }
      });
    }

    if (prefersReducedMotion()) {
      // Skip the visible fly-apart settle, but keep the simulation live — a later drag
      // still needs ticks to repaint. d3-force's own timer idles itself once alpha
      // decays below alphaMin, so this costs nothing at rest.
      for (let i = 0; i < 320; i++) simulation.tick();
      ticked();
    }
    simulation.on('tick', ticked);

    simRef.current = simulation;
    return () => simulation.stop();
  }, [simNodes, simEdges]);

  // --- zoom / pan ---
  useEffect(() => {
    const svgEl = svgRef.current;
    const svgSel = select(svgEl);
    const zoomLayerSel = select(zoomLayerRef.current);

    const zoomBehavior = d3zoom()
      .scaleExtent([0.25, 4])
      .filter((event) => {
        // Node drag has its own gesture handling — don't let canvas panning compete for it.
        if (event.target && event.target.closest && event.target.closest('.node')) return false;
        return !event.ctrlKey && !event.button;
      })
      .on('zoom', (event) => {
        transformRef.current = event.transform;
        zoomLayerSel.attr('transform', event.transform);
      });

    svgSel.call(zoomBehavior);
    zoomBehaviorRef.current = zoomBehavior;

    const rect = svgEl.getBoundingClientRect();
    const scale = Math.min(rect.width / SIM_WIDTH, rect.height / SIM_HEIGHT) * 0.92;
    const t = zoomIdentity
      .translate(rect.width / 2 - (SIM_WIDTH / 2) * scale, rect.height / 2 - (SIM_HEIGHT / 2) * scale)
      .scale(scale || 1);
    svgSel.call(zoomBehavior.transform, t);

    return () => svgSel.on('.zoom', null);
  }, []);

  // --- node dragging ---
  useEffect(() => {
    const nodeEls = nodeElsRef.current;
    nodeEls.forEach((el, id) => {
      const datum = simNodes.find((n) => n.id === id);
      if (!datum) return;

      // d3-drag's default container is the dragged node's parentNode (node-layer),
      // which already sits inside the zoomed <g> — event.x/event.y come out via that
      // element's own screen CTM, i.e. already in data space. Do not invert again here.
      // Dropped nodes stay pinned where the analyst placed them — decluttering a crowded
      // cluster is the point of dragging here, not a physics toy that snaps back. The rest
      // of the graph still relaxes around the new fixed point as alpha decays back to 0.
      // simRef.current is read fresh inside each handler (not captured at effect-setup
      // time) so a StrictMode dev double-render can never leave a handler bound to a
      // stale, already-stopped simulation instance.
      const dragBehavior = d3drag()
        .on('start', (event) => {
          const simulation = simRef.current;
          if (!event.active && simulation) simulation.alphaTarget(0.25).restart();
          datum.fx = event.x;
          datum.fy = event.y;
        })
        .on('drag', (event) => {
          datum.fx = event.x;
          datum.fy = event.y;
        })
        .on('end', (event) => {
          const simulation = simRef.current;
          if (!event.active && simulation) simulation.alphaTarget(0);
        });

      select(el).call(dragBehavior);
    });

    return () => {
      nodeEls.forEach((el) => select(el).on('.drag', null));
    };
  }, [simNodes]);

  // --- traveling signal pulse along each edge touching a newly selected node ---
  useEffect(() => {
    if (selectedId && selectedId !== prevSelectedRef.current) {
      const origin = simNodes.find((n) => n.id === selectedId);
      if (origin) {
        const conns = connections.get(selectedId) || [];
        const next = conns
          .slice(0, SIGNAL_PULSE_CAP)
          .map((c, i) => {
            const target = simNodes.find((n) => n.id === c.id);
            if (!target) return null;
            return {
              key: selectedId + '>' + c.id + '>' + Date.now(),
              x1: origin.x,
              y1: origin.y,
              x2: target.x,
              y2: target.y,
              delayMs: Math.min(i * 45, 320),
            };
          })
          .filter(Boolean);
        setPulses(next);
      }
    }
    prevSelectedRef.current = selectedId;
  }, [selectedId, simNodes, connections]);

  useImperativeHandle(ref, () => ({
    zoomIn() {
      select(svgRef.current).transition().duration(180).call(zoomBehaviorRef.current.scaleBy, 1.35);
    },
    zoomOut() {
      select(svgRef.current).transition().duration(180).call(zoomBehaviorRef.current.scaleBy, 1 / 1.35);
    },
    resetView() {
      const rect = svgRef.current.getBoundingClientRect();
      const scale = Math.min(rect.width / SIM_WIDTH, rect.height / SIM_HEIGHT) * 0.92;
      const t = zoomIdentity
        .translate(rect.width / 2 - (SIM_WIDTH / 2) * scale, rect.height / 2 - (SIM_HEIGHT / 2) * scale)
        .scale(scale || 1);
      select(svgRef.current).transition().duration(400).call(zoomBehaviorRef.current.transform, t);
    },
    focusOnNode(id) {
      const datum = simNodes.find((n) => n.id === id);
      if (!datum) return;
      const rect = svgRef.current.getBoundingClientRect();
      const targetScale = Math.max(transformRef.current.k, 1.6);
      const t = zoomIdentity
        .translate(rect.width / 2 - datum.x * targetScale, rect.height / 2 - datum.y * targetScale)
        .scale(targetScale);
      select(svgRef.current).transition().duration(420).call(zoomBehaviorRef.current.transform, t);
    },
    focusNodeEl(id) {
      nodeElsRef.current.get(id)?.focus();
    },
    exportPNG() {
      const svgEl = svgRef.current;
      const rect = svgEl.getBoundingClientRect();
      const clone = svgEl.cloneNode(true);
      clone.setAttribute('width', String(rect.width));
      clone.setAttribute('height', String(rect.height));
      const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
      styleEl.textContent = EXPORT_STYLE;
      clone.insertBefore(styleEl, clone.firstChild);

      const svgString = new XMLSerializer().serializeToString(clone);
      const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = rect.width * 2;
        canvas.height = rect.height * 2;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#070b11';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        canvas.toBlob((blob) => {
          const link = document.createElement('a');
          link.download = 'network-graph-' + Date.now() + '.png';
          link.href = URL.createObjectURL(blob);
          link.click();
          setTimeout(() => URL.revokeObjectURL(link.href), 2000);
        });
      };
      img.src = url;
    },
  }));

  const handleBackgroundClick = (event) => {
    if (event.target === svgRef.current || event.target === zoomLayerRef.current) {
      onSelectNode(null);
    }
  };

  return (
    <div className="network-canvas" ref={containerRef}>
      <svg
        ref={svgRef}
        className="network-svg"
        role="group"
        aria-label="Entity relationship graph"
        onClick={handleBackgroundClick}
      >
        <defs>
          <filter id="glow-red" x="-120%" y="-120%" width="340%" height="340%">
            <feGaussianBlur stdDeviation="4.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="glow-gold" x="-120%" y="-120%" width="340%" height="340%">
            <feGaussianBlur stdDeviation="4.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <pattern id="tactical-grid" width={GRID_STEP} height={GRID_STEP} patternUnits="userSpaceOnUse">
            <path className="tactical-grid-line" d={'M ' + GRID_STEP + ' 0 L 0 0 0 ' + GRID_STEP} fill="none" />
          </pattern>
        </defs>
        <g ref={zoomLayerRef} className="zoom-layer">
          <rect
            className="tactical-grid-bg"
            x={-4000}
            y={-4000}
            width={SIM_WIDTH + 8000}
            height={SIM_HEIGHT + 8000}
            fill="url(#tactical-grid)"
          />
          <g className="edge-layer">
            {edges.map((e, i) => {
              const touchesSelected = selectedId && (e.source === selectedId || e.target === selectedId);
              const dimmed = Boolean(selectedId) && !touchesSelected;
              const active = Boolean(touchesSelected);
              const opacity = active
                ? Math.min(0.85, 0.3 + e.strength * 0.5)
                : dimmed
                  ? 0.11
                  : 0.1 + e.strength * 0.32;
              const flagInfo = edgeFlagInfo[i];
              const flowClass = flagInfo.flagged
                ? flagInfo.toward === 'source'
                  ? ' edge--flagged edge--flow-rev'
                  : ' edge--flagged edge--flow-fwd'
                : '';
              return (
                <line
                  key={e.source + '|' + e.target + '|' + i}
                  ref={(el) => {
                    edgeElsRef.current[i] = el;
                  }}
                  className={'edge' + (active ? ' edge--active' : '') + (dimmed ? ' edge--dim' : '') + flowClass}
                  style={{ '--edge-o': opacity }}
                />
              );
            })}
          </g>
          <g className="signal-layer" aria-hidden="true">
            {pulses.map((p) => (
              <circle
                key={p.key}
                className="signal-pulse"
                r={2.6}
                style={{
                  '--x1': p.x1 + 'px',
                  '--y1': p.y1 + 'px',
                  '--x2': p.x2 + 'px',
                  '--y2': p.y2 + 'px',
                  animationDelay: p.delayMs + 'ms',
                }}
                onAnimationEnd={() => setPulses((prev) => prev.filter((q) => q.key !== p.key))}
              />
            ))}
          </g>
          <g className="node-layer">
            {nodes.map((n, i) => {
              const isSelected = n.id === selectedId;
              const isFocused = n.id === focusedId;
              const isHovered = n.id === hoveredId;
              const isConnected = connectedSet ? connectedSet.has(n.id) : true;
              const r = radiusFor(n.degree);
              const flagged = Boolean(n.flag);
              const labelVisible = showLabels || flagged || isHovered || (connectedSet ? connectedSet.has(n.id) : false);
              return (
                <g
                  key={n.id}
                  ref={(el) => {
                    if (el) nodeElsRef.current.set(n.id, el);
                    else nodeElsRef.current.delete(n.id);
                  }}
                  className={
                    'node' +
                    (flagged ? ' node--' + n.flag : '') +
                    (isSelected ? ' node--selected' : '') +
                    (!isConnected ? ' node--dim' : '')
                  }
                  tabIndex={isFocused ? 0 : -1}
                  role="button"
                  aria-pressed={isSelected}
                  aria-label={
                    n.name + ', ' + n.id + ', risk ' + n.risk.toFixed(2) + (flagged ? ', flagged ' + n.flag : '')
                  }
                  onFocus={() => onNodeFocus(n.id)}
                  onMouseEnter={() => setHoveredId(n.id)}
                  onMouseLeave={() => setHoveredId((h) => (h === n.id ? null : h))}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelectNode(n.id);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelectNode(n.id);
                    }
                  }}
                >
                  <g className="node-visual" style={{ animationDelay: Math.min(i * 10, 500) + 'ms' }}>
                    {flagged && (
                      <circle
                        className={'node-glow node-glow--' + n.flag}
                        r={r + 6}
                        filter={'url(#glow-' + n.flag + ')'}
                        style={{ animationDelay: (i % 5) * 0.31 + 's' }}
                      />
                    )}
                    {flagged && (
                      <circle
                        className={'node-ping node-ping--' + n.flag}
                        r={r}
                        style={{ animationDelay: (i % 3) * 0.7 + 's' }}
                      />
                    )}
                    {isSelected && <circle className="node-ring" r={r + 5} />}
                    <circle
                      className="node-fill"
                      r={r}
                      style={{ animationDelay: (i % 11) * 0.43 + 's' }}
                    />
                    <text
                      className={'node-text' + (labelVisible ? ' node-text--visible' : '')}
                      x={r + 5}
                      y={3}
                    >
                      {n.name}
                    </text>
                  </g>
                </g>
              );
            })}
          </g>
        </g>
      </svg>
      <div className="radar-sweep" aria-hidden="true" />
      <div className="canvas-vignette" aria-hidden="true" />
    </div>
  );
});

export default NetworkGraph;
