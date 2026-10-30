# Learned link ranker: experiment and decision (weights v1.2)

**Decision:** for unconnected pairs, `run_case_analysis` uses a **learned ranker** (`hidden_link_ranker`), gradient boosting on 14 structural signals. Under the strictest test (related networks held out together) it recovers hidden links **30% better** than personalised PageRank and isn't significantly different at predicting future links. Personalised PageRank and a blend remain as configuration options (`ranker_mode`).

## Candidates
- **Signals** (`analysis_model/link_features.py`, the same code the app runs): common neighbours, Adamic-Adar, resource allocation, Jaccard, preferential attachment, Katz-3, local path, personalised PageRank, inverse distance, same Louvain group, min/max degree, min/max clustering. Each is converted to a **percentile within its own network**.
- **Time signals** for predict-ahead (new neighbours, shared contacts gained, degree growth): tested in run 1 and **dropped**, because they made models worse on held-out networks (`run1_with_temporal.json`).
- **Learners:** logistic regression (L2, balanced) and gradient boosting (200 trees, learning rate 0.05, 15 leaves, L2 = 1, positives re-weighted). Fixed settings, no tuning on held-out data.
- **Blends:** percentile(model) + percentile(PageRank).

## Protocol
- **Units:** 36 predict-ahead transitions (8 time-sliced networks) and 170 edge-hiding repeats (17 networks × 10 hides of 20%).
- **Leave-one-group-out:** networks that share people are held out **together**: the Jemaah Islamiyah family (Bali 2002, JI Koschade, Christmas Eve 2000, Australian Embassy 2004, Philippines 2000) and 9/11 associates + Hamburg cell. Caviar's two datasets are one group. That makes 19 held-out groups over 24 networks. An earlier per-network run (`run2_leave_one_network_out.json`) flattered the blend, which is why grouping matters.
- **Comparison** with the current method (personalised PageRank): paired AP lift per unit with a 95% bootstrap CI, plus per-network wins with a network-level bootstrap CI.

## Results (leave-one-group-out)

| Method | Hidden links (edge hiding): AP lift | Wins vs PPR | Future links (predict ahead): AP lift | Wins vs PPR |
|---|---:|---|---:|---|
| Personalised PageRank (v1.1) | 8.78 | — | **2.86** | — |
| Adamic-Adar (v1) | 8.61 | 73/170 units, 7/17 networks | 2.50 | 10/36; **significantly worse** |
| Logistic regression | 9.55 | 91/170, 10/17, not significant | 2.58 | 12/36, not significant |
| Blend PPR + logistic | 9.03 | 97/170, 11/17, not significant | 2.76 | 13/36, not significant |
| Blend PPR + boosting | 9.34 | 104/170 (unit CI > 0), 11/17 (network CI spans 0) | 2.82 | 21/36, not significant |
| **Gradient boosting (shipped)** | **11.43** | **119/170, unit CI [+1.81, +3.51]; 12/17 networks, network CI [+0.39, +4.88]** | 2.63 | 18/36; CI [−0.55, +0.02], not significant |

Precision@10, shipped model vs PPR: hidden links 0.373 vs 0.353; future links 0.305 vs 0.300.

**Why the boosted model:** it's the only candidate significantly better on held-out networks (at both unit and network level) and not significantly worse on the other task. **Trade-off to state openly:** its average on future links is 8% lower than PPR's (2.63 vs 2.86), within noise across 36 transitions. Teams that care mostly about forecasting can set `ranker_mode: "ppr"`.

## Shipping and verification
- **Final model:** trained on all 206 units (188,140 pairs) with the same settings (`scripts/train_link_ranker.py`). Its in-sample fit isn't a performance estimate; the table above is.
- **Format:** exported to JSON trees (`analysis_model/models/link_ranker_gbm_v1.trees.json`) and scored with NumPy (`analysis_model/tree_model.py`), so there's no scikit-learn or joblib dependency at run time. Export check: identical probabilities on all 188,140 training pairs (max difference 2×10⁻¹⁶).
- **Integrity:** SHA-256 in `link_ranker_gbm_v1.json`, verified at load. A tampered or missing model falls back to personalised PageRank with a warning (tested).
- **Parity:** the experiment uses the app's own feature code. Re-running it reproduced every number exactly. `scripts/verify_ranker_parity.py`: the function's scores equal an independent computation on 9,668 pairs (max difference 0.0).
- **Determinism:** retraining reproduces the same model file checksum.

## Reading the score
`hidden_link_ranker` scores come from a class-reweighted model. They **rank** pairs within a case; they are **not probabilities**. Show the rank and the signals (shared contacts, proximity percentile, same group), never "x% chance".

## Limits
- Real but **coded** covert networks: absent ties may be unrecorded.
- Small: 8 time-sliced networks (36 transitions) limit forecasting conclusions.
- Structure-only: the ranker sees who's connected, not *how* (no tie types, times or weights). Direct evidence is handled by `tie_without_recorded_communication`, which remains the strongest signal where it exists.
- Not GAStech or crime-detection accuracy.

Rebuild: `python scripts/experiment_learned_ranker.py cases/benchmarks/source results/learned_ranker` (~3 min); `python scripts/train_link_ranker.py cases/benchmarks/source analysis_model/models`; `python scripts/verify_ranker_parity.py cases/benchmarks/source results/learned_ranker`.
