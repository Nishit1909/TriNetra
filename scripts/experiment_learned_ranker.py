"""Can a learned ranker beat personalised PageRank at suggesting links in real covert networks?

Usage: python scripts/experiment_learned_ranker.py cases/benchmarks/source results/learned_ranker

Protocol (fixed before results were seen)
- Evaluation units: every predict-ahead transition (test B) and every edge-hiding repeat (test C, 10 repeats per
  network here) from scripts/benchmark_link_methods.py.
- Features per candidate pair, each converted to a percentile WITHIN its own evaluation unit so networks of
  different size are comparable: structural (CN, AA, RA, Jaccard, PA, Katz-3, local path, PPR, shortest-path
  distance, same Louvain community, min/max degree, min/max clustering) and, for predict-ahead only, temporal
  (new neighbours of a/b in the last period, common neighbours gained in the last period, degree growth).
- Leave-one-GROUP-out: networks sharing people (Jemaah Islamiyah family; 9/11 + Hamburg cell) form one group; models
  are trained only on OTHER groups and tested on the held-out group. Caviar appears in both tests and is held out jointly.
- Models: logistic regression (L2, balanced) and histogram gradient boosting, fixed hyper-parameters (no tuning
  on held-out networks). Baseline: personalised PageRank (the current method) and Adamic-Adar.
- Comparison: paired per-unit AP lift vs PPR, wins and a 95% bootstrap CI over units; also per network.
"""
from __future__ import annotations

import json
import math
import sys
import warnings
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
sys.argv = [sys.argv[0], str(SRC), str(ROOT / "cases" / "noordin"), str(OUT)]
sys.path.insert(0, str(ROOT / "scripts"))
import benchmark_link_methods as H  # noqa: E402
sys.path.insert(0, str(ROOT))
from analysis_model.link_features import FEATURES as STRUCT_FEATURES, pair_features  # noqa: E402

STRUCT = STRUCT_FEATURES
TEMPORAL = ["new_nbrs_min", "new_nbrs_max", "cn_gained", "deg_growth_min", "deg_growth_max"]
EDGE_HIDE_REPEATS = 10
# Networks that share people are held out TOGETHER (no training on overlapping actors when testing):
GROUPS = {
    "covert_4": "jemaah_islamiyah", "covert_6": "jemaah_islamiyah", "covert_11": "jemaah_islamiyah",
    "covert_26": "jemaah_islamiyah", "covert_37": "jemaah_islamiyah",
    "covert_2": "sept11_hamburg", "covert_20": "sept11_hamburg",
}


def features(G: nx.Graph, pairs, G_prev: nx.Graph | None = None) -> pd.DataFrame:
    f = pair_features(G, pairs)          # the SAME implementation the app uses (analysis_model/link_features.py)
    deg = dict(G.degree())
    if G_prev is not None:
        prev_n = {v: set(G_prev[v]) if v in G_prev else set() for v in G}
        new_n = {v: set(G[v]) - prev_n[v] for v in G}
        pdeg = {v: G_prev.degree(v) if v in G_prev else 0 for v in G}
        f["new_nbrs_min"] = [min(len(new_n[a]), len(new_n[b])) for a, b in pairs]
        f["new_nbrs_max"] = [max(len(new_n[a]), len(new_n[b])) for a, b in pairs]
        f["cn_gained"] = [len((set(G[a]) & set(G[b])) - (prev_n[a] & prev_n[b])) for a, b in pairs]
        f["deg_growth_min"] = [min(deg[a] - pdeg[a], deg[b] - pdeg[b]) for a, b in pairs]
        f["deg_growth_max"] = [max(deg[a] - pdeg[a], deg[b] - pdeg[b]) for a, b in pairs]
    return f


def to_percentiles(f: pd.DataFrame) -> pd.DataFrame:
    return f.rank(pct=True, method="average")


def build_units():
    units = []   # dicts: network, task, unit, X (percentiles), raw ppr, raw aa, y
    # B: predict ahead
    for f, pref in H.TEMPORAL.items():
        gs = [(n, g) for n, g in H.load_graphs(SRC / f"{f}.rda") if n.startswith(pref) and "2MODE" not in n and "FULL" not in n]
        if f == "covert_10":
            gs = sorted(gs, key=lambda t: int(t[0].replace("CAVIAR", "")))
            cum, out = nx.Graph(), []
            for n, g in gs:
                cum = nx.compose(cum, g)
                out.append((n, cum.copy()))
            gs = out
        for k in range(len(gs) - 1):
            (n0, g0), (n1, g1) = gs[k], gs[k + 1]
            gp = gs[k - 1][1] if k > 0 else nx.Graph()
            active = {v for v in g0 if g0.degree(v) > 0}
            new = {tuple(sorted(e)) for e in g1.edges() if not g0.has_edge(*e) and e[0] in active and e[1] in active}
            if len(new) < 3:
                continue
            G = g0.subgraph(active).copy()
            pairs = [(a, b) for a in sorted(active) for b in sorted(active) if a < b and not G.has_edge(a, b)]
            y = np.array([int(p in new) for p in pairs])
            raw = features(G, pairs, gp.subgraph([v for v in gp if v in active]).copy())
            units.append({"network": f, "task": "B_predict_ahead", "unit": f"{n0}->{n1}", "X": to_percentiles(raw),
                          "ppr": raw.ppr.values, "aa": raw.aa.values, "y": y})
    # C: edge hiding
    for k, f in enumerate(H.STATIC):
        G0 = H.pick_static(f)
        G0 = G0.subgraph([v for v in G0 if G0.degree(v) > 0]).copy()
        edges = sorted(tuple(sorted(e)) for e in G0.edges())
        rng = np.random.default_rng(H.RNG_SEED + k)
        for r in range(EDGE_HIDE_REPEATS):
            hide = set(map(tuple, np.array(edges)[rng.choice(len(edges), size=max(1, int(0.2 * len(edges))), replace=False)]))
            G = G0.copy()
            G.remove_edges_from(hide)
            nodes = sorted(G)
            pairs = [(a, b) for i, a in enumerate(nodes) for b in nodes[i + 1:] if not G.has_edge(a, b)]
            y = np.array([int(p in hide) for p in pairs])
            if y.sum() == 0:
                continue
            raw = features(G, pairs)
            units.append({"network": f, "task": "C_edge_hiding", "unit": f"rep{r}", "X": to_percentiles(raw),
                          "ppr": raw.ppr.values, "aa": raw.aa.values, "y": y})
    return units


def ap_lift(y, s):
    return average_precision_score(y, s) / y.mean()


def run():
    units = build_units()
    for u in units:
        u["group"] = GROUPS.get(u["network"], u["network"])
    nets = sorted({u["group"] for u in units})
    rows = []
    variants = {
        "lr_struct": ("lr", STRUCT), "gbm_struct": ("gbm", STRUCT),
        # temporal variants evaluated in run 1 (results/learned_ranker/run1_with_temporal.json): they lost; not rerun
    }
    coefs = {}
    for held in nets:
        train = [u for u in units if u["group"] != held]
        test = [u for u in units if u["group"] == held]
        for name, (kind, cols) in variants.items():
            temporal = cols != STRUCT
            tr = [u for u in train if (not temporal) or u["task"] == "B_predict_ahead"]
            te = [u for u in test if (not temporal) or u["task"] == "B_predict_ahead"]
            if not te or not tr:
                continue
            X = np.vstack([u["X"][cols].values for u in tr])
            y = np.concatenate([u["y"] for u in tr])
            if kind == "lr":
                sc = StandardScaler().fit(X)
                m = LogisticRegression(C=1.0, class_weight="balanced", max_iter=5000).fit(sc.transform(X), y)
                pred = lambda Z: m.predict_proba(sc.transform(Z))[:, 1]
                coefs.setdefault(name, []).append(m.coef_[0])
            else:
                w = np.where(y == 1, (len(y) - y.sum()) / max(y.sum(), 1), 1.0)
                m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                                   l2_regularization=1.0, random_state=0).fit(X, y, sample_weight=w)
                pred = lambda Z: m.predict_proba(Z)[:, 1]
            for u in te:
                s = pred(u["X"][cols].values)
                rows.append({"network": u["network"], "group": held, "task": u["task"], "unit": u["unit"], "method": name,
                             "ap": average_precision_score(u["y"], s), "ap_lift": ap_lift(u["y"], s),
                             "p10": H.evaluate(u["y"], s)["p10"], "positives": int(u["y"].sum())})
                if name in ("gbm_struct", "lr_struct"):
                    # blend: average of within-unit percentile ranks of the model score and of PPR
                    blend = pd.Series(s).rank(pct=True).values + pd.Series(u["ppr"]).rank(pct=True).values
                    bname = "blend_ppr_" + name.split("_")[0]
                    rows.append({"network": u["network"], "group": held, "task": u["task"], "unit": u["unit"], "method": bname,
                                 "ap": average_precision_score(u["y"], blend), "ap_lift": ap_lift(u["y"], blend),
                                 "p10": H.evaluate(u["y"], blend)["p10"], "positives": int(u["y"].sum())})
        for u in test:
            for name, s in (("ppr_current", u["ppr"]), ("adamic_adar", u["aa"])):
                rows.append({"network": u["network"], "group": held, "task": u["task"], "unit": u["unit"], "method": name,
                             "ap": average_precision_score(u["y"], s), "ap_lift": ap_lift(u["y"], s),
                             "p10": H.evaluate(u["y"], s)["p10"], "positives": int(u["y"].sum())})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "lono_evaluations.csv", index=False)

    rng = np.random.default_rng(3)
    report = {}
    for task in ["B_predict_ahead", "C_edge_hiding"]:
        d = df[df.task == task]
        piv = d.pivot_table(index=["network", "unit"], columns="method", values="ap_lift")
        net = d.groupby(["method", "network"]).ap_lift.mean().unstack(0)
        out = {}
        for mth in piv.columns:
            if mth == "ppr_current":
                continue
            diff = (piv[mth] - piv["ppr_current"]).dropna().values
            nd = (net[mth] - net["ppr_current"]).dropna().values
            boots = [rng.choice(diff, len(diff)).mean() for _ in range(5000)]
            nboots = [rng.choice(nd, len(nd)).mean() for _ in range(5000)]
            out[mth] = {"units": int(len(diff)), "mean_ap_lift": round(float(piv[mth].mean()), 3),
                        "ppr_mean_ap_lift": round(float(piv["ppr_current"].mean()), 3),
                        "unit_wins": int((diff > 0).sum()), "unit_ties": int((diff == 0).sum()),
                        "mean_gain": round(float(diff.mean()), 3),
                        "ci95": [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)],
                        "network_wins": f"{int((nd > 0).sum())}/{len(nd)}",
                        "network_ci95": [round(float(np.percentile(nboots, 2.5)), 3), round(float(np.percentile(nboots, 97.5)), 3)],
                        "median_rel_gain": f"{np.median(((piv[mth] - piv['ppr_current']) / piv['ppr_current']).dropna()):+.1%}",
                        "mean_p10": round(float(d[d.method == mth].p10.mean()), 3),
                        "ppr_mean_p10": round(float(d[d.method == "ppr_current"].p10.mean()), 3)}
        report[task] = out
    report["lr_struct_mean_coefficients"] = dict(zip(STRUCT, np.round(np.mean(coefs["lr_struct"], axis=0), 3).tolist()))
    report["units"] = {t: int((df[(df.method == "ppr_current")].task == t).sum()) for t in ["B_predict_ahead", "C_edge_hiding"]}
    report["networks"] = int(df.network.nunique())
    report["held_out_groups"] = len(nets)
    report["grouping"] = GROUPS
    (OUT / "lono_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    run()
