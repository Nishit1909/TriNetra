# Noordin link-recovery benchmark: results

**Question:** can non-communication relationships recover recorded communication links in a real covert network?

**Answer:** yes, strongly, and almost entirely through **direct** ties (friendship, meetings, kinship), not through shared contacts. A simple count of tie types already puts real links at the top of the list. Logistic regression mainly improves the ranking of the rest of the list.

This is a separate benchmark on `CASE_NOORDIN`. It is **not** GAStech accuracy or crime-detection accuracy, and the model is not applied to any other case.

## Setup (fixed before the test set was scored)
- **Rows:** 3,081 unordered person pairs (79 people). Person IDs are tracking fields, not inputs.
- **Label:** recorded `communications` tie (200 pairs, base rate 6.5%). The layer builds labels only; it's excluded from every feature graph and aggregate (checked).
- **Features (14):** one 0/1 column per non-communication layer (9); `multiplexity` = number of those layers linking the pair; on the union non-communication graph: `common_neighbours`, `adamic_adar` = Σ 1/log(degree) over shared neighbours, `jaccard` = shared ÷ union of neighbours, `log_degree_product` = log(1 + deg(a)·deg(b)).
- **Split:** stratified random pair split, seed 42: train 1,848 / validation 616 / test 617 pairs (120 / 40 / 40 links).
- **Model:** logistic regression, L2, `class_weight=balanced`. Scaler fit on train only; C picked on validation average precision (C = 10); final fit on train only; test scored once.
- **Baselines (no training):** common neighbours; Adamic-Adar; **multiplexity heuristic** (rank by number of tie types, Adamic-Adar as tie-break), added because CN/AA ignore direct ties.
- **Metrics:** Precision@10 and Recall@10 as expected values under random tie order; average precision (AP); lift = metric ÷ test base rate.

## Results on the untouched test set (seed 42)

| Method | Precision@10 | Recall@10 | Average precision | AP lift vs random |
|---|---:|---:|---:|---:|
| Common neighbours | 0.50 | 0.125 | 0.257 | 4.0× |
| Adamic-Adar | 0.50 | 0.125 | 0.274 | 4.2× |
| Multiplexity heuristic | 1.00 | 0.250 | 0.557 | 8.6× |
| **Logistic regression (all features)** | **1.00** | **0.250** | **0.681** | **10.5×** |
| LR, tie types only | 0.90 | 0.225 | 0.663 | 10.2× |
| LR, network shape only | 0.50 | 0.125 | 0.263 | 4.1× |

Recall@10 can be at most 0.25 here (10 of 40 test links).

**Stability over 30 other split seeds (mean ± sd):**

| Method | Precision@10 | Average precision |
|---|---|---|
| Common neighbours | 0.59 ± 0.13 | 0.276 ± 0.052 |
| Adamic-Adar | 0.60 ± 0.13 | 0.306 ± 0.056 |
| Multiplexity heuristic | 0.97 ± 0.05 | 0.575 ± 0.057 |
| Logistic regression | 0.95 ± 0.06 | 0.725 ± 0.047 |
| LR, tie types only | 0.96 ± 0.06 | 0.698 ± 0.050 |
| LR, network shape only | 0.55 ± 0.15 | 0.310 ± 0.065 |

## Which factors matter (`factor_ranking.csv`)
Standardised coefficients with bootstrap 95% ranges (500 train resamples), plus the drop in validation AP when a feature is removed, averaged over 30 splits.

| Factor | Pairs with it | Share also communicating | Coefficient [95% range] | Verdict |
|---|---:|---:|---|---|
| Friendship | 91 | 87% | 0.67 [0.46, 0.98] | **Strong**: range excludes zero, largest removal drop |
| Meetings | 63 | 89% | 0.62 [0.41, 1.25] | **Strong** |
| Kinship | 16 | 81% | 0.36 [0.20, 1.45] | **Strong but few pairs** |
| Multiplexity | 594 | 29% | 0.46 [0.31, 0.72] | Positive, overlaps the layers above |
| Business & finance | 15 | 73% | 0.11 [−0.17, 1.63] | High share, too few pairs to separate from zero |
| Soulmates | 11 | 82% | 0.26 [−0.12, 1.64] | Same |
| Logistics, operations, training, classmates | 29–267 | 22–52% | ranges include zero | **Weak** |
| Common neighbours / Adamic-Adar | 2,213 | 9% | opposite signs, wide ranges | Collinear; little added value |

Removal drops are small relative to their spread (the validation set has 40 links), so read the ranking as tiers, not an exact order.

## Checks
- A rerun gives identical results (fixed seeds).
- No feature is derived from communications; common neighbours computed with communications included differ from the ones used.
- **Shuffled labels:** logistic regression AP falls to 0.074 on average (max 0.114) against a 0.065 base rate, so the result isn't leakage.
- Train, validation and test splits are disjoint and stratified (120 / 40 / 40 links).

## Limits
- **Absent links aren't confirmed non-relationships:** the data was coded from a report and is incomplete.
- **Within-network only:** pairs share people across train and test, so this measures prediction inside this network, not generalisation to unseen people or other networks.
- **Small:** 79 people and 40 test links make single-split numbers noisy. Use the 30-split ranges.
- **Not transferable as-is:** GAStech has no friendship, kinship or finance layers, and its co-location tracks departments. Use these results as supporting evidence about covert networks, not as GAStech weights.

## What this means for the project
1. In a real covert network, **direct personal and meeting ties** are the evidence that reveals communication. Shared contacts alone are weak.
2. A transparent heuristic (count of tie types) gets the top of the list right. Logistic regression adds a better full ranking, with readable weights.
3. For the app's default weights: personal ties and meetings rank high, organisational ties (classmates, training) low, marked "based on Noordin".

Rebuild: `python scripts/benchmark_noordin.py cases/noordin results/noordin` (~20 s).
