# Link-method benchmark for `run_case_analysis` (weights v1.1)

**Question:** which link-suggestion methods should the app use, and how well do they perform on real covert networks?

**Decision:**
1. **Ties without recorded communication** (`tie_without_recorded_communication`): rank pairs that share a non-communication tie (co-location, meetings, friendship…) but have no recorded communication, by evidence-weighted tie strength. This was the strongest method by far.
2. **Network proximity** (`network_proximity_ppr`): for unconnected pairs, use **personalised PageRank** instead of Adamic-Adar. It predicts future links better (significant) and ties on hidden-link recovery.

Both are implemented in `analysis_model/run_case_analysis.py`, and the shipped function was re-run on the benchmarks to confirm it reproduces these numbers.

## Data: real covert networks only
From `networkdata` v0.2.4 (MIT; files in `cases/benchmarks/source/`). Terror cells, drug and trafficking rings, gangs and corruption networks, coded from court records, investigations and reports.
- **Test A:** Noordin Top (79 people; communication recorded as its own layer).
- **Test B, predict ahead:** 8 time-sliced networks (17 November Greece, Australian Embassy 2004, Bali 2002, Christmas Eve 2000, Hamburg cell, Madrid 2004, Philippines bombing, Caviar in 11 phases). 36 period transitions with at least 3 new links.
- **Test C, edge hiding:** 17 single-layer networks (9/11 associates, Caviar, CielNet, cocaine and heroin dealing, Czech corruption, domestic-terror web, Italian gangs, JI Koschade, London gang, Madoff, Mali, Montreal gangs, Rhodes, Siren, Kenya–Tanzania, Togo).

## Protocol (fixed before results were seen)
- **A:** features from the 9 non-communication layers only; label = communication tie; 30 random halves, scored as selection and confirmation.
- **B:** graph up to period *t* → score every unconnected pair of active people → label = first linked in *t+1*. Earlier transitions **select**, each network's **last transition confirms**.
- **C:** hide 20% of links (30 repeats), score unconnected pairs, label = hidden link. Networks alternate between a **selection** group and a **confirmation** group.
- **Metrics:** average precision (AP), precision@10, and AP lift = AP ÷ base rate (makes networks comparable). Precision@10 is the expected value under random tie order.
- **Methods compared:** common neighbours, Adamic-Adar (the previous v1 method), resource allocation, Jaccard, preferential attachment, local path, Katz (length 3), personalised PageRank; for A also direct-tie strength (v1 weights), tie-type count and mixes.

## Results

**A. Noordin, hide and recover** (30 repeats; selection / confirmation)

| Method | AP lift | AP | P@10 |
|---|---:|---:|---:|
| **Direct-tie strength (weights v1)** | **11.0 / 11.2** | 0.72 / 0.72 | 1.00 / 1.00 |
| Direct-tie + resource allocation | 10.9 / 11.1 | 0.71 / 0.71 | 1.00 / 1.00 |
| Tie-type count | 8.4 / 8.6 | 0.55 / 0.55 | 0.93 / 0.97 |
| Resource allocation | 4.6 / 4.8 | 0.30 / 0.31 | 0.70 / 0.73 |
| Adamic-Adar | 4.4 / 4.5 | 0.29 / 0.29 | 0.61 / 0.61 |

⚠️ The Noordin layer weights in `weights.json` were set using Noordin's own statistics, so A shows the weighting is consistent, not proven out of sample. The independent held-out benchmark in `results/noordin/report.md` (logistic regression, AP 0.68 on an untouched test split) is the cleaner figure.

**B. Predict ahead** (8 networks; selection = 28 transitions, confirmation = 8)

| Method | Selection AP lift | Confirmation AP lift |
|---|---:|---:|
| **Personalised PageRank** | **3.13** | **1.93** |
| Local path | 2.81 | 1.40 |
| Katz-3 | 2.81 | 1.40 |
| Adamic-Adar (v1) | 2.73 | 1.71 |
| Resource allocation | 2.72 | 1.75 |
| Common neighbours | 2.40 | 1.37 |
| Preferential attachment | 2.27 | 1.22 |
| Jaccard | 2.13 | 1.29 |

Paired over all 36 transitions: personalised PageRank beats Adamic-Adar in **24** (2 ties); mean AP-lift gain +0.36, **95% bootstrap CI [+0.02, +0.72]**; median relative gain +15%.

**C. Edge hiding** (17 networks; selection 9 / confirmation 8)

| Method | Selection AP lift | Confirmation AP lift |
|---|---:|---:|
| Personalised PageRank | **8.57** | 9.05 |
| Adamic-Adar (v1) | 8.35 | 9.49 |
| Resource allocation | 8.33 | **9.55** |
| Katz-3 / local path | 7.09 | 7.57 |
| Common neighbours | 6.06 | 5.89 |
| Jaccard | 2.36 | 2.78 |

Paired: personalised PageRank vs Adamic-Adar, 9 wins of 17, CI [−0.97, +0.86], so **no difference**.

## Verification of the shipped function (`function_verification.json`)
- **A** via `tie_without_recorded_communication` on all 3,081 Noordin pairs: AP **0.676**, P@10 **1.0**, **10.4×** random. Slightly below the harness because pairs with no non-communication tie aren't listed by this method (they appear only in the proximity list).
- **B** via `network_proximity_ppr`: matches the harness exactly on 35 of 36 transitions. One transition differs by 0.005 AP because 32 of its 43 pairs have exactly tied scores and floating-point order breaks the ties differently. Mean AP 0.282 vs 0.250 for Adamic-Adar; better in 25 of 36.

## What these numbers mean, and don't
- They measure **ranking quality on coded, real covert networks**: how often true links rise to the top of the suggestion list. They aren't crime-detection accuracy, and they aren't GAStech accuracy (GAStech has no ground truth).
- **Predict-ahead lift is modest (about 2–3× random).** Future links are hard to predict from structure alone. Suggestions are leads for an investigator, not conclusions.
- **Direct evidence dominates:** across A, a recorded meeting, friendship or co-location tie is worth far more than shared contacts. That's why the app shows `tie_without_recorded_communication` first.
- Coded datasets miss ties; an unrecorded link isn't a confirmed non-link.
- Personalised PageRank uses unweighted transitions, exactly as benchmarked. Weighted variants weren't tested and aren't used.

Rebuild: `python scripts/benchmark_link_methods.py cases/benchmarks/source cases/noordin results/link_methods` (~10 s), then `python scripts/verify_function_benchmarks.py cases/benchmarks/source cases/noordin results/link_methods`.
