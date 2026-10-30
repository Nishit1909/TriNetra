"""Layer 2 — GraphSAGE link predictor (PyTorch Geometric).

The GNN is trained on whatever person graph it is given and scores candidate
person pairs with ``sigmoid(z_u · z_v)``.  It is deliberately **inductive**:
node inputs are purely structural (log-degree, degree centrality, PageRank,
clustering coefficient, weighted degree), never node ids, so the same
architecture can be trained on any graph size.

Graceful degradation (important for the backend team)
----------------------------------------------------
* If ``torch`` is not installed → :func:`gnn_available` is ``False`` and every
  entry point returns ``None`` with a warning; the heuristic layer remains the
  surfaced method.
* If ``torch`` is installed but ``torch_geometric`` is not → a pure-torch
  mean-aggregation SAGE layer (mathematically the same as ``SAGEConv`` with
  ``aggr="mean"``) is used instead, so the GNN still runs.
* Graphs with fewer than ``MIN_NODES`` nodes or ``MIN_EDGES`` edges → skipped
  (``None``), because there is not enough structure to train on.

Training is single-threaded CPU friendly: ~1–3 s for a 150-node graph, a few
seconds for 500 nodes.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

MIN_NODES = 8
MIN_EDGES = 5
DEFAULT_EPOCHS = 150
DEFAULT_HIDDEN = 32

try:  # torch is optional at import time
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    _TORCH_OK = True
except Exception:  # pragma: no cover - depends on environment
    torch = None  # type: ignore
    _TORCH_OK = False

try:
    from torch_geometric.nn import SAGEConv as _PygSAGEConv  # type: ignore

    _PYG_OK = _TORCH_OK
except Exception:  # pragma: no cover
    _PygSAGEConv = None
    _PYG_OK = False


def gnn_available() -> bool:
    """True when a GraphSAGE model can be trained in this environment."""
    return _TORCH_OK


def gnn_backend() -> str:
    """``"torch_geometric"``, ``"pure_torch"`` or ``"unavailable"``."""
    if _PYG_OK:
        return "torch_geometric"
    if _TORCH_OK:
        return "pure_torch"
    return "unavailable"


# --------------------------------------------------------------------------- #
# Structural node features (inductive, size-agnostic)
# --------------------------------------------------------------------------- #
def structural_features(pg: nx.Graph, nodes: Sequence[str]) -> np.ndarray:
    """5 standardised structural features per node (see module docstring)."""
    n = len(nodes)
    if n == 0:
        return np.zeros((0, 5), dtype=np.float32)
    deg = dict(pg.degree())
    wdeg = dict(pg.degree(weight="weight"))
    dc = nx.degree_centrality(pg) if n > 1 else {v: 0.0 for v in nodes}
    pr = nx.pagerank(pg, weight="weight") if pg.number_of_edges() else {v: 1.0 / n for v in nodes}
    cc = nx.clustering(pg) if pg.number_of_edges() else {v: 0.0 for v in nodes}
    X = np.array(
        [[np.log1p(deg.get(v, 0)), dc.get(v, 0.0), pr.get(v, 0.0) * n, cc.get(v, 0.0), np.log1p(wdeg.get(v, 0.0))] for v in nodes],
        dtype=np.float32,
    )
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
if _TORCH_OK:

    class _MeanSAGEConv(nn.Module):
        """Pure-torch equivalent of ``torch_geometric.nn.SAGEConv(aggr="mean")``."""

        def __init__(self, in_dim: int, out_dim: int):
            super().__init__()
            self.lin_self = nn.Linear(in_dim, out_dim)
            self.lin_neigh = nn.Linear(in_dim, out_dim, bias=False)

        def forward(self, x, edge_index):
            src, dst = edge_index
            n = x.size(0)
            agg = torch.zeros_like(x).index_add_(0, dst, x[src])
            cnt = torch.zeros(n, 1, device=x.device).index_add_(0, dst, torch.ones(src.size(0), 1, device=x.device))
            agg = agg / cnt.clamp(min=1.0)
            return self.lin_self(x) + self.lin_neigh(agg)

    class GraphSAGELinkPredictor(nn.Module):
        """Two-layer GraphSAGE encoder + dot-product link decoder."""

        def __init__(self, in_dim: int, hidden_dim: int = DEFAULT_HIDDEN, dropout: float = 0.2):
            super().__init__()
            Conv = _PygSAGEConv if _PYG_OK else _MeanSAGEConv
            self.conv1 = Conv(in_dim, hidden_dim)
            self.conv2 = Conv(hidden_dim, hidden_dim)
            self.dropout = dropout

        def encode(self, x, edge_index):
            h = F.relu(self.conv1(x, edge_index))
            h = F.dropout(h, p=self.dropout, training=self.training)
            return self.conv2(h, edge_index)

        @staticmethod
        def decode(z, pairs):
            return (z[pairs[0]] * z[pairs[1]]).sum(dim=-1)


@dataclass
class TrainedGNN:
    """A trained GraphSAGE link predictor bound to a node index."""

    model: object
    node_index: Dict[str, int]
    nodes: List[str]
    edge_index: object  # torch.LongTensor [2, 2E] of message-passing edges
    x: object  # torch.FloatTensor node features
    backend: str
    epochs: int
    final_loss: float
    warnings: List[str] = field(default_factory=list)


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    if _TORCH_OK:
        torch.manual_seed(seed)


def _to_edge_index(pg: nx.Graph, node_index: Dict[str, int]):
    src, dst = [], []
    for u, v in pg.edges():
        i, j = node_index[u], node_index[v]
        src += [i, j]
        dst += [j, i]
    return torch.tensor([src, dst], dtype=torch.long) if src else torch.zeros((2, 0), dtype=torch.long)


def _negative_sample(pg: nx.Graph, node_index: Dict[str, int], num: int, rng: random.Random):
    n = len(node_index)
    nodes = list(node_index.keys())
    src, dst = [], []
    tries = 0
    while len(src) < num and tries < num * 20:
        tries += 1
        a, b = rng.randrange(n), rng.randrange(n)
        if a == b or pg.has_edge(nodes[a], nodes[b]):
            continue
        src.append(a)
        dst.append(b)
    return torch.tensor([src, dst], dtype=torch.long)


def train_gnn_link_predictor(
    pg: nx.Graph,
    epochs: int = DEFAULT_EPOCHS,
    hidden_dim: int = DEFAULT_HIDDEN,
    lr: float = 0.01,
    seed: int = 42,
) -> Optional[TrainedGNN]:
    """Train GraphSAGE for link prediction on ``pg`` (a projected person graph).

    Returns ``None`` (with a logged warning) when torch is unavailable or the
    graph is too small to train on.  Never raises for environmental reasons —
    the caller always has the heuristic fallback.
    """
    warnings: List[str] = []
    if not _TORCH_OK:
        logger.warning("GNN skipped: torch is not installed (heuristic fallback will be used).")
        return None
    if pg.number_of_nodes() < MIN_NODES or pg.number_of_edges() < MIN_EDGES:
        logger.warning(
            "GNN skipped: graph too small (%d nodes, %d edges; need >= %d nodes and >= %d edges).",
            pg.number_of_nodes(), pg.number_of_edges(), MIN_NODES, MIN_EDGES,
        )
        return None

    _seed_everything(seed)
    rng = random.Random(seed)
    nodes = sorted(pg.nodes())
    node_index = {v: i for i, v in enumerate(nodes)}
    x = torch.tensor(structural_features(pg, nodes))
    edge_index = _to_edge_index(pg, node_index)
    pos = torch.tensor([[node_index[u] for u, _ in pg.edges()], [node_index[v] for _, v in pg.edges()]], dtype=torch.long)

    model = GraphSAGELinkPredictor(x.size(1), hidden_dim)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=5e-4)
    torch.set_num_threads(max(1, torch.get_num_threads()))
    loss_val = float("nan")
    model.train()
    for _ in range(epochs):
        opt.zero_grad()
        z = model.encode(x, edge_index)
        neg = _negative_sample(pg, node_index, pos.size(1), rng)
        pos_logit = model.decode(z, pos)
        neg_logit = model.decode(z, neg)
        logits = torch.cat([pos_logit, neg_logit])
        labels = torch.cat([torch.ones_like(pos_logit), torch.zeros_like(neg_logit)])
        loss = F.binary_cross_entropy_with_logits(logits, labels)
        loss.backward()
        opt.step()
        loss_val = float(loss.item())
    if not np.isfinite(loss_val):
        warnings.append("GNN training loss is not finite; predictions should be treated as degraded.")
        logger.warning(warnings[-1])
    model.eval()
    return TrainedGNN(model, node_index, nodes, edge_index, x, gnn_backend(), epochs, loss_val, warnings)


def gnn_pair_scores(trained: TrainedGNN, pairs: Sequence[Tuple[str, str]]) -> Dict[Tuple[str, str], float]:
    """Sigmoid link score for each candidate pair using the trained encoder."""
    if trained is None or not pairs:
        return {}
    idx = trained.node_index
    valid = [(a, b) for a, b in pairs if a in idx and b in idx]
    if not valid:
        return {}
    with torch.no_grad():
        z = trained.model.encode(trained.x, trained.edge_index)
        t = torch.tensor([[idx[a] for a, _ in valid], [idx[b] for _, b in valid]], dtype=torch.long)
        s = torch.sigmoid(trained.model.decode(z, t)).cpu().numpy()
    scores = {pair: float(v) for pair, v in zip(valid, s)}
    if not np.all(np.isfinite(list(scores.values()))):
        logger.warning("GNN produced non-finite scores; replacing with 0.")
        scores = {k: (v if np.isfinite(v) else 0.0) for k, v in scores.items()}
    return scores
