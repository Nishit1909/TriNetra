"""Layer 2 — link prediction (heuristics, GraphSAGE GNN, hidden-edge benchmark)."""
from .benchmark import hidden_edge_recovery, persons_in_both_methods, run_link_prediction
from .gnn_model import gnn_available, gnn_backend, train_gnn_link_predictor
from .heuristics import heuristic_scores, scores_to_predictions

__all__ = [
    "run_link_prediction", "hidden_edge_recovery", "persons_in_both_methods",
    "heuristic_scores", "scores_to_predictions",
    "train_gnn_link_predictor", "gnn_available", "gnn_backend",
]
