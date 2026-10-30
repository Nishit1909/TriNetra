"""Layer 3 — score a case with the trained risk model (demo-only output).

There is **no ground truth** for criminal risk in the case data, so every row
produced here carries ``risk_score_is_demo_only = True``.  The score is a
ranking aid for investigators ("who should we look at first?"), not a
validated probability that someone is a criminal.  The only validated
numbers live in :meth:`RiskModel.risk_model_validation_row` (Elliptic).
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .elliptic_train import RiskModel
from .features import MODEL_FEATURES, feature_availability

RISK_COLUMNS = ["person_id", "risk_score", "risk_score_is_demo_only"]
PERSON_METRICS_COLUMNS = [
    "person_id", "degree_centrality", "betweenness_centrality", "pagerank",
    "risk_score", "risk_score_is_demo_only", "rank",
]


def score_case_risk(risk_model: RiskModel, case_features_df: pd.DataFrame, demo_only: bool = True) -> pd.DataFrame:
    """Risk score per person from the trained model.

    Parameters
    ----------
    risk_model
        Output of :func:`train_risk_model` (or :meth:`RiskModel.load`).
    case_features_df
        Output of :func:`engineer_case_features`.  Columns are aligned to the
        model's feature list; anything missing becomes NaN (XGBoost handles
        it natively — no imputation).
    demo_only
        Keep ``True`` for case data.  Only set ``False`` when scoring a dataset
        that genuinely has ground-truth labels.

    Returns
    -------
    pd.DataFrame
        ``person_id, risk_score, risk_score_is_demo_only`` sorted by
        ``risk_score`` descending.  ``risk_score`` is the model's illicit-class
        probability in [0, 1]; it is always finite.
    """
    if case_features_df is None or case_features_df.empty:
        return pd.DataFrame(columns=RISK_COLUMNS)
    cols = risk_model.feature_columns or MODEL_FEATURES
    X = case_features_df.reindex(columns=cols).astype(float).values
    proba = risk_model.model.predict_proba(X)[:, 1]
    proba = np.where(np.isfinite(proba), proba, 0.0)
    out = pd.DataFrame(
        {
            "person_id": case_features_df["person_id"].values,
            "risk_score": np.round(proba.astype(float), 6),
            "risk_score_is_demo_only": bool(demo_only),
        }
    )
    return out.sort_values("risk_score", ascending=False).reset_index(drop=True)[RISK_COLUMNS]


def assemble_person_metrics(centrality_df: pd.DataFrame, risk_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Merge Layer 1 centrality with Layer 3 risk into ``person_metrics`` rows.

    The backend adds ``analysis_run_id``.  ``rank`` is by PageRank (1 = most
    central).  When ``risk_df`` is ``None`` the risk columns are NaN / True.
    """
    df = centrality_df.copy()
    if risk_df is not None and not risk_df.empty:
        df = df.merge(risk_df, on="person_id", how="left")
    else:
        df["risk_score"] = np.nan
        df["risk_score_is_demo_only"] = True
    df["risk_score_is_demo_only"] = df["risk_score_is_demo_only"].fillna(True).astype(bool)
    if "rank" not in df:
        df["rank"] = df["pagerank"].rank(ascending=False, method="first").astype(int)
    return df[PERSON_METRICS_COLUMNS].sort_values("rank").reset_index(drop=True)


def risk_explanations(risk_model: RiskModel, case_features_df: pd.DataFrame, top_k: int = 3) -> List[Dict]:
    """Per-person explanation: the top contributing features (by global importance × feature value).

    Lightweight and model-agnostic: for each person, list the ``top_k``
    features (with their values) among those that are non-missing, ordered by
    the model's global feature importance.  Suitable for a dashboard tooltip;
    for a full per-prediction attribution use SHAP on ``risk_model.model``.
    """
    imp = risk_model.feature_importance or {}
    avail = feature_availability(case_features_df)
    ranked = [c for c in sorted(imp, key=imp.get, reverse=True) if avail.get(c, 0) > 0]
    out = []
    for row in case_features_df.itertuples(index=False):
        r = row._asdict()
        feats = [(c, r[c]) for c in ranked if c in r and r[c] is not None and not pd.isna(r[c])][:top_k]
        out.append(
            {
                "person_id": r["person_id"],
                "top_features": [{"feature": c, "value": round(float(v), 4), "global_importance": round(imp[c], 4)} for c, v in feats],
                "note": "demo-only ranking aid; no ground truth exists for this case",
            }
        )
    return out
