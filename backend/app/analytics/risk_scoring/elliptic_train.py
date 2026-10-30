"""Layer 3 — train and validate the XGBoost risk classifier on the Elliptic dataset.

Why Elliptic
------------
The project's own case data is a synthetic investigation scenario with **no
defensible criminal-risk labels**.  Elliptic (Weber et al., KDD 2019) is a
real Bitcoin transaction graph with 4,545 illicit and 42,019 licit labelled
nodes.  It is the only ground truth available, so every accuracy number in
this package comes from here.

Why the *shared structural* feature schema
------------------------------------------
Elliptic ships 165 anonymised per-transaction features.  A model trained on
those cannot score a police case — the columns do not exist there.  Instead
we compute :data:`~sih26189_analytics.risk_scoring.features.MODEL_FEATURES`
on the Elliptic *transaction graph* (PageRank percentile, connection
percentile, community-size percentile, clustering percentile, …) exactly as
we compute them on a case person graph.  Features that Elliptic cannot
supply (amount-based structuring, clock-time odd-hour ratio, cross-layer
evidence, GNN agreement) are ``NaN`` during training; XGBoost learns
default directions for them and — honestly — never learns their meaning.
The README states this limitation explicitly.

Validation
----------
* Stratified k-fold (default 5) with per-fold precision / recall / F1 / AUC /
  AUPRC on the illicit class, plus an out-of-fold confusion matrix.
* If ``elliptic_txs_features.csv`` is available, a **temporal hold-out**
  (train on time steps ≤ 34, test on 35–49 — the split used in the original
  paper) is reported as well, because it is the stricter generalisation test.
* Raw accuracy is reported but is *not* the headline metric (illicit is a
  ~10 % minority class).

Expected files (Kaggle "Elliptic Data Set")
-------------------------------------------
``elliptic_txs_classes.csv`` (txId,class with 1/2/unknown),
``elliptic_txs_edgelist.csv`` (txId1,txId2) and optionally
``elliptic_txs_features.csv`` (headerless; only columns 0–1 = txId, time_step
are read).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from xgboost import XGBClassifier

from .features import MODEL_FEATURES, structural_feature_table

logger = logging.getLogger(__name__)

ELLIPTIC_TEMPORAL_SPLIT_STEP = 34
DEFAULT_XGB_PARAMS: Dict = dict(
    n_estimators=400,
    max_depth=4,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    reg_lambda=1.0,
    tree_method="hist",
    eval_metric="aucpr",
    n_jobs=1,
)


@dataclass
class RiskModel:
    """A trained XGBoost risk classifier plus everything needed to audit it."""

    model: XGBClassifier
    feature_columns: List[str]
    model_version: str
    trained_at: str
    training_dataset: str            # "elliptic" or "synthetic_smoke"
    n_train: int
    validation: Dict = field(default_factory=dict)
    feature_importance: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    # -- persistence -----------------------------------------------------
    def save(self, path: str | Path) -> None:
        """Persist with joblib (model + metadata) — the backend can reload without retraining."""
        import joblib

        joblib.dump(self, Path(path))

    @staticmethod
    def load(path: str | Path) -> "RiskModel":
        import joblib

        return joblib.load(Path(path))

    # -- table row -------------------------------------------------------
    def risk_model_validation_row(self) -> Dict:
        """Row for the ``risk_model_validation`` table (k-fold means)."""
        cv = self.validation.get("kfold", {})
        return {
            "model_version": self.model_version,
            "dataset": self.training_dataset,
            "precision": cv.get("precision_mean"),
            "recall": cv.get("recall_mean"),
            "f1": cv.get("f1_mean"),
            "auc": cv.get("auc_mean"),
            "trained_at": self.trained_at,
        }


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_elliptic(
    elliptic_labels_path: str | Path,
    elliptic_edgelist_path: str | Path,
    elliptic_features_path: Optional[str | Path] = None,
) -> Tuple[nx.Graph, pd.DataFrame]:
    """Load the Elliptic graph and labels.

    Returns ``(graph, labels_df)`` where ``labels_df`` has ``txId, label``
    (1 = illicit, 0 = licit; unknown rows dropped) and, when the features
    file is given, ``time_step``.
    """
    classes = pd.read_csv(elliptic_labels_path, dtype={"txId": str, "class": str})
    edges = pd.read_csv(elliptic_edgelist_path, dtype=str)
    g = nx.Graph()
    g.add_nodes_from(classes["txId"].astype(str))
    g.add_edges_from(zip(edges.iloc[:, 0].astype(str), edges.iloc[:, 1].astype(str)))

    lab = classes[classes["class"].isin(["1", "2"])].copy()
    lab["label"] = (lab["class"] == "1").astype(int)
    lab = lab[["txId", "label"]]
    if elliptic_features_path and Path(elliptic_features_path).exists():
        ts = pd.read_csv(elliptic_features_path, header=None, usecols=[0, 1], dtype={0: str, 1: int})
        ts.columns = ["txId", "time_step"]
        lab = lab.merge(ts, on="txId", how="left")
    return g, lab.reset_index(drop=True)


def elliptic_feature_table(graph: nx.Graph, labels: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Shared-schema features for every labelled Elliptic node (~30 s on a laptop)."""
    t0 = time.time()
    feats = structural_feature_table(graph, nodes=sorted(graph.nodes()), seed=seed)
    feats = feats.rename(columns={"node_id": "txId"})
    for c in MODEL_FEATURES:
        if c not in feats:
            feats[c] = np.nan
    df = labels.merge(feats, on="txId", how="left")
    logger.info("Elliptic feature table built in %.1fs (%d labelled rows)", time.time() - t0, len(df))
    return df


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _metrics(y_true: np.ndarray, proba: np.ndarray, threshold: float = 0.5) -> Dict[str, float]:
    pred = (proba >= threshold).astype(int)
    out = {
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "accuracy": float((pred == y_true).mean()),
    }
    try:
        out["auc"] = float(roc_auc_score(y_true, proba))
        out["auprc"] = float(average_precision_score(y_true, proba))
    except ValueError:
        out["auc"] = float("nan")
        out["auprc"] = float("nan")
    return out


def _make_xgb(y: np.ndarray, seed: int, params: Optional[Dict] = None) -> XGBClassifier:
    p = dict(DEFAULT_XGB_PARAMS)
    if params:
        p.update(params)
    pos = max(int(y.sum()), 1)
    neg = max(int(len(y) - y.sum()), 1)
    p["scale_pos_weight"] = neg / pos
    p["random_state"] = seed
    return XGBClassifier(**p)


# --------------------------------------------------------------------------- #
# Training
# --------------------------------------------------------------------------- #
def train_risk_model(
    elliptic_features_path: Optional[str | Path] = None,
    elliptic_labels_path: Optional[str | Path] = None,
    elliptic_edgelist_path: Optional[str | Path] = None,
    n_folds: int = 5,
    seed: int = 42,
    threshold: float = 0.5,
    xgb_params: Optional[Dict] = None,
    feature_table: Optional[pd.DataFrame] = None,
    training_dataset: str = "elliptic",
) -> Tuple[RiskModel, Dict]:
    """Train + k-fold cross-validate the XGBoost risk classifier on Elliptic.

    Parameters
    ----------
    elliptic_features_path
        ``elliptic_txs_features.csv`` (optional — only ``txId`` and
        ``time_step`` are read, to enable the temporal hold-out report).
    elliptic_labels_path
        ``elliptic_txs_classes.csv`` (required unless ``feature_table`` given).
    elliptic_edgelist_path
        ``elliptic_txs_edgelist.csv``; if omitted it is looked for next to
        the labels file.
    n_folds, seed, threshold, xgb_params
        Cross-validation / model settings.
    feature_table
        Pre-built table with ``label`` + :data:`MODEL_FEATURES` (used by the
        stress test with a synthetic smoke set — see ``training_dataset``).
    training_dataset
        Provenance tag stored on the model: ``"elliptic"`` for the real data.

    Returns
    -------
    (RiskModel, validation_dict)
        ``validation_dict`` has ``kfold`` (per-fold scores, means, out-of-fold
        confusion matrix), optional ``temporal_holdout``, ``feature_importance``,
        ``n_labelled``, ``positive_rate`` and ``notes``.
    """
    notes: List[str] = []
    if feature_table is None:
        if elliptic_labels_path is None:
            raise ValueError("elliptic_labels_path is required (or pass feature_table).")
        if elliptic_edgelist_path is None:
            cand = Path(elliptic_labels_path).with_name("elliptic_txs_edgelist.csv")
            if not cand.exists():
                raise FileNotFoundError("elliptic_txs_edgelist.csv not found; pass elliptic_edgelist_path.")
            elliptic_edgelist_path = cand
        graph, labels = load_elliptic(elliptic_labels_path, elliptic_edgelist_path, elliptic_features_path)
        feature_table = elliptic_feature_table(graph, labels, seed=seed)
    df = feature_table.copy()
    X = df[MODEL_FEATURES].astype(float).values
    y = df["label"].astype(int).values
    if len(np.unique(y)) < 2:
        raise ValueError("Need both classes present to train the risk model.")

    always_missing = [c for c in MODEL_FEATURES if df[c].isna().all()]
    if always_missing:
        notes.append(
            "Features entirely missing in the training data (model cannot learn their meaning; they are "
            f"kept in the schema so case tables align): {always_missing}"
        )

    # ---- stratified k-fold -------------------------------------------------
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    fold_scores: List[Dict[str, float]] = []
    oof = np.zeros(len(y))
    for i, (tr, te) in enumerate(skf.split(X, y)):
        m = _make_xgb(y[tr], seed + i, xgb_params)
        m.fit(X[tr], y[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]
        fold_scores.append(_metrics(y[te], oof[te], threshold))
    cm = confusion_matrix(y, (oof >= threshold).astype(int), labels=[0, 1])
    kfold = {f"{k}_mean": float(np.mean([s[k] for s in fold_scores])) for k in fold_scores[0]}
    kfold.update({f"{k}_std": float(np.std([s[k] for s in fold_scores])) for k in fold_scores[0]})
    kfold["fold_scores"] = fold_scores
    kfold["confusion_matrix"] = {"tn": int(cm[0, 0]), "fp": int(cm[0, 1]), "fn": int(cm[1, 0]), "tp": int(cm[1, 1])}
    kfold["threshold"] = threshold
    kfold["n_folds"] = n_folds

    validation: Dict = {
        "kfold": kfold,
        "n_labelled": int(len(y)),
        "positive_rate": float(y.mean()),
        "headline_note": "Illicit is a minority class — judge by precision/recall/F1/AUPRC, not accuracy.",
    }

    # ---- temporal hold-out (paper split) -----------------------------------
    if "time_step" in df and df["time_step"].notna().any():
        tr = (df["time_step"] <= ELLIPTIC_TEMPORAL_SPLIT_STEP).values
        te = (df["time_step"] > ELLIPTIC_TEMPORAL_SPLIT_STEP).values
        if tr.sum() and te.sum() and len(np.unique(y[te])) == 2:
            m = _make_xgb(y[tr], seed, xgb_params)
            m.fit(X[tr], y[tr])
            validation["temporal_holdout"] = {
                "train_time_steps": f"<= {ELLIPTIC_TEMPORAL_SPLIT_STEP}",
                "test_time_steps": f"> {ELLIPTIC_TEMPORAL_SPLIT_STEP}",
                "n_train": int(tr.sum()),
                "n_test": int(te.sum()),
                **_metrics(y[te], m.predict_proba(X[te])[:, 1], threshold),
            }
    else:
        notes.append("No time_step available (features file not supplied) — temporal hold-out not reported.")

    # ---- final fit on everything -------------------------------------------
    final = _make_xgb(y, seed, xgb_params)
    final.fit(X, y)
    imp = dict(zip(MODEL_FEATURES, [float(v) for v in final.feature_importances_]))
    validation["feature_importance"] = imp
    validation["notes"] = notes

    trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    version = f"xgb-shared-schema-{training_dataset}-{datetime.now(timezone.utc):%Y%m%d}"
    model = RiskModel(
        model=final, feature_columns=list(MODEL_FEATURES), model_version=version, trained_at=trained_at,
        training_dataset=training_dataset, n_train=int(len(y)), validation=validation,
        feature_importance=imp, notes=notes,
    )
    return model, validation


# --------------------------------------------------------------------------- #
# Synthetic smoke-test stand-in (NOT a validation source)
# --------------------------------------------------------------------------- #
def make_synthetic_elliptic_like_table(n_nodes: int = 3000, seed: int = 42) -> pd.DataFrame:
    """Small Elliptic-*shaped* labelled table for smoke tests only.

    A random graph with a planted structure: nodes in a few dense "illicit"
    clusters get label 1.  Metrics obtained on this table are MEANINGLESS as
    a validation claim — it exists so the pipeline can be exercised when the
    real Elliptic files are not on the machine.  Models trained on it carry
    ``training_dataset="synthetic_smoke"``.
    """
    rng = np.random.default_rng(seed)
    g = nx.powerlaw_cluster_graph(n_nodes, 2, 0.3, seed=seed)
    labels = np.zeros(n_nodes, dtype=int)
    n_clusters = max(3, n_nodes // 300)
    for _ in range(n_clusters):
        centre = int(rng.integers(n_nodes))
        members = [centre] + list(g[centre])[:12]
        for a in members:
            for b in members:
                if a < b and rng.random() < 0.6:
                    g.add_edge(a, b)
            labels[a] = 1
    feats = structural_feature_table(g, nodes=list(range(n_nodes)), seed=seed).rename(columns={"node_id": "txId"})
    feats["label"] = labels[feats["txId"].astype(int).values]
    for c in MODEL_FEATURES:
        if c not in feats:
            feats[c] = np.nan
    return feats
