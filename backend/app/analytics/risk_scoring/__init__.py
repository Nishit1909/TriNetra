"""Layer 3 — risk scoring (feature engineering, Elliptic training, case scoring)."""
from .elliptic_train import RiskModel, load_elliptic, make_synthetic_elliptic_like_table, train_risk_model
from .features import MODEL_FEATURES, SPEC_FEATURES, engineer_case_features, feature_availability, structural_feature_table
from .score_case import assemble_person_metrics, risk_explanations, score_case_risk

__all__ = [
    "RiskModel", "train_risk_model", "load_elliptic", "make_synthetic_elliptic_like_table",
    "engineer_case_features", "feature_availability", "structural_feature_table", "MODEL_FEATURES", "SPEC_FEATURES",
    "score_case_risk", "assemble_person_metrics", "risk_explanations",
]
