"""Check the shipped learned ranker (run_case_analysis) equals an independent computation with the saved model.

Usage: python scripts/verify_blend_parity.py cases/benchmarks/source results/learned_ranker
Correctness check only: the final model was trained on these networks, so any AP here is in-sample.
"""
import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.argv = [sys.argv[0], str(SRC), str(ROOT / "cases" / "noordin"), str(OUT)]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import benchmark_link_methods as H  # noqa: E402
from analysis_model import load_weights, run_case_analysis  # noqa: E402
from analysis_model.link_features import FEATURES, pair_features, to_percentiles  # noqa: E402

W = load_weights(ROOT / "analysis_model" / "weights" / "v1_2.json")
W["link_prediction"]["max_per_method"] = 10 ** 9
from analysis_model.tree_model import TreeEnsemble  # noqa: E402
model = TreeEnsemble.load(ROOT / "analysis_model" / "models" / "link_ranker_gbm_v1.trees.json")
checked, max_diff = 0, 0.0
for f in ["covert_26", "covert_10", "covert_28", "covert_47", "covert_31", "covert_2"]:
    G = H.pick_static(f)
    G = G.subgraph([v for v in G if G.degree(v) > 0]).copy()
    G = nx.relabel_nodes(G, {v: f"N{v:04d}" for v in G})
    persons = pd.DataFrame({"person_id": sorted(G)})
    e = pd.DataFrame([(a, b, "INTERCEPTED_COMMUNICATION", False, 1.0) for a, b in G.edges()],
                     columns=["person_a", "person_b", "relationship_type", "is_inferred", "weight"])
    r = run_case_analysis(persons, e, "observed_only", W)
    assert r["status"] == "ok" and not any("unavailable" in x for x in r["warnings"]), r["warnings"]
    pl = r["predicted_links"]; pl = pl[pl.method == "hidden_link_ranker"]
    got = {(a, b): s for a, b, s in zip(pl.person_a, pl.person_b, pl.score)}
    nodes = sorted(G)
    pairs = [(a, b) for i, a in enumerate(nodes) for b in nodes[i + 1:] if not G.has_edge(a, b)]
    fe = pair_features(G, pairs)
    prob = model.predict_proba(to_percentiles(fe)[FEATURES].values)[:, 1]
    ref = prob
    diffs = [abs(got[p] - ref[i]) for i, p in enumerate(pairs)]
    assert len(got) == len(pairs), (len(got), len(pairs))
    max_diff = max(max_diff, max(diffs)); checked += len(pairs)
res = {"networks": 6, "pairs_checked": checked, "max_abs_score_diff": max_diff, "parity": max_diff < 1e-9}
(OUT / "ranker_parity.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
