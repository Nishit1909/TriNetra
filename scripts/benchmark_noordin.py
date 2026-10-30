"""Noordin link-recovery benchmark.

Question: can NON-communication relationships recover recorded communication links?

Usage: python scripts/benchmark_noordin.py cases/noordin results/noordin [--seed 42]

Design (fixed before looking at test results)
- One row per unordered person pair (79 people -> 3,081 pairs). Person IDs are tracking fields only.
- Label: the pair has a recorded tie in the `communications` layer. That layer is used for labels only
  and is removed from every feature graph and aggregate.
- Features: one 0/1 column per non-communication layer, multiplexity (number of non-communication
  layers), and structural scores on the union non-communication graph: common neighbours,
  Adamic-Adar, Jaccard, log degree product.
- Split: stratified random pair split 60% train / 20% validation / 20% test (fixed seed). The test set
  is scored once, at the end.
- Baselines need no training: common neighbours and Adamic-Adar, scored directly on test pairs.
- Model: logistic regression, L2, class_weight=balanced; scaler fit on train only; C chosen on
  validation average precision; final model fit on train only.
- Metrics on test: Precision@10 and Recall@10 (expected values under random tie-breaking),
  average precision, and lift over the test base rate.
- Factor ranking: standardised coefficients with bootstrap 95% ranges (train resampled), and
  leave-one-feature-out drop in VALIDATION average precision (test untouched).
- Stability (supplementary): the whole procedure repeated over 30 different split seeds.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

LABEL_LAYER = "communications"
C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]
K = 10


# ------------------------------------------------------------------ data
def build_pairs(case: Path) -> tuple[pd.DataFrame, list[str]]:
    persons = pd.read_csv(case / "persons.csv")
    rel = pd.read_csv(case / "relationships.csv")
    ids = list(persons.person_id)
    feat_layers = sorted(l for l in rel.layer.unique() if l != LABEL_LAYER)

    nc = rel[rel.layer != LABEL_LAYER]                       # communication removed from features
    G = nx.Graph()
    G.add_nodes_from(ids)
    G.add_edges_from(zip(nc.person_a, nc.person_b))
    assert not any(l == LABEL_LAYER for l in nc.layer), "label layer leaked into feature graph"

    pairs = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
    df = pd.DataFrame(pairs, columns=["person_a", "person_b"])
    key = lambda a, b: (a, b) if a < b else (b, a)
    for layer in feat_layers:
        s = {key(a, b) for a, b in zip(nc[nc.layer == layer].person_a, nc[nc.layer == layer].person_b)}
        df[f"layer_{layer}"] = [int((a, b) in s) for a, b in pairs]
    df["multiplexity"] = df[[f"layer_{l}" for l in feat_layers]].sum(axis=1)
    nbr = {n: set(G[n]) for n in G}
    cn, aa, jac, dp = [], [], [], []
    for a, b in pairs:
        common = nbr[a] & nbr[b]
        cn.append(len(common))
        aa.append(sum(1 / math.log(len(nbr[z])) for z in common if len(nbr[z]) > 1))
        union = nbr[a] | nbr[b]
        jac.append(len(common) / len(union) if union else 0.0)
        dp.append(math.log1p(len(nbr[a]) * len(nbr[b])))
    df["common_neighbours"], df["adamic_adar"], df["jaccard"], df["log_degree_product"] = cn, aa, jac, dp

    lab = {key(a, b) for a, b in zip(rel[rel.layer == LABEL_LAYER].person_a, rel[rel.layer == LABEL_LAYER].person_b)}
    df["label"] = [int((a, b) in lab) for a, b in pairs]
    features = [f"layer_{l}" for l in feat_layers] + ["multiplexity", "common_neighbours", "adamic_adar",
                                                      "jaccard", "log_degree_product"]
    return df, features


# ------------------------------------------------------------------ metrics
def expected_precision_at_k(y: np.ndarray, s: np.ndarray, k: int = K) -> float:
    """Expected precision@k when tied scores are ordered at random."""
    order = np.argsort(-s, kind="stable")
    s_sorted, y_sorted = s[order], y[order]
    thresh = s_sorted[k - 1]
    above = s_sorted > thresh
    tie = s_sorted == thresh
    n_above = int(above.sum())
    hits_above = int(y_sorted[above].sum())
    slots = k - n_above
    tie_rate = y_sorted[tie].mean() if tie.any() else 0.0
    return (hits_above + slots * tie_rate) / k


def evaluate(y, s, base_rate):
    p = expected_precision_at_k(y, s)
    return {"precision_at_10": round(p, 4),
            "recall_at_10": round(p * K / y.sum(), 4) if y.sum() else None,
            "average_precision": round(float(average_precision_score(y, s)), 4),
            "lift_precision_at_10": round(p / base_rate, 2),
            "lift_average_precision": round(float(average_precision_score(y, s)) / base_rate, 2)}


# ------------------------------------------------------------------ one full run
def split(df, seed):
    idx = np.arange(len(df))
    tr, tmp = train_test_split(idx, test_size=0.4, stratify=df.label, random_state=seed)
    va, te = train_test_split(tmp, test_size=0.5, stratify=df.label.iloc[tmp], random_state=seed)
    return tr, va, te


def fit_lr(X, y, C):
    scaler = StandardScaler().fit(X)
    m = LogisticRegression(C=C, penalty="l2", class_weight="balanced", max_iter=5000).fit(scaler.transform(X), y)
    return scaler, m


def run(df, features, seed):
    tr, va, te = split(df, seed)
    X, y = df[features].values, df.label.values
    val_ap = {}
    for C in C_GRID:
        sc, m = fit_lr(X[tr], y[tr], C)
        val_ap[C] = average_precision_score(y[va], m.predict_proba(sc.transform(X[va]))[:, 1])
    C = max(val_ap, key=lambda c: (round(val_ap[c], 6), -c))   # ties -> smaller C (stronger regularisation)
    sc, m = fit_lr(X[tr], y[tr], C)
    base = y[te].mean()
    res = {
        "common_neighbours": evaluate(y[te], df.common_neighbours.values[te], base),
        "adamic_adar": evaluate(y[te], df.adamic_adar.values[te], base),
        # direct-tie heuristic: rank by number of non-communication tie types, Adamic-Adar breaks ties
        "multiplexity_heuristic": evaluate(y[te], df.multiplexity.values[te] + 1e-3 * df.adamic_adar.values[te] / (1 + df.adamic_adar.values.max()), base),
        "logistic_regression": evaluate(y[te], m.predict_proba(sc.transform(X[te]))[:, 1], base),
    }
    for name, cols in (("lr_tie_types_only", [f for f in features if f.startswith("layer_")] + ["multiplexity"]),
                       ("lr_network_shape_only", ["common_neighbours", "adamic_adar", "jaccard", "log_degree_product"])):
        Xg = df[cols].values
        best = max(C_GRID, key=lambda c: average_precision_score(
            y[va], fit_lr(Xg[tr], y[tr], c)[1].predict_proba(fit_lr(Xg[tr], y[tr], c)[0].transform(Xg[va]))[:, 1]))
        scg, mg = fit_lr(Xg[tr], y[tr], best)
        res[name] = evaluate(y[te], mg.predict_proba(scg.transform(Xg[te]))[:, 1], base)
    return res, {"tr": tr, "va": va, "te": te, "C": C, "val_ap": val_ap, "scaler": sc, "model": m, "base": base}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stability-seeds", type=int, default=30)
    ap.add_argument("--bootstrap", type=int, default=500)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    df, features = build_pairs(a.case)
    res, st = run(df, features, a.seed)
    X, y = df[features].values, df.label.values

    # factor ranking 1: standardised coefficients + bootstrap ranges (train only)
    rng = np.random.default_rng(a.seed)
    boots = []
    for _ in range(a.bootstrap):
        b = rng.choice(st["tr"], size=len(st["tr"]), replace=True)
        if y[b].sum() == 0:
            continue
        _, mb = fit_lr(X[b], y[b], st["C"])
        boots.append(mb.coef_[0])
    boots = np.array(boots)
    # factor ranking 2: leave-one-feature-out drop in validation AP
    full_val = st["val_ap"][st["C"]]
    loo = {}
    for f in features:
        keep = [c for c in features if c != f]
        sc, m = fit_lr(df[keep].values[st["tr"]], y[st["tr"]], st["C"])
        loo[f] = full_val - average_precision_score(y[st["va"]], m.predict_proba(sc.transform(df[keep].values[st["va"]]))[:, 1])
    fr = pd.DataFrame({
        "feature": features,
        "std_coefficient": np.round(st["model"].coef_[0], 3),
        "bootstrap_2.5%": np.round(np.percentile(boots, 2.5, axis=0), 3),
        "bootstrap_97.5%": np.round(np.percentile(boots, 97.5, axis=0), 3),
        "loo_val_ap_drop": np.round([loo[f] for f in features], 4),
        "pairs_with_feature": [int((df[f] > 0).sum()) for f in features],
        "share_of_those_with_comm": [round(float(df.label[df[f] > 0].mean()), 3) if (df[f] > 0).any() else None for f in features],
    })
    fr["range_excludes_zero"] = (fr["bootstrap_2.5%"] > 0) | (fr["bootstrap_97.5%"] < 0)
    fr = fr.sort_values("loo_val_ap_drop", ascending=False)
    fr.to_csv(a.out / "factor_ranking.csv", index=False)

    # stability over many splits (supplementary; same fixed procedure) + averaged leave-one-out
    stab = {k: [] for k in res}
    loo_many = {f: [] for f in features}
    for s in range(a.stability_seeds):
        r, sti = run(df, features, 1000 + s)
        for k in r:
            stab[k].append(r[k])
        fv = sti["val_ap"][sti["C"]]
        for f in features:
            keep = [c for c in features if c != f]
            scf, mf = fit_lr(df[keep].values[sti["tr"]], y[sti["tr"]], sti["C"])
            loo_many[f].append(fv - average_precision_score(y[sti["va"]], mf.predict_proba(scf.transform(df[keep].values[sti["va"]]))[:, 1]))
    fr["loo_val_ap_drop_mean_30_splits"] = fr.feature.map({f: round(float(np.mean(v)), 4) for f, v in loo_many.items()})
    fr["loo_val_ap_drop_sd_30_splits"] = fr.feature.map({f: round(float(np.std(v)), 4) for f, v in loo_many.items()})
    fr = fr.sort_values("loo_val_ap_drop_mean_30_splits", ascending=False)
    fr.to_csv(a.out / "factor_ranking.csv", index=False)
    stability = {k: {m: {"mean": round(float(np.mean([x[m] for x in v])), 4), "sd": round(float(np.std([x[m] for x in v])), 4)}
                     for m in ["precision_at_10", "recall_at_10", "average_precision"]} for k, v in stab.items()}

    # artifacts
    split_col = np.empty(len(df), dtype=object)
    split_col[st["tr"]], split_col[st["va"]], split_col[st["te"]] = "train", "validation", "test"
    df.assign(split=split_col).to_csv(a.out / "pair_features.csv", index=False)
    te = st["te"]
    top = df.iloc[te].assign(lr_score=st["model"].predict_proba(st["scaler"].transform(X[te]))[:, 1]) \
        .sort_values("lr_score", ascending=False).head(K)[["person_a", "person_b", "lr_score", "multiplexity", "label"]]
    top.to_csv(a.out / "test_top10_logistic_regression.csv", index=False)
    metrics = {
        "case_id": "CASE_NOORDIN", "task": "recover recorded communication links from non-communication relationships",
        "seed": a.seed, "pairs": len(df), "positives": int(y.sum()), "overall_base_rate": round(float(y.mean()), 4),
        "split_sizes": {k: int(len(st[k])) for k in ["tr", "va", "te"]},
        "test_positives": int(y[te].sum()), "test_base_rate": round(float(st["base"]), 4),
        "features": features, "chosen_C": st["C"],
        "validation_ap_by_C": {str(k): round(v, 4) for k, v in st["val_ap"].items()},
        "test_results": res, "stability_over_seeds": {"n_seeds": a.stability_seeds, **stability},
        "bootstrap_resamples_used": int(len(boots)),
    }
    (a.out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(json.dumps({"test_results": res, "chosen_C": st["C"], "test_positives": int(y[te].sum()),
                      "test_base_rate": round(float(st["base"]), 4)}, indent=1))
    print(fr[["feature", "std_coefficient", "bootstrap_2.5%", "bootstrap_97.5%", "range_excludes_zero",
              "loo_val_ap_drop_mean_30_splits", "loo_val_ap_drop_sd_30_splits", "share_of_those_with_comm"]].to_string(index=False))
    print(json.dumps(stability, indent=1))


if __name__ == "__main__":
    main()
