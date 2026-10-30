import { useEffect, useMemo, useRef } from 'react';
import ForceGraph3D, { type ForceGraphMethods } from 'react-force-graph-3d';
import SpriteText from 'three-spritetext';
import { DoubleSide, Group, Mesh, MeshBasicMaterial, RingGeometry, SphereGeometry, type Material, type Object3D } from 'three';
import type { GraphEdge, GraphNode } from '../../api/types';
import { displayColor, edgeColor, freshLayout, pulse } from './graph-utils';
import { tierMeta } from '../../utils/format';
import { forceX, forceY, forceZ } from 'd3-force-3d';

export type GraphCommand = { type: 'fit' | 'in' | 'out' | 'export' | 'focus'; id: number; nodeId?: string };

interface Props {
  data: { nodes: GraphNode[]; links: GraphEdge[] };
  width: number;
  height: number;
  selected: string;
  labels: boolean;
  reduced: boolean;
  onSelect: (n: GraphNode) => void;
  onEdge: (e: GraphEdge) => void;
  onFailure: () => void;
  command: GraphCommand;
  caseId: string;
}

/** Animated parts of a node, updated every frame (pulsing halo, camera-facing ring). */
type Animated = { halo?: Mesh; ring?: Mesh; tier: GraphNode['tier']; phase: number };

const radius3d = (n: GraphNode) => 2.4 + Math.min(5, Math.sqrt(Math.max(0, n.pagerank || 0)) * 18) + (n.tier === 'key_figure' ? 1.2 : 0);

function disposeTree(root: Object3D) {
  root.traverse((obj) => {
    const mesh = obj as Mesh;
    mesh.geometry?.dispose();
    const mats = mesh.material ? (Array.isArray(mesh.material) ? mesh.material : [mesh.material]) : [];
    for (const m of mats as (Material & { map?: { dispose(): void } })[]) {
      m.map?.dispose();
      m.dispose();
    }
  });
}

export default function SpatialGraph({ data, width, height, selected, labels, reduced, onSelect, onEdge, onFailure, command, caseId }: Props) {
  const ref = useRef<ForceGraphMethods<GraphNode, GraphEdge>>();
  const animated = useRef(new Map<string, Animated>());

  // Fresh copies: the simulation mutates positions and link endpoints.
  const graphData = useMemo(
    () => freshLayout(data),
    [data],
  );

  // Node objects are rebuilt when the data, labels or selection change; old ones are disposed.
  const objects = useMemo(() => new Map<string, Group>(), [graphData, labels, selected]);
  useEffect(
    () => () => {
      for (const g of objects.values()) disposeTree(g);
      animated.current.clear();
    },
    [objects],
  );

  // Centring forces keep disconnected groups together so the fitted view stays close and readable.
  useEffect(() => {
    const g = ref.current;
    if (!g) return;
    g.d3Force('x', forceX(0).strength(0.07));
    g.d3Force('y', forceY(0).strength(0.07));
    g.d3Force('z', forceZ(0).strength(0.07));
    g.d3Force('charge')?.strength(-70).distanceMax(260);
    g.d3ReheatSimulation();
    // Fit early as well as when the simulation settles, so the first view is never zoomed far out.
    const timer = setTimeout(() => ref.current?.zoomToFit(reduced ? 0 : 500, 30), 1200);
    return () => clearTimeout(timer);
  }, [graphData, reduced]);

  // WebGL can be lost (GPU reset, too many contexts); fall back to 2D instead of a blank panel.
  useEffect(() => {
    const canvas = ref.current?.renderer().domElement;
    if (!canvas) return;
    const lost = (e: Event) => {
      e.preventDefault();
      onFailure();
    };
    canvas.addEventListener('webglcontextlost', lost);
    return () => canvas.removeEventListener('webglcontextlost', lost);
  }, [onFailure]);

  // Blinking: key figures pulse strongly (1.6 s), secondary figures breathe slowly (3.2 s).
  useEffect(() => {
    if (reduced) return;
    let raf = 0;
    const tick = (t: number) => {
      const camera = ref.current?.camera();
      for (const a of animated.current.values()) {
        if (a.halo) {
          const period = a.tier === 'key_figure' ? 1600 : 3200;
          const p = pulse(t + a.phase, period);
          const s = a.tier === 'key_figure' ? 1.35 + p * 1.1 : 1.3 + p * 0.35;
          a.halo.scale.setScalar(s);
          (a.halo.material as MeshBasicMaterial).opacity = a.tier === 'key_figure' ? 0.42 * (1 - p) + 0.06 : 0.12 + 0.12 * p;
        }
        if (a.ring && camera) a.ring.quaternion.copy(camera.quaternion);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reduced, objects]);

  useEffect(() => {
    const g = ref.current;
    if (!g || command.id === 0) return;
    const ms = reduced ? 0 : 500;
    if (command.type === 'fit') g.zoomToFit(ms, 60);
    if (command.type === 'in' || command.type === 'out') {
      const p = g.camera().position;
      const k = command.type === 'in' ? 0.75 : 1.3;
      g.cameraPosition({ x: p.x * k, y: p.y * k, z: p.z * k }, undefined, ms);
    }
    if (command.type === 'focus' && command.nodeId) {
      const n = graphData.nodes.find((x) => x.id === command.nodeId) as (GraphNode & { z?: number }) | undefined;
      if (n && n.x !== undefined) {
        const d = 90;
        const len = Math.hypot(n.x || 1, n.y || 1, n.z || 1);
        const r = 1 + d / len;
        g.cameraPosition({ x: (n.x || 0) * r, y: (n.y || 0) * r, z: (n.z || 0) * r }, { x: n.x || 0, y: n.y || 0, z: n.z || 0 }, ms);
      }
    }
    if (command.type === 'export') {
      g.renderer().render(g.scene(), g.camera());
      const a = document.createElement('a');
      a.download = `${caseId}-network-3d.png`;
      a.href = g.renderer().domElement.toDataURL('image/png');
      a.click();
    }
  }, [command, reduced, caseId, graphData]);

  return (
    <ForceGraph3D
      ref={ref}
      width={width}
      height={height}
      graphData={graphData}
      backgroundColor="#070b14"
      showNavInfo={false}
      nodeLabel={(n) => `${n.label} · ${tierMeta(n.tier).label}`}
      linkLabel={() => ''}
      rendererConfig={{ antialias: true, alpha: false, preserveDrawingBuffer: true }}
      controlType="orbit"
      cooldownTicks={reduced ? 0 : 90}
      warmupTicks={70}
      onNodeClick={onSelect}
      onLinkClick={onEdge}
      nodeVal={(n) => 3 + Math.sqrt(Math.max(0, n.pagerank || 0)) * 25}
      nodeThreeObject={(n) => {
        const cached = objects.get(n.id);
        if (cached) return cached;
        const g = new Group();
        const r = radius3d(n);
        const color = displayColor(n);
        g.add(new Mesh(new SphereGeometry(r, 20, 14), new MeshBasicMaterial({ color })));
        const anim: Animated = { tier: n.tier, phase: (n.id.length * 137) % 1600 };

        if (n.tier === 'key_figure' || n.tier === 'secondary_figure') {
          const halo = new Mesh(
            new SphereGeometry(r, 20, 14),
            new MeshBasicMaterial({ color, transparent: true, opacity: 0.25, depthWrite: false }),
          );
          halo.scale.setScalar(1.5);
          g.add(halo);
          anim.halo = halo;
        }
        if (n.tier === 'connector') {
          const ring = new Mesh(
            new RingGeometry(r * 1.45, r * 1.7, 40),
            new MeshBasicMaterial({ color: tierMeta('connector').color, side: DoubleSide, transparent: true, opacity: 0.9 }),
          );
          g.add(ring);
          anim.ring = ring;
        }
        if (n.id === selected) {
          const sel = new Mesh(
            new RingGeometry(r * 2.0, r * 2.2, 48),
            new MeshBasicMaterial({ color: '#ffffff', side: DoubleSide, transparent: true, opacity: 0.85 }),
          );
          g.add(sel);
          anim.ring = anim.ring || sel;
        }
        if (labels) {
          const label = new SpriteText(n.label, 4.2, n.tier === 'neutral' ? '#cbd5e1' : color);
          label.position.y = -r - 4.5;
          label.backgroundColor = '#070b14cc';
          label.padding = 1.6;
          label.borderRadius = 1;
          g.add(label);
        }
        animated.current.set(n.id, anim);
        objects.set(n.id, g);
        return g;
      }}
      linkColor={edgeColor}
      linkOpacity={0.5}
      linkWidth={(e) => (e.kind === 'observed' ? 0.3 : 0.7)}
      linkCurvature={(e) => (e.kind === 'predicted' ? 0.15 : e.kind === 'inferred' ? -0.1 : 0)}
      linkDirectionalParticles={(e) => (!reduced && e.kind === 'predicted' ? 2 : 0)}
      linkDirectionalParticleWidth={0.9}
      linkDirectionalParticleSpeed={0.004}
      linkDirectionalParticleColor={edgeColor}
      onEngineStop={() => {
        if (!selected) ref.current?.zoomToFit(reduced ? 0 : 600, 30);
      }}
    />
  );
}
