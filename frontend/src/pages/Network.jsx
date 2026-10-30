import { useCallback, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import Panel from '../components/Panel';
import NetworkGraph from '../components/network/NetworkGraph';
import EntityInspector from '../components/network/EntityInspector';
import GraphToolbar from '../components/network/GraphToolbar';
import GraphLegend from '../components/network/GraphLegend';
import GraphSearch from '../components/network/GraphSearch';
import { buildNetwork } from '../data/networkMock';
import './Network.css';

export default function Network() {
  const [searchParams] = useSearchParams();
  const network = useMemo(() => buildNetwork(), []);
  const { nodes, edges, byId, connections, communities } = network;

  const communityLabel = useMemo(() => {
    const map = new Map(communities.map((c) => [c.id, c.label]));
    return map;
  }, [communities]);

  const orderedNodes = useMemo(() => [...nodes].sort((a, b) => b.degree - a.degree), [nodes]);

  const initialSelection = searchParams.get('entity');
  const [selectedId, setSelectedId] = useState(
    initialSelection && byId.has(initialSelection) ? initialSelection : null,
  );
  const [focusedId, setFocusedId] = useState(orderedNodes[0]?.id ?? null);
  const [showLabels, setShowLabels] = useState(false);
  const [announcement, setAnnouncement] = useState('');

  const graphRef = useRef(null);
  const wrapRef = useRef(null);

  const flaggedCount = useMemo(() => nodes.filter((n) => n.flag).length, [nodes]);

  const goToEntity = useCallback(
    (id) => {
      if (!id || !byId.has(id)) return;
      setSelectedId(id);
      setFocusedId(id);
      graphRef.current?.focusOnNode(id);
      graphRef.current?.focusNodeEl(id);
      setAnnouncement(byId.get(id).name + ' selected');
    },
    [byId],
  );

  const handleSelectNode = useCallback(
    (id) => {
      setSelectedId(id);
      if (id) setAnnouncement(byId.get(id)?.name + ' selected');
      else setAnnouncement('Selection cleared');
    },
    [byId],
  );

  const handleNodeFocus = useCallback((id) => setFocusedId(id), []);

  const handleKeyDown = (event) => {
    const idx = orderedNodes.findIndex((n) => n.id === focusedId);
    let nextIdx = null;

    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIdx = (idx + 1 + orderedNodes.length) % orderedNodes.length;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIdx = (idx - 1 + orderedNodes.length) % orderedNodes.length;
    } else if (event.key === 'Escape') {
      setSelectedId(null);
      setAnnouncement('Selection cleared');
      return;
    } else {
      return;
    }

    event.preventDefault();
    const nextId = orderedNodes[nextIdx].id;
    setFocusedId(nextId);
    graphRef.current?.focusNodeEl(nextId);
  };

  const selectedNode = selectedId ? byId.get(selectedId) : null;
  const selectedConnections = selectedId ? connections.get(selectedId) || [] : [];

  return (
    <div className="network-page">
      <h1 className="sr-only">Network — relationship graph workspace</h1>
      <div className="sr-only" role="status" aria-live="polite">{announcement}</div>

      <div className="network-topbar">
        <GraphSearch nodes={nodes} onSelect={goToEntity} />
        <div className="mono network-stats dim">
          {nodes.length} entities · {edges.length} links · <span className="network-stats-flag">{flaggedCount} flagged</span>
        </div>
      </div>

      <div className="network-body">
        <Panel label="entity inspector" className="network-inspector-panel">
          <EntityInspector
            node={selectedNode}
            connections={selectedConnections}
            byId={byId}
            communityLabel={selectedNode ? communityLabel.get(selectedNode.community) : null}
            onFocusEntity={goToEntity}
          />
        </Panel>

        <Panel
          label="relationship graph"
          meta={selectedNode ? selectedNode.id + ' focused' : 'force-directed'}
          className="network-graph-panel"
        >
          <div
            className="network-graph-wrap"
            ref={wrapRef}
            onKeyDown={handleKeyDown}
          >
            <NetworkGraph
              ref={graphRef}
              nodes={nodes}
              edges={edges}
              connections={connections}
              selectedId={selectedId}
              focusedId={focusedId}
              onSelectNode={handleSelectNode}
              onNodeFocus={handleNodeFocus}
              showLabels={showLabels}
            />
            <GraphToolbar
              showLabels={showLabels}
              onToggleLabels={() => setShowLabels((v) => !v)}
              onZoomIn={() => graphRef.current?.zoomIn()}
              onZoomOut={() => graphRef.current?.zoomOut()}
              onReset={() => graphRef.current?.resetView()}
              onExport={() => graphRef.current?.exportPNG()}
            />
            <GraphLegend />
          </div>
        </Panel>
      </div>
    </div>
  );
}
