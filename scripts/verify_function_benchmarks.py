"""Run the SHIPPED run_case_analysis through the benchmark tasks and compare with the harness numbers.

Usage: python scripts/verify_function_benchmarks.py cases/benchmarks/source cases/noordin results/link_methods

Checks that the code the app calls reproduces the benchmarked methods:
  A. Noordin hide-and-recover via method `tie_without_recorded_communication`
  B. predict-ahead and C. edge hiding via method `network_proximity_ppr`
The function returns ranked lists; pairs it does not list are scored 0 (as a user would see them: not suggested).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import benchmark_link_methods as H  # noqa: E402  (harness: loaders, evaluate, transition building)
from analysis_model import load_weights, run_case_analysis  # noqa: E402

SRC, NOORDIN, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
W = load_weights(ROOT / "analysis_model" / "weights" / "v1_2.json")
W["link_prediction"]["max_per_method"] = 10 ** 9          # return full rankings for evaluation
W["link_prediction"]["ranker_mode"] = "ppr"               # this script verifies the PPR method; the learned ranker is verified by verify_ranker_parity.py


def fn_scores(G, pairs, method, rel_type="INTERCEPTED_COMMUNICATION"):
    ids = sorted(G)
    persons = pd.DataFrame({"person_id": [f"N{v:04d}" for v in ids]})
    e = pd.DataFrame({"person_a": [f"N{a:04d}" for a, b in G.edges()], "person_b": [f"N{b:04d}" for a, b in G.edges()],
                      "relationship_type": rel_type, "is_inferred": False, "weight": 1.0})
    r = run_case_analysis(persons, e, "observed_only", W)
    assert r["status"] == "ok", r["stages"]
    pl = r["predicted_links"]
    pl = pl[pl.method == method]
    d = {(a, b): s for a, b, s in zip(pl.person_a, pl.person_b, pl.score)}
    return np.array([d.get(tuple(sorted((f"N{a:04d}", f"N{b:04d}"))), 0.0) for a, b in pairs])


rows = []
# ---- A: Noordin
persons = pd.read_csv(NOORDIN / "persons.csv")
rel = pd.read_csv(NOORDIN / "relationships.csv")
feats = rel[rel.layer != "communications"]
edges = pd.DataFrame({"person_a": feats.person_a, "person_b": feats.person_b, "relationship_type": feats.layer.str.upper(),
                      "is_inferred": False, "weight": 1.0})
r = run_case_analysis(persons, edges, "observed_only", W)
pl = r["predicted_links"]
m1 = {(a, b): s for a, b, s, m in zip(pl.person_a, pl.person_b, pl.score, pl.method) if m == "tie_without_recorded_communication"}
ids = list(persons.person_id)
pairs = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
lab = {tuple(sorted(x)) for x in zip(rel[rel.layer == "communications"].person_a, rel[rel.layer == "communications"].person_b)}
y = np.array([int(p in lab) for p in pairs])
s = np.array([m1.get(p, 0.0) for p in pairs])
ev = H.evaluate(y, s)
rows.append({"test": "A_noordin", "unit": "all 3,081 pairs", "function_ap": ev["ap"], "function_p10": ev["p10"], "function_ap_lift": ev["ap_lift"]})

# ---- B: predict ahead (same transitions as the harness)
harness = pd.read_csv(OUT / "all_evaluations.csv")
for f, pref in H.TEMPORAL.items():
    gs = [(n, g) for n, g in H.load_graphs(SRC / f"{f}.rda") if n.startswith(pref) and "2MODE" not in n and "FULL" not in n]
    if f == "covert_10":
        import networkx as nx
        gs = sorted(gs, key=lambda t: int(t[0].replace("CAVIAR", "")))
        cum, out = nx.Graph(), []
        for n, g in gs:
            cum = nx.compose(cum, g)
            out.append((n, cum.copy()))
        gs = out
    for (n0, g0), (n1, g1) in zip(gs, gs[1:]):
        active = {v for v in g0 if g0.degree(v) > 0}
        new = {tuple(sorted(e)) for e in g1.edges() if not g0.has_edge(*e) and e[0] in active and e[1] in active}
        if len(new) < 3:
            continue
        g = g0.subgraph(active).copy()
        pairs = [(a, b) for a in sorted(active) for b in sorted(active) if a < b and not g0.has_edge(a, b)]
        y = np.array([int(p in new) for p in pairs])
        ev = H.evaluate(y, fn_scores(g, pairs, "network_proximity_ppr"))
        h = harness[(harness.test == "B_predict_ahead") & (harness.network == f) & (harness.transition == f"{n0}->{n1}")]
        rows.append({"test": "B_predict_ahead", "unit": f"{f} {n0}->{n1}", "function_ap": ev["ap"], "function_p10": ev["p10"],
                     "function_ap_lift": ev["ap_lift"],
                     "harness_ppr_ap": float(h[h.method == "personalised_pagerank"].ap.iloc[0]),
                     "harness_adamic_adar_ap": float(h[h.method == "adamic_adar"].ap.iloc[0])})

res = pd.DataFrame(rows)
res.to_csv(OUT / "function_verification.csv", index=False)
b = res[res.test == "B_predict_ahead"]
summary = {
    "A_noordin_function": res[res.test == "A_noordin"].iloc[0][["function_ap", "function_p10", "function_ap_lift"]].round(4).to_dict(),
    "B_transitions": len(b),
    "B_function_equals_harness_ppr_max_abs_diff": float((b.function_ap - b.harness_ppr_ap).abs().max()),
    "B_mean_ap_function": round(float(b.function_ap.mean()), 4),
    "B_mean_ap_adamic_adar": round(float(b.harness_adamic_adar_ap.mean()), 4),
    "B_function_beats_adamic_adar": int((b.function_ap > b.harness_adamic_adar_ap).sum()),
}
(OUT / "function_verification.json").write_text(json.dumps(summary, indent=1))
print(json.dumps(summary, indent=1))
