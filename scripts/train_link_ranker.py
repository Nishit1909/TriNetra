"""Train the final link ranker on ALL benchmark networks and save it with metadata.

Usage: python scripts/train_link_ranker.py cases/benchmarks/source analysis_model/models

Same features, units and hyper-parameters as scripts/experiment_learned_ranker.py (whose leave-one-network-out
results are the performance estimate; the final model's in-sample fit is NOT an estimate).
"""
import hashlib
import json
import runpy
import sys
import warnings
from pathlib import Path

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

sys.argv = [sys.argv[0], str(SRC), str(ROOT / "results" / "learned_ranker")]
mod = runpy.run_path(str(ROOT / "scripts" / "experiment_learned_ranker.py"), run_name="library")
units = mod["build_units"]()
STRUCT = mod["STRUCT"]
X = np.vstack([u["X"][STRUCT].values for u in units])
y = np.concatenate([u["y"] for u in units])
w = np.where(y == 1, (len(y) - y.sum()) / max(y.sum(), 1), 1.0)
params = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=1.0, random_state=0)
model = HistGradientBoostingClassifier(**params).fit(X, y, sample_weight=w)

sys.path.insert(0, str(ROOT))
from analysis_model.tree_model import TreeEnsemble, export_sklearn_hgb  # noqa: E402
path = OUT / "link_ranker_gbm_v1.trees.json"
export_sklearn_hgb(model, path)                       # shipped format: JSON trees scored with NumPy only
assert np.abs(TreeEnsemble.load(path).predict_proba(X)[:, 1] - model.predict_proba(X)[:, 1]).max() < 1e-9
lono = json.loads((ROOT / "results" / "learned_ranker" / "lono_report.json").read_text())
meta = {
    "name": "link_ranker_gbm_v1",
    "use": "hidden_link_ranker in run_case_analysis (ranker_mode 'model'; 'blend' adds percentile(PPR))",
    "format": "JSON tree ensemble (analysis_model/tree_model.py), exported from the trained sklearn model; identical predictions",
    "features": STRUCT, "feature_transform": "percentile rank within the case (analysis_model.link_features.to_percentiles)",
    "model": "sklearn HistGradientBoostingClassifier", "params": params, "class_weighting": "positives weighted to balance",
    "sklearn_version": sklearn.__version__, "numpy_version": np.__version__,
    "trained_on": {"units": len(units), "pairs": int(len(y)), "positives": int(y.sum()),
                   "networks": sorted({u["network"] for u in units}),
                   "tasks": {"B_predict_ahead": sum(u["task"] == "B_predict_ahead" for u in units),
                             "C_edge_hiding": sum(u["task"] == "C_edge_hiding" for u in units)}},
    "performance_estimate_leave_one_network_out": {
        "protocol": "leave-one-group-out; networks sharing people held out together",
        "model": {t: {k: lono[t]["gbm_struct"][k] for k in ("mean_ap_lift", "ppr_mean_ap_lift", "unit_wins", "units", "ci95", "network_wins", "network_ci95", "mean_p10", "ppr_mean_p10")}
                  for t in ("B_predict_ahead", "C_edge_hiding")},
        "blend": {t: {k: lono[t]["blend_ppr_gbm"][k] for k in ("mean_ap_lift", "ppr_mean_ap_lift", "unit_wins", "units", "ci95", "network_wins", "network_ci95")}
                  for t in ("B_predict_ahead", "C_edge_hiding")}},
    "trees_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
}
(OUT / "link_ranker_gbm_v1.json").write_text(json.dumps(meta, indent=1))
print(json.dumps({k: meta[k] for k in ("sklearn_version", "trees_sha256")}, indent=1))
