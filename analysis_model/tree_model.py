"""Dependency-free scoring of the exported gradient-boosting ranker (JSON trees, NumPy only).

The model was trained with scikit-learn's HistGradientBoostingClassifier (scripts/train_link_ranker.py) and exported
node-by-node, so the app does not depend on a specific scikit-learn version. Binary log-loss:
probability = sigmoid(baseline + sum of tree outputs); at each split go LEFT if x <= threshold (no missing values occur).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class TreeEnsemble:
    def __init__(self, spec: dict):
        self.baseline = float(spec["baseline"])
        self.trees = [{k: np.asarray(v) for k, v in t.items()} for t in spec["trees"]]

    @classmethod
    def load(cls, path: Path) -> "TreeEnsemble":
        return cls(json.loads(Path(path).read_text()))

    def raw(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        out = np.full(len(X), self.baseline)
        rows = np.arange(len(X))
        for t in self.trees:
            node = np.zeros(len(X), dtype=int)
            active = ~t["is_leaf"][node].astype(bool)
            while active.any():
                n = node[active]
                go_left = X[rows[active], t["feature"][n]] <= t["threshold"][n]
                node[active] = np.where(go_left, t["left"][n], t["right"][n])
                active = ~t["is_leaf"][node].astype(bool)
            out += t["value"][node]
        return out

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = 1.0 / (1.0 + np.exp(-self.raw(X)))
        return np.column_stack([1 - p, p])


def export_sklearn_hgb(model, path: Path) -> dict:
    """Export a fitted binary HistGradientBoostingClassifier (numerical features only) to JSON."""
    if getattr(model, "is_categorical_", None) is not None and np.any(model.is_categorical_):
        raise ValueError("categorical features are not supported by the exporter")
    trees = []
    for (pred,) in model._predictors:
        nd = pred.nodes
        trees.append({"feature": nd["feature_idx"].astype(int).tolist(), "threshold": nd["num_threshold"].astype(float).tolist(),
                      "left": nd["left"].astype(int).tolist(), "right": nd["right"].astype(int).tolist(),
                      "is_leaf": nd["is_leaf"].astype(int).tolist(), "value": nd["value"].astype(float).tolist()})
    spec = {"format": "tree_ensemble_v1", "baseline": float(np.ravel(model._baseline_prediction)[0]), "trees": trees}
    Path(path).write_text(json.dumps(spec))
    return spec
