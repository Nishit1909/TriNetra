"""Benchmark link-prediction methods for run_case_analysis on real covert networks.

Usage: python scripts/benchmark_link_methods.py cases/benchmarks/source cases/noordin results/link_methods

Three tests (protocol fixed before results were seen):
  A. Noordin hide-and-recover: features from the 9 non-communication layers only; label = communication tie.
  B. Predict ahead on time-sliced networks: graph up to period t -> score unconnected pairs -> label = pair
     first linked in period t+1. Earlier transitions = SELECTION, the last transition per network = CONFIRMATION.
  C. Edge hiding on single-layer criminal/terror networks: hide 20% of links (30 repeats), score the remaining
     unconnected pairs, label = hidden link. Networks split alphabetically-interleaved into SELECTION and
     CONFIRMATION groups so a winner chosen on one group is checked on networks it never saw.

Metrics per evaluation: average precision (AP), precision@10, and lift (AP / base rate). Methods are
compared by mean AP lift (base rates differ across networks). All randomness is seeded.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import rdata
from sklearn.metrics import average_precision_score

SRC, NOORDIN, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
RNG_SEED = 7


# ------------------------------------------------------------------ data loading (pure-python R parser)
def _py(x):
    t = x.info.type.name
    if t in ("REAL", "INT", "LGL"):
        return np.asarray(x.value)
    if t == "STR":
        return [s.value.decode() if s.value is not None else None for s in x.value]
    if t == "VEC":
        return [_py(e) for e in x.value]
    return t


def load_graphs(path: Path) -> list[tuple[str, nx.Graph]]:
    obj = rdata.parser.parse_file(str(path)).object.value[0]
    gs = obj.value if obj.info.type.name == "VEC" and obj.value and obj.value[0].info.type.name == "VEC" \
        and len(obj.value[0].value) > 8 else [obj]
    out = []
    for g in gs:
        el = g.value
        n = int(_py(el[0])[0])
        fr, to = _py(el[2]).astype(int), _py(el[3]).astype(int)
        a = _py(el[8])
        name = a[1][0][0] if a[1] and a[1][0] else path.stem
        G = nx.Graph()
        G.add_nodes_from(range(n))
        G.add_edges_from((int(u), int(v)) for u, v in zip(fr, to) if u != v)
        out.append((name, G))
    return out


# ------------------------------------------------------------------ scoring methods (unweighted structure)
def scores(G: nx.Graph, pairs: list[tuple[int, int]]) -> dict[str, np.ndarray]:
    deg = dict(G.degree())
    nbr = {v: set(G[v]) for v in G}
    nodes = list(G)
    idx = {v: i for i, v in enumerate(nodes)}
    A = nx.to_numpy_array(G, nodelist=nodes)
    A2 = A @ A
    A3 = A2 @ A
    # Katz truncated at length 3, beta = 0.05
    katz = 0.05 * A + 0.05 ** 2 * A2 + 0.05 ** 3 * A3
    lp = A2 + 0.01 * A3                                        # local path index (Lu et al.)
    # personalised PageRank, symmetrised (alpha 0.85)
    ppr = np.zeros_like(A)
    if G.number_of_edges():
        deg_v = A.sum(1)
        P = np.divide(A, deg_v[:, None], out=np.zeros_like(A), where=deg_v[:, None] > 0)
        M = np.linalg.inv(np.eye(len(nodes)) - 0.85 * P.T)
        ppr = 0.15 * M
        ppr = ppr + ppr.T
    out = {k: [] for k in ["common_neighbours", "adamic_adar", "resource_allocation", "jaccard",
                           "preferential_attachment", "local_path", "katz3", "personalised_pagerank"]}
    for a, b in pairs:
        cn = nbr[a] & nbr[b]
        out["common_neighbours"].append(len(cn))
        out["adamic_adar"].append(sum(1 / math.log(deg[z]) for z in cn if deg[z] > 1))
        out["resource_allocation"].append(sum(1 / deg[z] for z in cn if deg[z] > 0))
        un = nbr[a] | nbr[b]
        out["jaccard"].append(len(cn) / len(un) if un else 0.0)
        out["preferential_attachment"].append(deg[a] * deg[b])
        i, j = idx[a], idx[b]
        out["local_path"].append(lp[i, j])
        out["katz3"].append(katz[i, j])
        out["personalised_pagerank"].append(ppr[i, j])
    return {k: np.asarray(v, dtype=float) for k, v in out.items()}


def evaluate(y: np.ndarray, s: np.ndarray) -> dict:
    base = y.mean()
    order = np.argsort(-s, kind="stable")
    th = s[order[min(9, len(s) - 1)]]
    above, tie = s > th, s == th
    p10 = (y[above].sum() + (10 - above.sum()) * (y[tie].mean() if tie.any() else 0)) / 10
    ap = average_precision_score(y, s) if y.sum() else float("nan")
    return {"ap": ap, "p10": p10, "base": base, "ap_lift": ap / base if base else float("nan"), "positives": int(y.sum())}


# ------------------------------------------------------------------ test B: predict ahead
TEMPORAL = {  # file -> slice-name filter (cumulative period snapshots, in order)
    "covert_1": "17NOV_GREECE_19", "covert_4": "AE_INDO_", "covert_6": "BALIBOMBING2002_", "covert_11": "CHRISTMASEVEINDONESIA_",
    "covert_20": "HAMBURG_", "covert_30": "MADRID_", "covert_37": "PHILBOMB_2000_", "covert_10": "CAVIAR",
}


def test_b():
    rows = []
    for f, pref in TEMPORAL.items():
        gs = [(n, g) for n, g in load_graphs(SRC / f"{f}.rda") if n.startswith(pref) and "2MODE" not in n and "FULL" not in n]
        if f == "covert_10":   # Caviar phases are per-period, not cumulative: build cumulative snapshots
            gs = sorted(gs, key=lambda t: int(t[0].replace("CAVIAR", "")))
            cum, out = nx.Graph(), []
            for n, g in gs:
                cum = nx.compose(cum, g)
                out.append((n, cum.copy()))
            gs = out
        trans = []
        for (n0, g0), (n1, g1) in zip(gs, gs[1:]):
            active = {v for v in g0 if g0.degree(v) > 0}
            new = {tuple(sorted(e)) for e in g1.edges() if not g0.has_edge(*e) and e[0] in active and e[1] in active}
            if len(new) < 3:
                continue
            pairs = [(a, b) for a in sorted(active) for b in sorted(active) if a < b and not g0.has_edge(a, b)]
            y = np.array([int(p in new) for p in pairs])
            trans.append((n0, n1, g0.subgraph(active).copy(), pairs, y))
        for k, (n0, n1, g, pairs, y) in enumerate(trans):
            sc = scores(g, pairs)
            role = "confirmation" if k == len(trans) - 1 else "selection"
            for m, s in sc.items():
                rows.append({"test": "B_predict_ahead", "network": f, "transition": f"{n0}->{n1}", "role": role, "method": m, **evaluate(y, s)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ test C: edge hiding
STATIC = ["covert_2", "covert_10", "covert_12", "covert_13", "covert_15", "covert_16", "covert_21", "covert_24", "covert_26",
          "covert_28", "covert_29", "covert_31", "covert_32", "covert_39", "covert_41", "covert_46", "covert_47"]


def pick_static(f):
    gs = load_graphs(SRC / f"{f}.rda")
    if f == "covert_10":
        return [g for n, g in gs if n == "CAVIAR_FULL"][0]
    if f == "covert_2":
        return [g for n, g in gs if n == "9_11_HIJACKERS_ASSOCIATES"][0]
    return gs[0][1]


def test_c(repeats=30, frac=0.2):
    rows = []
    for k, f in enumerate(STATIC):
        G0 = pick_static(f)
        G0 = G0.subgraph([v for v in G0 if G0.degree(v) > 0]).copy()
        role = "selection" if k % 2 == 0 else "confirmation"
        edges = sorted(tuple(sorted(e)) for e in G0.edges())
        rng = np.random.default_rng(RNG_SEED + k)
        per = {}
        for r in range(repeats):
            hide = set(map(tuple, np.array(edges)[rng.choice(len(edges), size=max(1, int(frac * len(edges))), replace=False)]))
            G = G0.copy()
            G.remove_edges_from(hide)
            nodes = sorted(G)
            pairs = [(a, b) for i, a in enumerate(nodes) for b in nodes[i + 1:] if not G.has_edge(a, b)]
            y = np.array([int(p in hide) for p in pairs])
            for m, s in scores(G, pairs).items():
                per.setdefault(m, []).append(evaluate(y, s))
        for m, evs in per.items():
            rows.append({"test": "C_edge_hiding", "network": f, "transition": f"{repeats}x hide {int(frac*100)}%", "role": role,
                         "method": m, "nodes": G0.number_of_nodes(), "edges": G0.number_of_edges(),
                         **{k2: float(np.nanmean([e[k2] for e in evs])) for k2 in ["ap", "p10", "base", "ap_lift"]},
                         "positives": int(np.mean([e["positives"] for e in evs]))})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ test A: Noordin hide-and-recover (direct ties vs shared contacts)
def test_a(repeats=30):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from analysis_model.run_case_analysis import _edge_strength, _graph, _validate, load_weights
    W = load_weights(Path(__file__).resolve().parents[1] / "analysis_model" / "weights" / "v1.json")
    persons = pd.read_csv(NOORDIN / "persons.csv")
    rel = pd.read_csv(NOORDIN / "relationships.csv")
    feats = rel[rel.layer != "communications"]
    edges = pd.DataFrame({"person_a": feats.person_a, "person_b": feats.person_b, "relationship_type": feats.layer.str.upper(),
                          "is_inferred": False, "weight": 1.0})
    warn = []
    p, e = _validate(persons, edges, "observed_only", W, warn)
    s = _edge_strength(p, e, W, warn)
    G, _ = _graph(p, s, W)
    ids = list(persons.person_id)
    pairs_all = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
    lab = {tuple(sorted(x)) for x in zip(rel[rel.layer == "communications"].person_a, rel[rel.layer == "communications"].person_b)}
    y_all = np.array([int(pq in lab) for pq in pairs_all])
    direct = s.groupby(["a", "b"]).strength.sum().to_dict()
    ntypes = s.groupby(["a", "b"]).type.nunique().to_dict()
    Gi = nx.relabel_nodes(G, {v: i for i, v in enumerate(ids)})
    pi = [(ids.index(a), ids.index(b)) for a, b in pairs_all]
    sc = scores(Gi, pi)
    aa = sc["adamic_adar"]
    ra = sc["resource_allocation"]
    d = np.array([direct.get(pq, 0.0) for pq in pairs_all])
    nt = np.array([ntypes.get(pq, 0) for pq in pairs_all])
    methods = {
        "direct_tie_strength_v1": d + 1e-3 * aa / (1 + aa.max()),
        "tie_type_count": nt + 1e-3 * aa / (1 + aa.max()),
        "adamic_adar": aa, "resource_allocation": ra, "common_neighbours": sc["common_neighbours"],
        "direct_v1_plus_aa": d / (d.max() or 1) + 0.25 * aa / (aa.max() or 1),
        "direct_v1_plus_ra": d / (d.max() or 1) + 0.25 * ra / (ra.max() or 1),
    }
    # selection / confirmation: repeated stratified halves of pairs (no training except the 0.25 mix, fixed a priori)
    rng = np.random.default_rng(RNG_SEED)
    rows = []
    for r in range(repeats):
        perm = rng.permutation(len(pairs_all))
        half = len(perm) // 2
        for role, ix in (("selection", perm[:half]), ("confirmation", perm[half:])):
            for m, s_ in methods.items():
                rows.append({"test": "A_noordin_hide_recover", "network": "covert_34", "transition": f"rep{r}", "role": role,
                             "method": m, **evaluate(y_all[ix], s_[ix])})
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame, test: str) -> pd.DataFrame:
    d = df[df.test == test]
    g = d.groupby(["role", "method"]).agg(mean_ap_lift=("ap_lift", "mean"), mean_ap=("ap", "mean"), mean_p10=("p10", "mean"),
                                          evaluations=("ap", "size")).reset_index()
    wins = d.loc[d.groupby(["role", "network", "transition"]).ap_lift.idxmax()].groupby(["role", "method"]).size()
    g["wins"] = [int(wins.get((r, m), 0)) for r, m in zip(g.role, g.method)]
    return g.sort_values(["role", "mean_ap_lift"], ascending=[False, False])


if __name__ == "__main__":
    a, b, c = test_a(), test_b(), test_c()
    allr = pd.concat([a, b, c], ignore_index=True)
    allr.to_csv(OUT / "all_evaluations.csv", index=False)
    summary = {}
    for t in ["A_noordin_hide_recover", "B_predict_ahead", "C_edge_hiding"]:
        s = summarise(allr, t)
        s.to_csv(OUT / f"summary_{t}.csv", index=False)
        summary[t] = s
        print(f"\n===== {t}\n", s.round(3).to_string(index=False))
    nets = allr.groupby("test").network.nunique().to_dict()
    evals = allr.groupby(["test", "role"]).transition.nunique().to_dict()
    (OUT / "run_info.json").write_text(json.dumps({"networks_per_test": nets, "seed": RNG_SEED}, indent=1))
    print("\nnetworks per test:", nets)
